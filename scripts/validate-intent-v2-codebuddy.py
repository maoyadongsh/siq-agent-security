#!/usr/bin/env python3
"""Run the installed Tencent CLI against synthetic files and loopback-only models.

Uses native PreToolUse/PostToolUse command hooks and the actual SIQ Go daemon.
The Node IO guard is a test precaution, not an OS sandbox. No user config, real
provider credential or paid model is used. Reports contain summaries/hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "native_base", REPO / "scripts/validate-intent-v2-hermes.py"
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
require = base.require
SESSION = base.SESSION


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Model:
    def __init__(self):
        self.calls = []
        self.results = {}
        self.request_count = 0
        self.history = []
        self.errors = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    require(0 < length < 4 * 1024 * 1024, "model body limit")
                    request = json.loads(self.rfile.read(length))
                    require(self.path == "/chat/completions", "unexpected model route")
                    require(request.get("stream") is True, "expected model stream")
                    owner.request_count += 1
                    require(owner.request_count <= 60, "model request budget")
                    owner.history.append(
                        [
                            item["tool_call_id"]
                            for item in request.get("messages", [])
                            if item.get("role") == "tool"
                        ]
                    )
                    for item in request.get("messages", []):
                        if item.get("role") == "tool":
                            owner.results[item["tool_call_id"]] = item.get("content")
                    delta, finish = (
                        {"role": "assistant", "content": "fixture-complete"},
                        "stop",
                    )
                    if owner.calls:
                        call = owner.calls.pop(0)
                        offered = {
                            t["function"]["name"] for t in request.get("tools", [])
                        }
                        require(call["tool"] in offered, "native tool not offered")
                        delta = {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": call["tool"],
                                        "arguments": json.dumps(call["params"]),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    common = {
                        "id": f"fixture-{owner.request_count}",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": request["model"],
                    }
                    chunks = [
                        {
                            **common,
                            "choices": [
                                {"index": 0, "delta": delta, "finish_reason": None}
                            ],
                        },
                        {
                            **common,
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": finish}
                            ],
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 3,
                                "total_tokens": 13,
                            },
                        },
                    ]
                    body = (
                        "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
                        + "data: [DONE]\n\n"
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (OSError, ValueError, KeyError, RuntimeError, TypeError) as exc:
                    owner.errors.append(type(exc).__name__ + ": " + str(exc))
                    self.send_error(500, "fixture model rejected request")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class Harness(base.Harness):
    platform = "codebuddy"
    read_tool = "Read"
    write_tool = "Write"

    def __init__(self, root, args):
        super().__init__(root, args)
        self.model = Model()
        self.native_count = 0
        self.sessions = set()
        self.session_calls = {}
        self.native_summaries = []
        self.config_dir = root / "codebuddy"
        self.config_dir.mkdir()
        for name in ("tmp", "xdg", "cache"):
            (root / name).mkdir()
        self.env.update(
            {
                "CODEBUDDY_CONFIG_DIR": str(self.config_dir),
                "CODEBUDDY_CODE_DEBUG_LOGS_DIR": str(root / "logs"),
                "CODEBUDDY_CREDENTIALS_IN_MEMORY": "1",
                "CODEBUDDY_DISABLE_COMPILE_CACHE": "1",
                "DISABLE_AUTOUPDATER": "1",
                "DISABLE_TELEMETRY": "1",
                "DISABLE_GALILEO": "1",
                "CODEBUDDY_CODE_ENABLE_TELEMETRY": "0",
                "CODEBUDDY_DISABLE_AUTO_MEMORY": "1",
                "CODEBUDDY_CODE_DISABLE_AUTO_MEMORY": "1",
                "CODEBUDDY_MAX_RETRIES": "0",
                "CODEBUDDY_FIRST_TOKEN_TIMEOUT_MS": "10000",
                "CODEBUDDY_BASE_URL": f"http://127.0.0.1:{self.model.server.server_port}",
                "CODEBUDDY_API_KEY": "synthetic-fixture-key",
                "CODEBUDDY_MODEL": "fixture-model",
                "TMPDIR": str(root / "tmp"),
                "XDG_CONFIG_HOME": str(root / "xdg"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "SIQ_FIXTURE_ROOT": str(root),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "SERVER__HOST": "127.0.0.1",
            }
        )
        (self.config_dir / "settings.json").write_text(
            json.dumps({"env": {"SIQ_FIXTURE_USER_SETTING": "preserve"}})
        )

    def start(self):
        super().start()
        cfg_path = self.state / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["port"] = int(self.endpoint.rsplit(":", 1)[1])
        cfg_path.write_text(json.dumps(cfg))

    def read(self, call_id, company="company-a"):
        return {
            "id": call_id,
            "tool": self.read_tool,
            "params": {"file_path": str(self.workspace / company / "report.txt")},
        }

    def native(self, calls, session=SESSION):
        require(not self.model.calls, "unconsumed prior model calls")
        self.model.calls = list(calls)
        history_index = len(self.model.history)
        port = free_port()
        self.env.update(
            {
                "SERVER__PORT": str(port),
                "SIQ_FIXTURE_ENDPOINTS": json.dumps(
                    [
                        f"127.0.0.1:{port}",
                        f"127.0.0.1:{self.model.server.server_port}",
                        self.endpoint.removeprefix("http://"),
                    ]
                ),
            }
        )
        args = [
            str(self.args.node),
            "--import",
            str(REPO / "scripts/codebuddy-fixture-guard.mjs"),
            str(self.args.codebuddy_root / "bin/codebuddy"),
            "-p",
            "Execute the fixture plan and finish.",
            "--tools",
            "Read,Write",
            "--allowedTools",
            "Read,Write",
            "--permission-mode",
            "dontAsk",
            "--output-format",
            "json",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--resume" if session in self.sessions else "--session-id",
            session,
        ]
        proc = subprocess.run(
            args,
            cwd=self.workspace,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        require(proc.returncode == 0, "native CLI exit failure")
        require(
            not self.model.errors,
            "model protocol failure: " + "; ".join(self.model.errors),
        )
        try:
            items = json.loads(proc.stdout)
        except ValueError as exc:
            raise RuntimeError("native CLI produced no valid JSON") from exc
        result = [i for i in items if i.get("type") == "result"]
        require(
            len(result) == 1 and result[0].get("is_error") is False,
            "native result error",
        )
        require(
            result[0].get("result") == "fixture-complete",
            "assistant completion missing",
        )
        require(
            result[0].get("session_id") == session, "native session identity changed"
        )
        require(not self.model.calls, "model plan incomplete")
        first_history = self.model.history[history_index]
        expected_history = self.session_calls.get(session, [])
        require(
            set(expected_history).issubset(first_history),
            "native resume lost prior tool results",
        )
        if not expected_history:
            require(
                not first_history, "new native session inherited prior tool results"
            )
        self.session_calls.setdefault(session, []).extend(c["id"] for c in calls)
        self.sessions.add(session)
        self.native_count += 1
        self.native_summaries.append(
            {
                "session_id": session,
                "call_ids": [c["id"] for c in calls],
                "completed": True,
                "prior_tool_result_ids": first_history,
            }
        )
        outputs = []
        for call in calls:
            require(
                call["id"] in self.model.results,
                "native tool result missing: " + call["id"],
            )
            outputs.append(
                {"id": call["id"], "result": json.dumps(self.model.results[call["id"]])}
            )
        return outputs

    def run(self):
        pkg = json.loads((self.args.codebuddy_root / "package.json").read_text())
        require(
            pkg["name"] == "@tencent-ai/codebuddy-code" and pkg["version"] == "2.146.0",
            "unvalidated CodeBuddy package/version",
        )
        runtime_hash = digest(self.args.codebuddy_root / "dist/codebuddy-headless.js")
        self.build()
        self.start()
        settings = self.config_dir / "settings.json"
        original = settings.read_bytes()
        for _ in range(2):
            installed = json.loads(
                self.command([str(self.binary), "adapter", "install", "codebuddy"])
            )
            require(
                installed["paths"] == [str(settings)], "installer selected wrong config"
            )
        snapshot = Path(str(settings) + ".siq-agent-security.orig")
        require(snapshot.read_bytes() == original, "reinstall lost original config")
        status = json.loads(
            self.command([str(self.binary), "adapter", "status", "codebuddy"])
        )
        require(status["note"] == "installed", "CLI installation status missing")
        before_grant = self.native([self.read("before-grant")])[0]["result"]
        require(
            "fixture-visible-" not in before_grant
            and "siq-agent-security" in before_grant,
            "pre-grant native read not denied",
        )
        before = [r for r in self.receipts() if r.get("tool_call_id") == "before-grant"]
        require(
            len(before) == 1
            and before[0]["record_type"] == "decision"
            and before[0]["action"] == "deny",
            "pre-grant decision evidence missing",
        )
        self.checks.append(
            "cli_custom_config_install_reinstall_backup_and_native_pregrant_denial"
        )
        self.setup_authority()
        forbidden = self.workspace / "company-a" / "must-not-exist.txt"
        calls = [
            self.read("allowed"),
            self.read("foreign-company", "company-b"),
            self.read("prefix-collision", "company-a-evil"),
            {
                "id": "write-denied",
                "tool": "Write",
                "params": {
                    "file_path": str(forbidden),
                    "content": "fixture must not execute",
                },
            },
        ]
        outputs = self.native(calls)
        require(
            "fixture-visible-company-a" in outputs[0]["result"],
            "native allowed read missing",
        )
        require(not forbidden.exists(), "native denied write executed")
        for output in outputs[1:]:
            require(
                "fixture-visible-" not in output["result"]
                and "siq-agent-security" in output["result"],
                "native denial missing or content leaked",
            )
        records = self.receipts()
        self.assert_call(records, "allowed", "allow")
        for call_id in ("foreign-company", "prefix-collision", "write-denied"):
            self.assert_call(records, call_id, "deny")
        self.checks.extend(
            [
                "native_allowed_read_and_correlated_post",
                "native_resource_and_prefix_denial",
                "native_denied_write_has_no_effect",
            ]
        )
        self.native([self.read("missing-binding")], "unbound-fixture")
        self.assert_call(self.receipts(), "missing-binding", "deny", bound=False)
        self.checks.append("native_new_session_does_not_inherit_binding")
        self.stop(kill=True)
        offline = self.native([self.read("offline")])[0]["result"]
        require(
            "fail-closed" in offline and "fixture-visible-" not in offline,
            "native offline call did not block",
        )
        require(
            (self.state / "pending/decisions.jsonl").exists(), "pending denial missing"
        )
        self.start()
        recovered = self.native([self.read("after-restart")])[0]["result"]
        require("fixture-visible-company-a" in recovered, "native restart read missing")
        records = self.receipts()
        self.assert_call(records, "after-restart", "allow")
        promoted = [r for r in records if "pending" in str(r.get("matched_rule_ids"))]
        require(
            len(promoted) == 1 and promoted[0]["action"] == "deny",
            "pending promotion not exactly once",
        )
        self.checks.append("native_resume_daemon_kill_and_pending_recovery")
        self.stop()
        self.config("optional")
        self.start()
        legacy = self.native([self.read("optional-unbound")], "unbound-fixture")[0][
            "result"
        ]
        require(
            "fixture-visible-company-a" in legacy, "optional unbound native read failed"
        )
        self.assert_call(self.receipts(), "optional-unbound", "allow", bound=False)
        self.native([self.read("bound-still-denied", "company-b")])
        self.assert_call(self.receipts(), "bound-still-denied", "deny")
        self.checks.append("native_optional_unbound_and_bound_no_downgrade")
        records = self.receipts()
        bound = [
            r
            for r in records
            if r.get("record_type") == "decision" and r.get("intent_binding") == "bound"
        ]
        parent = None
        for index, current in enumerate(bound, start=1):
            require(
                current["task_seq"] == index
                and current.get("parent_action_id") == parent,
                "bound action sequence detached across native resumes",
            )
            # dev-spec § V2: denied attempts advance sequence but do not become
            # an authorized parent; allow/redact advance the parent action.
            if current["action"] in ("allow", "redact"):
                parent = current["action_id"]
        self.checks.append("bound_action_sequence_and_parent_survive_native_resume")
        self.command([str(self.binary), "adapter", "uninstall", "codebuddy"])
        status = json.loads(
            self.command([str(self.binary), "adapter", "status", "codebuddy"])
        )
        require(status["note"] == "not installed", "CLI uninstall status incorrect")
        require(
            json.loads(settings.read_text())["env"]["SIQ_FIXTURE_USER_SETTING"]
            == "preserve",
            "uninstall removed unrelated config",
        )
        require(
            snapshot.read_bytes() == original, "uninstall changed original snapshot"
        )
        control = self.native([self.read("uninstalled-control", "company-b")])[0][
            "result"
        ]
        require(
            "fixture-visible-company-b" in control,
            "unguarded native control did not execute",
        )
        require(
            len(self.receipts()) == len(records), "uninstalled native call reached SIQ"
        )
        self.checks.append(
            "cli_uninstall_preserves_settings_and_native_control_executes"
        )
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        require(verified["verified"], "offline receipt verification failed")
        require(
            digest(self.args.codebuddy_root / "dist/codebuddy-headless.js")
            == runtime_hash,
            "runtime changed",
        )
        return {
            "schema": "intent-v2-native-codebuddy-validation/v1",
            "passed": True,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "siq_commit": self.command(["git", "rev-parse", "HEAD"], cwd=REPO).strip(),
            "runtime": {
                "package": pkg["name"],
                "version": pkg["version"],
                "headless_sha256": runtime_hash,
            },
            "source_sha256": {
                p: digest(REPO / p)
                for p in [
                    "scripts/validate-intent-v2-codebuddy.py",
                    "scripts/codebuddy-fixture-guard.mjs",
                    "scripts/validate-intent-v2-hermes.py",
                    "apps/agentshield/internal/adapters/adapters.go",
                    "apps/agentshield/internal/adapterinstall/install.go",
                ]
            },
            "binary_sha256": digest(self.binary),
            "checks": self.checks,
            "native_cli_invocations": self.native_count,
            "model_requests": self.model.request_count,
            "sessions": sorted(self.sessions),
            "journeys": self.native_summaries,
            "receipt_count": len(records),
            "receipt_summaries": [
                {
                    k: r.get(k)
                    for k in (
                        "record_type",
                        "tool_call_id",
                        "session_id",
                        "action",
                        "reason_code",
                        "intent_binding",
                        "task_seq",
                        "action_id",
                        "parent_action_id",
                        "decision_receipt_id",
                        "receipt_id",
                    )
                }
                for r in records
            ],
            "offline_verified": verified["verified"],
            "limitations": [
                "synthetic operator and local deterministic model",
                "installer/native CLI E2E only in a temporary config and state directory",
                "no GUI, real human approval, hold/redact or channel proof",
                "Node IO guard is not OS isolation",
                "no overall supported claim",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codebuddy-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.codebuddy_root = args.codebuddy_root.resolve(strict=True)
    args.node = args.node.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="siq-codebuddy-native-") as directory:
        harness = Harness(Path(directory), args)
        try:
            report = harness.run()
        finally:
            harness.stop()
            harness.model.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "receipt_count": report["receipt_count"],
                "native_cli_invocations": report["native_cli_invocations"],
            }
        )
    )


if __name__ == "__main__":
    main()
