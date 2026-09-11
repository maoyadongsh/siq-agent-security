#!/usr/bin/env python3
"""Exercise the public Hermes CLI and native hooks in an isolated test profile.

Uses the real adapter enrollment endpoint, with a generated local configuration.
No fixture observer or manually issued Intent/binding is used. Installer and UI
activation remain separate unfinished integration work.
"""

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("native_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)

class Harness(fixture.Harness):
    def setup_authority(self):
        catalog = self.api("/v1/adapter/instances?platform=hermes")
        target = next(row for row in catalog["instances"] if row["active"])
        self.instance_id = target["instance_id"]
        self.agent = "hri-" + self.instance_id[3:]
        skill = self.root / "fixture-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: intent-fixture\ndescription: Read a synthetic report.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\nRead the fixture report.\n"
        )
        adm = self.api("/v1/admit", {"path": str(skill)})["admission"]
        fixture.require(adm["verdict"] != "quarantine", "benign fixture quarantined")
        result = self.api(
            "/v1/grants",
            {
                "admission_id": adm["admission_id"],
                "platform": self.platform,
                "subject_id": self.agent,
                "subject_type": "agent_instance",
                "redact_secrets": True,
            },
        )
        grant_path = "/v1/grants/" + result["grant"]["grant_id"]

        def action(name, **body):
            nonlocal result
            result = self.api(
                grant_path + "/" + name,
                {
                    "expected_revision": result["state_revision"],
                    "actor_id": "automated-fixture-operator",
                    **body,
                },
            )
            return result

        action(
            "patch-desired",
            tools=[self.read_tool, self.write_tool],
            **(
                {"network": [{"endpoint": host, "effect": "allow"} for host in self.network_endpoints]}
                if hasattr(self, "network_endpoints")
                else {}
            ),
            filesystem={
                "read_only": [str(self.workspace)],
                "read_write": [],
            },
        )
        for index, overlap in enumerate(result["grant"]["overlap_conflicts"]):
            if overlap["resolution"] == "unresolved":
                action("resolve-overlap", index=index)
        challenge = action("challenge")["challenge"]
        action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        fixture.require(result["grant"]["status"] == "approved", "grant approval did not transition")
        action("deploy")
        self.issued = self.api("/v1/runtime-identities", {
            "schema_version": "local-runtime-identity-create/v1",
            "instance_id": self.instance_id, "grant_id": result["grant"]["grant_id"],
            "expected_grant_revision": result["state_revision"],
            "actor_id": "automated-fixture-operator", "session_ttl_seconds": 28800,
        }, expected=201)
        fixture.require(self.issued["identity"]["runtime_state"] == "unverified", "issuance claimed protection")
        profile = Path(self.env["HERMES_HOME"])
        (profile / "plugins/siq-agent-security/config.json").write_text(json.dumps({
            "endpoint": self.endpoint, "token_path": self.issued["credential_path"],
            "runtime_identity_id": self.issued["identity"]["identity_id"],
            "agent_id": self.agent, "enforcement_mode": "block", "timeout_s": 2,
        }))
        self.env["SIQ_AGENT_SECURITY_AGENT_ID"] = "forged-environment-agent"
        fixture.require(self.api("/v1/intents")["items"] == [], "manual intent created")

    def assert_call(self, records, call_id, outcome, **unused):
        own = [row for row in records if row.get("tool_call_id") == call_id]
        decisions = [row for row in own if row.get("record_type") == "decision"]
        fixture.require(len(decisions) == 1, "decision missing or duplicated")
        row = decisions[0]
        fixture.require(row["action"] == outcome and row["authority_status"] == "valid", "wrong decision")
        fixture.require(row["intent_id"] == self.native_intent["intent_id"], "wrong intent")
        fixture.require(row["intent_digest"] == self.native_intent["digest"], "wrong intent digest")
        fixture.require(row["agent_id"] == self.agent, "agent config overridden")
        fixture.require(row["matched_grant_id"] == self.issued["identity"]["grant_ref"]["grant_id"], "wrong grant")
        fixture.require(len(own) == (1 if outcome == "deny" else 2), "unexpected observations")
        if outcome == "deny":
            fixture.require(row["reason_code"] == "grant_scope_violation", "wrong rejection layer")

    def public_cli(self):
        profile = Path(self.env["HERMES_HOME"])
        config = profile / "config.yaml"
        before = hashlib.sha256(config.read_bytes()).hexdigest()
        session = ""
        revoked = False
        received, auxiliary, failures = [], [], []
        forbidden = self.workspace / "company-a/must-not-exist.txt"
        confirmation = self.workspace / "company-a/confirmation.txt"
        confirmation.write_text("fixture-visible-company-a-confirmation\n")
        calls = [
            {
                "id": "allowed-first",
                "tool": "read_file",
                "params": {"path": str(confirmation)},
            },
            {
                "id": "write-denied",
                "tool": "write_file",
                "params": {"path": str(forbidden), "content": "must not execute"},
            },
            {
                "id": "allowed-last",
                "tool": "read_file",
                "params": {"path": str(self.workspace / "company-a/report.txt")},
            },
        ]

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
                    if self.path == "/api/show":
                        self.send_error(404)
                        return
                    fixture.require(self.path == "/v1/chat/completions", "unexpected model route")
                    names = {item.get("function", {}).get("name") for item in body.get("tools", [])}
                    if "read_file" not in names:
                        # Public CLI also generates titles / other plain text.
                        # These calls must never advance the tool probe sequence.
                        fixture.require(len(auxiliary) < 16, "auxiliary request budget")
                        auxiliary.append({"stream": bool(body.get("stream"))})
                        self.complete(
                            {"role": "assistant", "content": "SIQ synthetic check"}, "stop", bool(body.get("stream"))
                        )
                        return
                    results = [item for item in body.get("messages", []) if item.get("role") == "tool"]
                    index = len(received)
                    fixture.require(
                        index <= len(calls) and len(results) == index,
                        f"unexpected model retry or lost history: step={index} results={len(results)}",
                    )
                    for call, result in zip(calls[:index], results, strict=True):
                        fixture.require(result["tool_call_id"] == call["id"], "tool call identity changed")
                        text = str(result.get("content", ""))
                        if call["id"].startswith("allowed") and not revoked:
                            if "fixture-visible-company-a" not in text:
                                category = "siq_block" if "siq-agent-security" in text else "host_result"
                                raise RuntimeError("allowed read missing: " + category)
                        else:
                            fixture.require("siq-agent-security" in text, "native block missing")
                    message = {"role": "assistant", "content": "SIQ_RUNTIME_CHECK_COMPLETE"}
                    finish = "stop"
                    if index < len(calls):
                        call = calls[index]
                        message = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {"name": call["tool"], "arguments": json.dumps(call["params"])},
                                }
                            ],
                        }
                        finish = "tool_calls"
                    received.append({"tool_result_count": len(results), "stream": bool(body.get("stream"))})
                    self.complete(message, finish, bool(body.get("stream")))
                except Exception as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc)[:256])
                    self.send_error(500, "synthetic protocol failed")

        model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        thread = threading.Thread(target=model.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{model.server_port}"
        env = {
            **self.env,
            "CUSTOM_BASE_URL": endpoint + "/v1",
        }
        try:
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
                    "Execute the SIQ synthetic runtime check.",
                ],
                cwd=self.workspace,
                env=env,
                capture_output=True,
                timeout=90,
                check=False,
            )
            if process.returncode:
                raise RuntimeError("public CLI did not complete in isolated fixture")
            fixture.require(not failures and len(received) == 4, "native conversation did not execute all probes")
            fixture.require(not forbidden.exists(), "forbidden write executed")
            records = self.receipts()
            fixture.require(len(records) == 5, "unexpected receipt count")
            session = records[0]["session_id"]
            contracts = self.api("/v1/intents")["items"]
            fixture.require(len(contracts) == 1, "manual or duplicate intent was created")
            self.native_intent = contracts[0]
            fixture.require(self.native_intent["authority"]["issuer"] == "local-runtime-identity", "wrong issuer")
            bindings = self.api("/v1/intent-bindings")["items"]
            fixture.require(len(bindings) == 1 and bindings[0]["session_id"] == session, "native session not bound")
            fixture.require(bindings[0]["grant_ref"] == self.issued["identity"]["grant_ref"], "wrong grant selection")
            for call in calls:
                self.assert_call(records, call["id"], "deny" if call["id"] == "write-denied" else "allow")
            fixture.require(
                all(record["session_id"] == session for record in records), "receipts do not match native session"
            )
            first_requests = list(received)
            self.api("/v1/runtime-identities/" + self.issued["identity"]["identity_id"] + "/revoke", {
                "schema_version": "local-runtime-identity-revoke/v1", "actor_id": "automated-fixture-operator",
            })
            revoked = True
            received.clear()
            after_revoke = subprocess.run(
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
                    "Execute the SIQ synthetic runtime check.",
                ],
                cwd=self.workspace,
                env=env,
                capture_output=True,
                timeout=90,
                check=False,
            )
            fixture.require(after_revoke.returncode == 0 and not failures and len(received) == 4,
                            "revoked native conversation did not complete with blocked tools")
            fixture.require(len(self.receipts()) == 5, "revoked credential produced authorized receipts")
            pending = [json.loads(line) for line in (self.state / "pending/decisions.jsonl").read_text().splitlines()]
            fixture.require(len(pending) == 3 and all(row["outcome"] == "deny" for row in pending),
                            "missing revoked-call fail-closed evidence")
            fixture.require(len({row["session_id"] for row in pending}) == 1
                            and pending[0]["session_id"] != session, "revoked run did not use a new native session")
            fixture.require(not forbidden.exists(), "revoked write executed")
            self.stop()
            verified = json.loads(self.command([str(self.binary), "verify"]))
            fixture.require(verified["verified"], "receipt chain invalid")
            return {
                "schema_version": "personal-hermes-identity-runtime-smoke/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "native_cli_sha256": hashlib.sha256(self.args.hermes_cli.read_bytes()).hexdigest(),
                "native_entrypoint": "public hermes chat --oneshot; normal Agent loop and plugin lifecycle",
                "session_id_source": "native pre_tool_call; actual SIQ adapter automatically enrolls; not injected",
                "checks": [
                    "native_cli_started",
                    "native_generated_session_automatically_bound",
                    "instance_credential_used_without_manual_intent",
                    "environment_cannot_override_managed_agent",
                    "allowed_read",
                    "write_denied_before_execution",
                    "allowed_after_denial",
                    "receipt_chain_verified",
                    "revoked_identity_blocks_new_native_session",
                    "revoked_calls_record_unsigned_denials",
                ],
                "receipt_count": len(records),
                "model_requests": first_requests,
                "revoked_model_requests": received,
                "revoked_pending_denials": len(pending),
                "auxiliary_requests": auxiliary,
                "profile_config_unchanged": before == hashlib.sha256(config.read_bytes()).hexdigest(),
                "limitations": [
                    "isolated profile configured by harness; installer and UI activation not integrated",
                    "synthetic model and operator; no real-user approval, Skill attribution or OS isolation proof",
                    "native startup may produce host history/cache; network isolation is not claimed",
                ],
            }
        finally:
            model.shutdown()
            model.server_close()
            thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-cli", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.hermes_cli, args.binary = args.hermes_cli.resolve(), args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix="siq-hermes-identity-runtime-") as temporary:
        root = Path(temporary)
        harness = Harness(root, args)
        home = root / "home"
        home.mkdir(mode=0o700)
        harness.env.update({"HOME": str(home), "USERPROFILE": str(home), "LOCALAPPDATA": str(home / "AppData/Local")})
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.public_cli()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
