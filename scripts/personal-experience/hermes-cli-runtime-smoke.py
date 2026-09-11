#!/usr/bin/env python3
"""Exercise the public Hermes CLI and native hooks in an isolated test profile.

The extra observer plugin exposes only the host-generated session ID to the
fixture controller. SIQ decisions still run through the installed adapter and
real daemon. This is an integration spike, not a product self-check endpoint.
"""

import argparse
import hashlib
import importlib.util
import json
import secrets
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


class Harness(fixture.Harness):
    def public_cli(self):
        profile = Path(self.env["HERMES_HOME"])
        observer = profile / "plugins/siq-runtime-check-observer"
        observer.mkdir()
        (observer / "plugin.yaml").write_text(
            "name: siq-runtime-check-observer\nversion: 0.0.1\ndescription: Synthetic session observer.\n"
        )
        (observer / "__init__.py").write_text(OBSERVER)
        config = profile / "config.yaml"
        config.write_text(
            "plugins:\n  enabled: [siq-agent-security, siq-runtime-check-observer]\nterminal:\n  env: local\n"
        )
        self.command(
            [str(self.args.hermes_cli), "plugins", "enable", "siq-runtime-check-observer", "--no-allow-tool-override"]
        )
        before = hashlib.sha256(config.read_bytes()).hexdigest()
        session = ""
        nonce = secrets.token_hex(32)
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
        controller = self
        guard = threading.Lock()

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
                nonlocal session
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    fixture.require(0 < size <= 2_000_000, "request budget")
                    body = json.loads(self.rfile.read(size))
                    if self.path == "/attach":
                        fixture.require(self.headers.get("Authorization") == "Bearer " + nonce, "observer credential")
                        value = body.get("session_id")
                        fixture.require(isinstance(value, str) and 0 < len(value) <= 256, "native session missing")
                        with guard:
                            fixture.require(not session or session == value, "native session changed")
                            if not session:
                                controller.api(
                                    "/v1/intent-bindings",
                                    {
                                        "platform": "hermes",
                                        "session_id": value,
                                        "agent_id": fixture.AGENT,
                                        "intent_id": "int-native-fixture",
                                    },
                                    expected=201,
                                )
                                session = value
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
                        fixture.require(len(auxiliary) < 16, "auxiliary request budget")
                        auxiliary.append({"stream": bool(body.get("stream"))})
                        self.complete(
                            {"role": "assistant", "content": "SIQ synthetic check"}, "stop", bool(body.get("stream"))
                        )
                        return
                    fixture.require(bool(session), "model called before native session hook")
                    results = [item for item in body.get("messages", []) if item.get("role") == "tool"]
                    index = len(received)
                    fixture.require(
                        index <= len(calls) and len(results) == index,
                        f"unexpected model retry or lost history: step={index} results={len(results)}",
                    )
                    for call, result in zip(calls[:index], results, strict=True):
                        fixture.require(result["tool_call_id"] == call["id"], "tool call identity changed")
                        text = str(result.get("content", ""))
                        if call["id"].startswith("allowed"):
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
            "SIQ_FIXTURE_ATTACH": endpoint + "/attach",
            "SIQ_FIXTURE_NONCE": nonce,
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
            for call in calls:
                self.assert_call(records, call["id"], "deny" if call["id"] == "write-denied" else "allow")
            fixture.require(
                all(record["session_id"] == session for record in records), "receipts do not match native session"
            )
            self.stop()
            verified = json.loads(self.command([str(self.binary), "verify"]))
            fixture.require(verified["verified"], "receipt chain invalid")
            return {
                "schema_version": "personal-hermes-cli-runtime-smoke/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "native_cli_sha256": hashlib.sha256(self.args.hermes_cli.read_bytes()).hexdigest(),
                "native_entrypoint": "public hermes chat --oneshot; normal Agent loop and plugin lifecycle",
                "session_id_source": "native pre_llm_call; fixture observer only; not injected",
                "checks": [
                    "native_cli_started",
                    "native_generated_session_bound",
                    "allowed_read",
                    "write_denied_before_execution",
                    "allowed_after_denial",
                    "receipt_chain_verified",
                ],
                "receipt_count": len(records),
                "model_requests": received,
                "auxiliary_requests": auxiliary,
                "profile_config_unchanged": before == hashlib.sha256(config.read_bytes()).hexdigest(),
                "limitations": [
                    "isolated fixture profile and observer; not a product self-check endpoint",
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
    with tempfile.TemporaryDirectory(prefix="siq-hermes-cli-runtime-") as temporary:
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
