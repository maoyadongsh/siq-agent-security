#!/usr/bin/env python3
"""Prove R01 SEC attribution through a real Hermes CLI/plugin/tool lifecycle.

The model endpoint is a local deterministic fixture and has no external or
paid provider. A test-only pre_llm observer reports Hermes-generated session
and task IDs to this harness; the harness uses the product runtime-enrollment
and admin SEC APIs. Tool decisions and dispatch still run in the unmodified
public Hermes process through the installed SIQ adapter.
"""

from __future__ import annotations

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
loader = importlib.util.spec_from_file_location(
    "installed_fixture", REPO / "scripts/personal-experience/installed-skill-runtime-native-smoke.py"
)
installed = importlib.util.module_from_spec(loader)
loader.loader.exec_module(installed)
fixture = installed.fixture


class Harness(installed.Harness):
    def setup_authority(self):
        super().setup_authority()
        self.narrow_install = self.skill_installation["install_id"]
        self.product_config = (Path(self.env["HERMES_HOME"]) / "config.yaml").read_bytes()
        self.broad_install = self._install_broad_skill()

    def _install_broad_skill(self):
        skill = self.root / "fixture-broad-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: broad-fixture\ndescription: Write a synthetic report.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\nWrite the requested fixture report.\n"
        )
        imported = self.api(
            "/v1/skill-imports",
            {
                "schema_version": "local-skill-import-create/v1",
                "import_id": "si-" + "d" * 32,
                "source_kind": "local_dir",
                "path": str(skill),
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
        )["import"]
        result = self.api(
            "/v1/skill-imports/" + imported["import_id"] + "/permissions",
            {
                "schema_version": "local-skill-import-permission-create/v1",
                "request_id": "ip-" + "e" * 32,
                "artifact_digest": imported["artifact_digest"],
                "analysis_sha256": imported["analysis_sha256"],
                "instance_id": self.instance_id,
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
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
        challenge = action("challenge")["challenge"]
        action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        plan = self.api(
            "/v1/skill-installations/plans",
            {
                "schema_version": "local-skill-install-stage-create/v1",
                "request_id": "is-" + "f" * 32,
                "grant_id": result["grant"]["grant_id"],
                "expected_revision": result["state_revision"],
                "instance_id": self.instance_id,
                "directory_name": "broad-fixture",
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
        )["plan"]
        applied = self.api(
            "/v1/skill-installations/apply",
            {
                "schema_version": "local-skill-install-apply/v1",
                "plan_id": plan["plan_id"],
                "plan_signature": plan["signature"],
                "actor_id": "automated-fixture-operator",
                "confirm_install": True,
            },
        )
        self.api(
            "/v1/skill-installations/operations/" + applied["install_id"] + "/activate",
            {
                "schema_version": "local-skill-install-activate/v1",
                "operation_signature": applied["operation"]["signature"],
                "expected_revision": result["state_revision"],
                "actor_id": "automated-fixture-operator",
                "confirm_instance_scope": True,
            },
        )
        return applied["install_id"]

    def _install_bootstrap_observer(self, endpoint):
        profile = Path(self.env["HERMES_HOME"])
        plugin = profile / "plugins/sec-bootstrap"
        plugin.mkdir(parents=True)
        (plugin / "plugin.yaml").write_text(
            "name: sec-bootstrap\nversion: 1.0.0\ndescription: Isolated R01 native test synchronizer.\n"
            "provides_hooks:\n  - pre_llm_call\nhooks:\n  - pre_llm_call\n"
        )
        (plugin / "__init__.py").write_text(
            "import json, os, urllib.request\n"
            "_done = set()\n"
            "def _pre_llm_call(session_id='', task_id='', **_):\n"
            "    key = (session_id, task_id)\n"
            "    if key in _done: return None\n"
            "    if not session_id or not task_id: raise RuntimeError('missing native identity')\n"
            "    body = json.dumps({'session_id': session_id, 'task_id': task_id}).encode()\n"
            "    req = urllib.request.Request(\n"
            "        os.environ['SIQ_SEC_BOOTSTRAP_URL'], data=body,\n"
            "        headers={'Content-Type':'application/json'},\n"
            "    )\n"
            "    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
            "    with opener.open(req, timeout=20) as response:\n"
            "        result = json.loads(response.read(4097))\n"
            "    if response.status != 200 or result != {'ready': True}: raise RuntimeError('SEC bootstrap rejected')\n"
            "    _done.add(key)\n"
            "def register(ctx): ctx.register_hook('pre_llm_call', _pre_llm_call)\n"
        )
        config = profile / "config.yaml"
        self.command(
            [str(self.args.hermes_cli), "plugins", "enable", "sec-bootstrap"],
            cwd=self.workspace,
            env=self.env,
        )
        fixture.require("sec-bootstrap" in config.read_text(), "fixture observer was not enabled")
        self.env["SIQ_SEC_BOOTSTRAP_URL"] = endpoint

    def _context_body(self, install_id, session_id, task_id):
        return {
            "schema_version": "local-skill-execution-context-issue/v1",
            "instance_id": self.instance_id,
            "session_id": session_id,
            "task_id": task_id,
            "install_id": install_id,
            "ttl_seconds": 3600,
            "actor_id": "automated-fixture-operator",
            "confirm_issue": True,
        }

    @staticmethod
    def _complete(handler, message, finish, stream):
        base = {"id": "siq-sec-fixture", "created": 0, "model": "siq-synthetic-fixture"}
        if not stream:
            handler.respond(
                {
                    **base,
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
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": message, "finish_reason": None}],
            },
            {
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        raw = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Content-Length", str(len(raw.encode())))
        handler.end_headers()
        handler.wfile.write(raw.encode())

    def _run_native(self, calls, prompt, expected_prompt_text="intent-fixture", skills=()):
        received, failures, saw_skill = [], [], []
        harness = self

        class Model(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, value):
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path != "/v1/models":
                    self.send_error(404)
                    return
                self.respond(
                    {
                        "object": "list",
                        "data": [
                            {"id": "siq-synthetic-fixture", "object": "model", "created": 0, "owned_by": "fixture"}
                        ],
                    }
                )

            def do_POST(self):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    fixture.require(0 < size <= 2_000_000, "model request budget")
                    body = json.loads(self.rfile.read(size))
                    if self.path == "/api/show":
                        self.send_error(404)
                        return
                    fixture.require(self.path == "/v1/chat/completions", "unexpected model route")
                    names = {item.get("function", {}).get("name") for item in body.get("tools", [])}
                    if "read_file" not in names:
                        harness._complete(
                            self, {"role": "assistant", "content": "SIQ fixture"}, "stop", bool(body.get("stream"))
                        )
                        return
                    # Inspect only host-owned prompt material. Searching the
                    # whole request would let the user prompt itself satisfy
                    # this assertion without Hermes loading the Skill.
                    host_prompt = {
                        "messages": [
                            message
                            for message in body.get("messages", [])
                            if message.get("role") in {"system", "developer"}
                        ],
                        "tools": body.get("tools", []),
                    }
                    saw_skill.append(expected_prompt_text in json.dumps(host_prompt))
                    results = [item for item in body.get("messages", []) if item.get("role") == "tool"]
                    index = len(received)
                    fixture.require(index <= len(calls) and len(results) == index, "unexpected model history")
                    for call, result in zip(calls[:index], results, strict=True):
                        fixture.require(result["tool_call_id"] == call["id"], "tool call identity changed")
                        text = str(result.get("content", ""))
                        if call["outcome"] == "allow":
                            category = "siq_block" if "siq-agent-security" in text else "host_result"
                            fixture.require(
                                "fixture-visible-company-a" in text, "allowed read did not execute: " + category
                            )
                        else:
                            fixture.require("siq-agent-security" in text, "denied call was not blocked by adapter")
                    message, finish = {"role": "assistant", "content": "SIQ_SEC_NATIVE_COMPLETE"}, "stop"
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
                    received.append(index)
                    harness._complete(self, message, finish, bool(body.get("stream")))
                except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc)[:200])
                    self.send_error(500, "synthetic model protocol failed")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = {**self.env, "CUSTOM_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1"}
        try:
            command = [
                str(self.args.hermes_cli),
                "chat",
                "--provider",
                "custom",
                "--model",
                "siq-synthetic-fixture",
                "--toolsets",
                "file",
                "--max-turns",
                "5",
                "--run-budget",
                "45",
                "--ignore-rules",
                "--quiet",
            ]
            for skill in skills:
                command.extend(["--skills", skill])
            command.extend(["--oneshot", "-q", prompt])
            process = subprocess.run(
                command,
                cwd=self.workspace,
                env=env,
                capture_output=True,
                timeout=90,
                check=False,
            )
            if process.returncode != 0:
                raw = process.stderr or process.stdout or b""
                detail = raw.decode(errors="replace")[-1200:].replace(str(self.root), "<fixture>")
                receipt_summary = [
                    {
                        key: row.get(key)
                        for key in ("tool_call_id", "action", "reason_code", "task_id", "skill_attribution")
                    }
                    for row in self.receipts()
                    if row.get("record_type") == "decision"
                ]
                raise RuntimeError(
                    "public Hermes CLI failed: "
                    + detail
                    + " model="
                    + repr(failures)
                    + " controller="
                    + repr(getattr(self, "controller_failures", []))
                    + " receipts="
                    + repr(receipt_summary)
                )
            fixture.require(not failures and len(received) == len(calls) + 1, "native model sequence incomplete")
            fixture.require(any(saw_skill), "installed Skill was absent from the native prompt")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @staticmethod
    def _call_binding(record, params):
        payload = {
            "platform": record["platform"],
            "session_id": record["session_id"],
            "agent_id": record["agent_id"],
            "task_id": record.get("runtime_task_id") or record["task_id"] or "-",
            "tool": record["tool"],
            "tool_call_id": record["tool_call_id"],
            "params": params,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()

    def native_sec(self):
        controller_failures = []
        self.controller_failures = controller_failures
        subjects = []
        lock = threading.Lock()
        harness = self

        class Bootstrap(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, status, value):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                try:
                    fixture.require(self.path == "/bind", "unexpected bootstrap route")
                    size = int(self.headers.get("Content-Length", "0"))
                    fixture.require(0 < size <= 2048, "bootstrap request budget")
                    body = json.loads(self.rfile.read(size))
                    fixture.require(set(body) == {"session_id", "task_id"}, "bootstrap request fields")
                    session_id, task_id = body["session_id"], body["task_id"]
                    fixture.require(
                        isinstance(session_id, str) and 0 < len(session_id) <= 256, "native session invalid"
                    )
                    fixture.require(isinstance(task_id, str) and 0 < len(task_id) <= 256, "native task invalid")
                    with lock:
                        pair = (session_id, task_id)
                        if pair not in subjects:
                            subjects.append(pair)
                        if len(subjects) == 1:
                            credential = Path(harness.issued["credential_path"]).read_text().strip()
                            harness.api(
                                "/v1/runtime-sessions",
                                {"schema_version": "local-runtime-session-enroll/v1", "session_id": session_id},
                                token=credential,
                            )
                            broad = harness.api(
                                "/v1/skill-contexts",
                                harness._context_body(harness.broad_install, session_id, task_id),
                                expected=409,
                            )
                            fixture.require(
                                broad["error"] == "skill_context_grant_changed", "other Skill borrowed identity"
                            )
                            harness.broad_rejection = broad["error"]
                            harness.sec = harness.api(
                                "/v1/skill-contexts",
                                harness._context_body(harness.narrow_install, session_id, task_id),
                                expected=201,
                            )
                        self.respond(200, {"ready": True})
                except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
                    controller_failures.append(type(exc).__name__ + ": " + str(exc)[:200])
                    self.respond(500, {"ready": False})

        controller = ThreadingHTTPServer(("127.0.0.1", 0), Bootstrap)
        thread = threading.Thread(target=controller.serve_forever, daemon=True)
        thread.start()
        self._install_bootstrap_observer(f"http://127.0.0.1:{controller.server_port}/bind")
        forbidden = self.workspace / "company-a/sec-must-not-exist.txt"
        calls = [
            {
                "id": "sec-read",
                "tool": "read_file",
                "params": {"path": str(self.workspace / "company-a/report.txt")},
                "outcome": "allow",
            },
            {
                "id": "sec-write-denied",
                "tool": "write_file",
                "params": {"path": str(forbidden), "content": "must not execute"},
                "outcome": "deny",
            },
        ]
        try:
            self._run_native(
                calls,
                "Use the installed intent-fixture Skill for the SIQ controlled-task check.",
                skills=("intent-fixture",),
            )
            cross = {
                "id": "sec-cross-task",
                "tool": "read_file",
                "params": {"path": str(self.workspace / "company-a/report.txt")},
                "outcome": "deny",
            }
            self._run_native(
                [cross],
                "Try to reuse the previous controlled intent-fixture Skill context in a new Hermes task.",
                skills=("intent-fixture",),
            )
        finally:
            controller.shutdown()
            controller.server_close()
            thread.join(timeout=2)
            (Path(self.env["HERMES_HOME"]) / "config.yaml").write_bytes(self.product_config)
            shutil.rmtree(Path(self.env["HERMES_HOME"]) / "plugins/sec-bootstrap", ignore_errors=True)

        fixture.require(not controller_failures and len(subjects) == 2, "native SEC bootstrap sequence failed")
        fixture.require(not forbidden.exists(), "denied write produced a side effect")
        records = self.receipts()
        decisions = {row.get("tool_call_id"): row for row in records if row.get("record_type") == "decision"}
        for call in calls:
            row = decisions[call["id"]]
            fixture.require(row["action"] == call["outcome"], call["id"] + ": wrong action")
            attribution = row["skill_attribution"]
            fixture.require(
                attribution["status"] == "verified"
                and attribution["evidence_level"] == "controlled_task"
                and attribution["context_id"] == self.sec["context_id"],
                call["id"] + ": trusted Skill attribution missing",
            )
            fixture.require(
                attribution["call_binding"] == self._call_binding(row, call["params"]), "call binding mismatch"
            )
        cross_row = decisions["sec-cross-task"]
        fixture.require(cross_row["action"] == "deny", "cross-task SEC reuse was allowed")
        cross_attribution = cross_row.get("skill_attribution")
        fixture.require(
            cross_attribution is None or cross_attribution.get("status") != "verified",
            "cross-task reuse retained verified attribution",
        )
        fixture.require(
            cross_row["reason_code"] == "skill_attribution_mismatch",
            "cross-task rejection layer changed: " + str(cross_row.get("reason_code")),
        )
        fixture.require(
            self.broad_rejection == "skill_context_grant_changed", "other installed Skill borrowed authority"
        )
        fixture.require(
            (Path(self.env["HERMES_HOME"]) / "config.yaml").read_bytes() == self.product_config,
            "fixture plugin config not restored",
        )
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        fixture.require(verified["verified"], "receipt chain failed verification")
        return {
            "schema_version": "personal-r01-sec-hermes-native/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True,
            "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "native_cli_sha256": hashlib.sha256(self.args.hermes_cli.read_bytes()).hexdigest(),
            "native_entrypoint": "public hermes chat --oneshot with normal Agent loop, plugin hooks, and file tools",
            "native_identity_source": "; ".join(
                (
                    "test-only pre_llm observer reports Hermes-generated session/task",
                    "product APIs enroll and issue SEC",
                )
            ),
            "checks": [
                "two_skills_installed_for_same_agent",
                "other_skill_cannot_borrow_runtime_identity",
                "admin_api_issues_task_bound_sec",
                "native_prompt_contains_installed_skill",
                "native_allowed_read_executes",
                "native_write_denied_before_side_effect",
                "verified_attribution_on_allow_and_deny",
                "receipt_call_binding_recomputed",
                "new_native_task_cannot_copy_sec",
                "receipt_chain_verified",
                "test_observer_removed_and_product_config_restored",
            ],
            "receipt_count": len(records),
            "verified_decision_count": 2,
            "cross_task_verified": False,
            "other_skill_issue_error": self.broad_rejection,
            "limitations": [
                "local deterministic synthetic model; no external provider or paid model",
                "pre_llm observer is a test-only synchronization helper and carries no SIQ credential or authority",
                "controlled_task proves admin-bound task attribution, not causal attribution for every prompt fragment",
                "same-UID compromise and OS sandbox isolation remain outside the SEC threat boundary",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.installer_managed_profile = True
    args.remove_installed_skill = False
    args.legacy_binary = None
    with tempfile.TemporaryDirectory(prefix="siq-r01-sec-native-") as tmp:
        harness = Harness(Path(tmp), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.native_sec()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
