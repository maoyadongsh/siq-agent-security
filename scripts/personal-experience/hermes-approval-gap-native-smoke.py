#!/usr/bin/env python3
"""Verify the closed Hermes approval gap against a real daemon and native tool.

The public Hermes process first receives a held write and blocks it before the
side effect. A synthetic local operator resolves the immutable confirmation
while that same process is alive. Hermes then retries the same parameters with
a fresh tool-call ID; the installed adapter reads approval, atomically reserves
one execution and the real file tool writes exactly once. A separate denial
run proves retry remains blocked with no side effect. The model endpoint is a
local deterministic fixture; no real user configuration, data or model calls.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("native_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)

OBSERVER = """import json, os, urllib.request
def attach(session_id="", **unused):
    body = json.dumps({"session_id": session_id}).encode()
    req = urllib.request.Request(os.environ["SIQ_FIXTURE_ATTACH"], data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["SIQ_FIXTURE_NONCE"]})
    with urllib.request.urlopen(req, timeout=5) as response:
        if response.status != 200: raise RuntimeError("fixture attach failed")
def register(ctx):
    ctx.register_hook("pre_llm_call", attach)
"""

CONTENT = "fixture-approval-gap-content"
CONSOLE_GUIDANCE = "Approve in the console"
LABELS = ("approve", "deny")


class Harness(fixture.Harness):
    def setup_authority(self):
        skill = self.root / "fixture-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: approval-gap-fixture\ndescription: Write one synthetic report file.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\nWrite the fixture report.\n"
        )
        adm = self.api("/v1/admit", {"path": str(skill)})["admission"]
        fixture.require(adm["verdict"] != "quarantine", "benign fixture quarantined")
        result = self.api(
            "/v1/grants",
            {
                "admission_id": adm["admission_id"],
                "platform": self.platform,
                "subject_id": fixture.AGENT,
                "subject_type": "agent_instance",
                "redact_secrets": True,
            },
        )
        grant_path = "/v1/grants/" + result["grant"]["grant_id"]

        def action(name, **body):
            nonlocal result
            result = self.api(
                grant_path + "/" + name,
                {"expected_revision": result["state_revision"], "actor_id": "automated-fixture-operator", **body},
            )
            return result

        action(
            "patch-desired",
            tools=[self.read_tool, self.write_tool],
            filesystem={"read_only": [str(self.workspace)], "read_write": [str(self.workspace)]},
        )
        for index, overlap in enumerate(result["grant"]["overlap_conflicts"]):
            if overlap["resolution"] == "unresolved":
                action("resolve-overlap", index=index)
        action("require-approval", schema_version="grant-tool-approval/v1", tools=[self.write_tool])
        fixture.require(
            any(
                fact.get("domain") == "tool"
                and fact.get("resource", {}).get("value") == self.write_tool
                and fact.get("conditions", {}).get("require_approval") is True
                for fact in result["grant"].get("facts", [])
            ),
            "require_approval condition missing from grant facts",
        )
        self.checks.append("grant_require_approval_applied")
        challenge = action("challenge")["challenge"]
        action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        fixture.require(result["grant"]["status"] == "approved", "grant approval did not transition")
        action("deploy")
        fixture.require(result["grant"]["status"] == "deployed", "grant deploy did not transition")
        now = datetime.now(UTC)

        def stamp(t):
            return t.strftime("%Y-%m-%dT%H:%M:%SZ")

        self.intent_id = "int-approval-gap-fixture"
        intent = self.api(
            "/v1/intents",
            {
                "schema_version": "intent/v2",
                "intent_id": self.intent_id,
                "task_id": "task-approval-gap-fixture",
                "principal": {"type": "user", "id": "fixture"},
                "agent": {"id": fixture.AGENT, "platform": self.platform},
                "purpose": "write one fixture file under console approval",
                "allowed_tools": [self.read_tool, self.write_tool],
                "allowed_effects": ["file.read", "file.write"],
                "resource_constraints": [
                    {"domain": "filesystem", "operator": "prefix", "value": str(self.workspace / "company-a")}
                ],
                "parameter_constraints": [],
                "issued_at": stamp(now - timedelta(minutes=1)),
                "valid_from": stamp(now - timedelta(minutes=1)),
                "expires_at": stamp(now + timedelta(hours=1)),
                "authority": {"issuer": "local-admin", "revision": "r1", "evidence_ids": []},
            },
            expected=201,
        )
        self.digest = intent["digest"]
        decision_token = (self.state / "token").read_text().strip()
        self.api("/v1/intents", token=decision_token, expected=403)
        self.api("/v1/confirmations", token=decision_token, expected=403)
        self.checks.append("decision_token_cannot_read_authority_or_confirmations")

    def pending_confirmation(self, call_id):
        items = self.api("/v1/confirmations")["items"]
        matches = [item for item in items if item.get("tool_call_id") == call_id]
        fixture.require(len(matches) == 1, call_id + ": confirmation inbox mismatch")
        item = matches[0]
        fixture.require(item["status"] == "pending", call_id + ": confirmation not pending")
        fixture.require(
            item["tool"] == self.write_tool and item["platform"] == "hermes" and item["agent_id"] == fixture.AGENT,
            call_id + ": confirmation identity mismatch",
        )
        return item

    def confirmation_status(self, call_id):
        items = self.api("/v1/confirmations")["items"]
        matches = [item.get("status") for item in items if item.get("tool_call_id") == call_id]
        fixture.require(len(matches) == 1, call_id + ": confirmation inbox lost the hold")
        return matches[0]

    def resolve(self, item, approve):
        return self.api(
            "/v1/confirmations/" + item["action_id"] + "/resolve",
            {
                "schema_version": "local-confirmation-resolve/v1",
                "decision_receipt_id": item["decision_receipt_id"],
                "decision_hash": item["decision_hash"],
                "params_digest": item["params_digest"],
                "approve": approve,
                "actor_id": "fixture-console-reviewer",
            },
        )

    def hold_status(self, item, session_id):
        token = (self.state / "token").read_text().strip()
        return self.api(
            "/v1/hold-status",
            {
                "platform": "hermes",
                "session_id": session_id,
                "agent_id": fixture.AGENT,
                "task_id": item.get("task_id", ""),
                "runtime_task_id": item.get("runtime_task_id", ""),
                "tool": self.write_tool,
                "tool_call_id": item["tool_call_id"],
                "action_id": item["action_id"],
                "decision_receipt_id": item["decision_receipt_id"],
                "params": self.write_params,
            },
            token=token,
        )

    def held_decision(self, records, call_id):
        own = [r for r in records if r.get("tool_call_id") == call_id]
        decisions = [r for r in own if r.get("record_type") == "decision"]
        observations = [r for r in own if r.get("record_type") == "observation"]
        fixture.require(len(decisions) == 1, call_id + ": missing/duplicate decision")
        decision = decisions[0]
        fixture.require(
            decision["action"] == "hold", call_id + ": unexpected action " + str(decision.get("action"))
        )
        fixture.require(decision["intent_binding"] == "bound", call_id + ": hold was not intent bound")
        fixture.require(decision["intent_id"] == self.intent_id, call_id + ": wrong authority")
        fixture.require(not observations, call_id + ": held call produced an execution observation")
        return decision

    def probe(self):
        profile = Path(self.env["HERMES_HOME"])
        observer = profile / "plugins/siq-approval-gap-observer"
        observer.mkdir()
        (observer / "plugin.yaml").write_text(
            "name: siq-approval-gap-observer\nversion: 0.0.1\ndescription: Synthetic session observer.\n"
        )
        (observer / "__init__.py").write_text(OBSERVER)
        config = profile / "config.yaml"
        config.write_text(
            "plugins:\n  enabled: [siq-agent-security, siq-approval-gap-observer]\nterminal:\n  env: local\n"
        )
        self.command(
            [str(self.args.hermes_cli), "plugins", "enable", "siq-approval-gap-observer", "--no-allow-tool-override"]
        )
        config_digest = hashlib.sha256(config.read_bytes()).hexdigest()
        target = self.workspace / "company-a/approval-gap-target.txt"
        self.write_params = {"path": str(target), "content": CONTENT}
        nonce = secrets.token_hex(32)
        sessions = {}
        state = {
            "label": "", "session": "", "received": 0, "blocks": [],
            "resolutions": [], "aux": 0, "failures": [],
        }
        guard = threading.Lock()
        controller = self

        class Model(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, value):
                encoded = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                if self.path == "/v1/models":
                    self.respond(
                        {
                            "object": "list",
                            "data": [
                                {"id": "siq-synthetic-fixture", "object": "model", "owned_by": "fixture", "created": 0}
                            ],
                        }
                    )
                else:
                    self.send_error(404)

            def complete(self, message, finish, stream):
                payload = {"id": "siq-fixture", "created": 0, "model": "siq-synthetic-fixture"}
                if not stream:
                    self.respond(
                        {
                            **payload,
                            "object": "chat.completion",
                            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                        }
                    )
                    return
                if "tool_calls" in message:
                    message["tool_calls"][0]["index"] = 0
                chunks = [
                    {
                        **payload,
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": message, "finish_reason": None}],
                    },
                    {
                        **payload,
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                    },
                ]
                raw = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(raw.encode())))
                self.end_headers()
                self.wfile.write(raw.encode())

            def do_POST(self):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    fixture.require(0 < size <= 2_000_000, "request budget")
                    body = json.loads(self.rfile.read(size))
                    if self.path == "/attach":
                        fixture.require(
                            self.headers.get("Authorization") == "Bearer " + nonce, "observer credential"
                        )
                        value = body.get("session_id")
                        fixture.require(
                            isinstance(value, str) and 0 < len(value) <= 256, "native session missing"
                        )
                        with guard:
                            label = state["label"]
                            fixture.require(
                                bool(label) and not state["session"], "attach outside a run or repeated"
                            )
                            if value not in sessions:
                                controller.api(
                                    "/v1/intent-bindings",
                                    {
                                        "platform": "hermes",
                                        "session_id": value,
                                        "agent_id": fixture.AGENT,
                                        "intent_id": controller.intent_id,
                                    },
                                    expected=201,
                                )
                            sessions[value] = label
                            state["session"] = value
                        self.respond({"attached": True})
                        return
                    if self.path == "/api/show":
                        self.send_error(404)
                        return
                    fixture.require(self.path == "/v1/chat/completions", "unexpected model route")
                    names = {item.get("function", {}).get("name") for item in body.get("tools", [])}
                    if "read_file" not in names:
                        # Public CLI also generates titles / other plain text.
                        # These calls must never advance the tool probe sequence.
                        with guard:
                            state["aux"] += 1
                            fixture.require(state["aux"] <= 48, "auxiliary request budget")
                        self.complete(
                            {"role": "assistant", "content": "SIQ synthetic check"}, "stop", bool(body.get("stream"))
                        )
                        return
                    with guard:
                        fixture.require(bool(state["session"]), "model called before native session hook")
                        results = [item for item in body.get("messages", []) if item.get("role") == "tool"]
                        index = state["received"]
                        fixture.require(
                            index <= 2 and len(results) == index,
                            f"unexpected model retry or lost history: step={index} results={len(results)}",
                        )
                        original_call_id = "write-" + state["label"] + "-original"
                        retry_call_id = "write-" + state["label"] + "-retry"
                        if index == 1:
                            fixture.require(
                                results[0]["tool_call_id"] == original_call_id,
                                "original tool call identity changed",
                            )
                            text = str(results[0].get("content", ""))
                            fixture.require("siq-agent-security" in text, "native block missing adapter reason")
                            fixture.require(CONTENT not in text, "block message leaked fixture write content")
                            state["blocks"].append(
                                {"label": state["label"], "console_guidance": CONSOLE_GUIDANCE in text}
                            )
                            item = controller.pending_confirmation(original_call_id)
                            approve = state["label"] == "approve"
                            resolution = controller.resolve(item, approve=approve)
                            fixture.require(
                                resolution["action"] == ("allow" if approve else "deny"),
                                "console resolution action mismatch",
                            )
                            status = controller.hold_status(item, state["session"])
                            fixture.require(
                                status["status"] == ("approved" if approve else "denied"),
                                "resolved hold status mismatch",
                            )
                            state["resolutions"].append(
                                {
                                    "label": state["label"], "approve": approve,
                                    "action_id": item["action_id"], "status": status["status"],
                                }
                            )
                        if index == 2:
                            fixture.require(
                                results[1]["tool_call_id"] == retry_call_id,
                                "retry tool call identity changed",
                            )
                            text = str(results[1].get("content", ""))
                            if state["label"] == "approve":
                                fixture.require(target.read_text() == CONTENT, "approved native write did not execute")
                                fixture.require("siq-agent-security" not in text, "approved retry stayed blocked")
                            else:
                                fixture.require(not target.exists(), "denied retry executed")
                                fixture.require("siq-agent-security" in text, "denied retry was not blocked")
                        message = {"role": "assistant", "content": "SIQ_APPROVAL_RETRY_CHECK_COMPLETE"}
                        finish = "stop"
                        if index in (0, 1):
                            message = {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": original_call_id if index == 0 else retry_call_id,
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": json.dumps(controller.write_params),
                                        },
                                    }
                                ],
                            }
                            finish = "tool_calls"
                        state["received"] += 1
                    self.complete(message, finish, bool(body.get("stream")))
                except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
                    state["failures"].append(type(exc).__name__ + ": " + str(exc)[:256])
                    self.send_error(500, "synthetic protocol failed")

        model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        thread = threading.Thread(target=model.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{model.server_port}"

        def run(label):
            with guard:
                state.update({"label": label, "session": "", "received": 0})
            env = {
                **self.env,
                "CUSTOM_BASE_URL": endpoint + "/v1",
                "SIQ_FIXTURE_ATTACH": endpoint + "/attach",
                "SIQ_FIXTURE_NONCE": nonce,
            }
            process = subprocess.run(
                [
                    str(self.args.hermes_cli),
                    "chat",
                    "--provider",
                    "custom",
                    "--model",
                    "siq-synthetic-fixture",
                    "--toolsets",
                    "file",
                    "--max-turns",
                    "6",
                    "--run-budget",
                    "45",
                    "--ignore-rules",
                    "--quiet",
                    "--oneshot",
                    "-q",
                    "Execute the SIQ synthetic approval retry check.",
                ],
                cwd=self.workspace,
                env=env,
                capture_output=True,
                timeout=90,
                check=False,
            )
            if process.returncode:
                raise RuntimeError("public CLI did not complete in isolated fixture")
            fixture.require(not state["failures"], "synthetic model protocol failed")
            fixture.require(state["received"] == 3, "native conversation did not complete the probe")
            fixture.require(bool(state["session"]), "native session was not attached")
            if label == "approve":
                fixture.require(target.read_text() == CONTENT, "approved native retry did not write target")
            else:
                fixture.require(not target.exists(), "denied native retry wrote target")
            return {"label": label, "session_id": state["session"], "target_file_created": target.exists()}

        attempts = []
        try:
            attempts.append(run("approve"))
            target.unlink()
            attempts.append(run("deny"))
        finally:
            model.shutdown()
            model.server_close()
            thread.join(timeout=2)
        fixture.require(len(attempts) == 2, "probe did not complete all native runs")
        fixture.require(
            all(block["console_guidance"] for block in state["blocks"]) and len(state["blocks"]) == 2,
            "hold block message missing console guidance",
        )
        records = self.receipts()
        decisions = {}
        for label in LABELS:
            decisions[label] = self.held_decision(records, "write-" + label + "-original")
        resolutions_on_chain = [r for r in records if r.get("record_type") == "hold_resolution"]
        fixture.require(len(resolutions_on_chain) == 2, "expected exactly two hold resolutions")
        fixture.require(
            resolutions_on_chain[0]["action"] == "allow"
            and resolutions_on_chain[0]["decision_receipt_id"] == decisions["approve"]["receipt_id"],
            "approval resolution missing or misattributed",
        )
        fixture.require(
            resolutions_on_chain[1]["action"] == "deny"
            and resolutions_on_chain[1]["decision_receipt_id"] == decisions["deny"]["receipt_id"],
            "denial resolution missing or misattributed",
        )
        reservations = [r for r in records if r.get("record_type") == "hold_reservation"]
        observations = [r for r in records if r.get("record_type") == "observation"]
        fixture.require(len(reservations) == 1, "approved retry did not create exactly one reservation")
        fixture.require(
            reservations[0].get("tool_call_id") == "write-approve-retry"
            and reservations[0].get("decision_receipt_id") == decisions["approve"]["receipt_id"],
            "reservation is not bound to the approved retry",
        )
        fixture.require(
            len(observations) == 1
            and observations[0].get("decision_receipt_id") == reservations[0].get("receipt_id"),
            "native execution observation is not linked to the reservation",
        )
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        fixture.require(verified["verified"], "receipt chain invalid")
        self.checks.extend(
            [
                "native_cli_runs_completed",
                "hold_blocks_before_execution",
                "block_message_points_to_console",
                "console_approval_recorded",
                "approved_retry_reserved_before_native_execution",
                "approved_native_side_effect_exactly_once",
                "console_denial_recorded",
                "denied_retry_blocked_without_execution",
                "reservation_and_observation_linked",
                "receipt_chain_verified",
            ]
        )
        return {
            "schema_version": "personal-hermes-approved-retry-native-smoke/v2",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True,
            "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "native_cli_sha256": hashlib.sha256(self.args.hermes_cli.read_bytes()).hexdigest(),
            "native_entrypoint": "public hermes chat --oneshot; normal Agent loop and plugin lifecycle",
            "session_id_source": "native pre_llm_call; fixture observer only; not injected",
            "checks": self.checks,
            "attempts": [
                {
                    "label": label,
                    "tool_call_id": "write-" + label + "-original",
                    "decision_action": decisions[label]["action"],
                    "decision_reason_code": decisions[label].get("reason_code"),
                    "intent_binding": decisions[label].get("intent_binding"),
                    "console_guidance_in_block": True,
                    "target_file_created": label == "approve",
                    "execution_observations": 1 if label == "approve" else 0,
                }
                for label in LABELS
            ],
            "console_resolutions": state["resolutions"],
            "receipt_count": len(records),
            "auxiliary_requests": state["aux"],
            "profile_config_unchanged": config_digest == hashlib.sha256(config.read_bytes()).hexdigest(),
            "limitations": [
                "approved execution is at-most-once locally; external systems can still require uncertain reconciliation",
                "synthetic model, operator and target; no real user data, contacts or external services",
                "isolated fixture profile and daemon state; no claim about other platforms or adapter versions",
                "desktop notification delivery and manual browser clicking are covered by separate evidence",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-cli", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.hermes_cli, args.binary = args.hermes_cli.resolve(), args.binary.resolve()
    fixture.require(args.hermes_cli.is_file(), "installed Hermes CLI not found; use --hermes-cli")
    fixture.require(args.binary.is_file(), "candidate daemon binary not found; use --binary")
    with tempfile.TemporaryDirectory(prefix="siq-hermes-approval-gap-") as temporary:
        root = Path(temporary)
        harness = Harness(root, args)
        home = root / "home"
        home.mkdir(mode=0o700)
        harness.env.update({"HOME": str(home), "USERPROFILE": str(home), "LOCALAPPDATA": str(home / "AppData/Local")})
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.probe()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        # Subprocess output may contain pairing codes or tool data; never echo it.
        print(f"approval-gap probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
