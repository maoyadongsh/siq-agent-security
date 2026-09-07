#!/usr/bin/env python3
"""Run installed OpenClaw CLI conversations against a synthetic loopback model."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "openclaw_fixture", ROOT / "scripts/validate-intent-v2-openclaw.py"
)
native = importlib.util.module_from_spec(loader)
loader.loader.exec_module(native)
fixture = native.fixture
require = fixture.require


class ConversationHarness(native.OpenClawHarness):
    def run_cli(self, session_id=None):
        command = [
            str(self.args.node),
            "--import",
            str(ROOT / "scripts/openclaw-fixture-guard.mjs"),
            str(self.args.openclaw_root / "openclaw.mjs"),
            "agent",
            "--local",
            "--agent",
            fixture.AGENT,
            "--message",
            "Run the next local synthetic fixture turn.",
            "--thinking",
            "off",
            "--timeout",
            "45",
            "--json",
        ]
        if session_id:
            command.extend(["--session-id", session_id])
        result = subprocess.run(
            command,
            cwd=self.workspace,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode:
            if self.model_failures:
                raise RuntimeError(
                    "model exchange failed: " + repr(self.model_failures)
                )
            # Only synthetic fixture config is passed to this process. Keep
            # raw logs private; emit known failure categories for diagnostics.
            categories = [
                line[:220]
                for line in result.stderr.splitlines()
                if any(
                    word in line.lower()
                    for word in (
                        "error",
                        "invalid",
                        "fail",
                        "unknown",
                        "reject",
                        "missing",
                    )
                )
            ]
            detail = repr(categories[-8:]).replace(str(self.root), "<fixture>")
            for value in (self.admin, (self.state / "token").read_text().strip()):
                if value:
                    detail = detail.replace(value, "<redacted>")
            detail = re.sub(r"[a-fA-F0-9]{32,}", "<digest-or-token>", detail)
            raise RuntimeError(f"native CLI exit {result.returncode}: " + detail)
        payload = json.loads(result.stdout)
        require(
            any(
                p.get("text") == "fixture-conversation-complete"
                for p in payload.get("payloads", [])
            ),
            "native CLI did not finish",
        )
        return payload.get("meta", {})

    def session(self):
        store = self.root / "openclaw/agents" / fixture.AGENT / "sessions/sessions.json"
        entries = json.loads(store.read_text())
        require(len(entries) == 1, "expected one native session")
        key, entry = next(iter(entries.items()))
        require(bool(entry.get("sessionId")), "native session ID missing")
        return key, entry["sessionId"]

    def run(self):
        self.build()
        self.start()
        self.setup_authority()
        calls = [
            self.read("allowed"),
            self.read("foreign-company", "company-b"),
            self.read("prefix-collision", "company-a-evil"),
            {
                "id": "write-denied",
                "tool": "write",
                "params": {
                    "path": str(self.workspace / "company-a/must-not-exist.txt"),
                    "content": "synthetic forbidden write",
                },
            },
            self.read("allowed-after-denials"),
        ]
        # First let the native runtime establish its own persistent session.
        # Two more CLI invocations then resume that session and use real tools.
        bound_steps = [None] + calls[:4] + [None] + calls[4:] + [None]
        missing_call = self.read("missing-binding")
        steps = bound_steps + [missing_call, None]
        requests, failures, history_id_mappings = [], [], []
        self.model_failures = failures

        class Model(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                try:
                    require(
                        self.path == "/v1/chat/completions", "unexpected model route"
                    )
                    size = int(self.headers.get("Content-Length", "0"))
                    require(0 < size < 2_000_000, "model request size invalid")
                    body = json.loads(self.rfile.read(size))
                    index = len(requests)
                    require(index < len(steps), "unexpected model retry")
                    results = [m for m in body["messages"] if m["role"] == "tool"]
                    active_steps = (
                        steps[:index]
                        if index < len(bound_steps)
                        else steps[len(bound_steps) : index]
                    )
                    active_calls = calls if index < len(bound_steps) else [missing_call]
                    completed = sum(step is not None for step in active_steps)
                    require(
                        len(results) == completed, "native transcript lost tool results"
                    )
                    for call, result in zip(
                        active_calls[:completed], results, strict=True
                    ):
                        result_id = result["tool_call_id"]
                        require(
                            result_id
                            in (call["id"], re.sub(r"[^a-zA-Z0-9]", "", call["id"])),
                            "unexpected native tool ID mapping",
                        )
                        paired = [
                            tc
                            for msg in body["messages"]
                            for tc in msg.get("tool_calls", [])
                            if tc["id"] == result_id
                        ]
                        require(
                            len(paired) == 1
                            and paired[0]["function"]["name"] == call["tool"]
                            and json.loads(paired[0]["function"]["arguments"])
                            == call["params"],
                            "normalized result detached from original tool and parameters",
                        )
                        mapping = {"response_id": call["id"], "history_id": result_id}
                        if (
                            result_id != call["id"]
                            and mapping not in history_id_mappings
                        ):
                            history_id_mappings.append(mapping)
                        content = str(result["content"])
                        if call["id"].startswith("allowed"):
                            require(
                                "fixture-visible-company-a" in content,
                                "allowed read missing",
                            )
                        else:
                            require(
                                "fixture-visible-" not in content,
                                "denied content reached model",
                            )
                            require(
                                "siq-agent-security" in content, "SIQ rejection missing"
                            )
                    requests.append(
                        {
                            "stream": bool(body.get("stream")),
                            "tool_results": len(results),
                        }
                    )
                    call = steps[index]
                    message = {
                        "role": "assistant",
                        "content": "fixture-conversation-complete",
                    }
                    if call is not None:
                        message = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": call["tool"],
                                        "arguments": json.dumps(call["params"]),
                                    },
                                }
                            ],
                        }
                    finish = "tool_calls" if call else "stop"
                    base = {
                        "id": f"fixture-completion-{index}",
                        "created": int(time.time()),
                        "model": "siq-fixture",
                        "object": "chat.completion",
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "total_tokens": 120,
                        },
                    }
                    content_type = "application/json"
                    if body.get("stream"):
                        if call:
                            message["tool_calls"][0]["index"] = 0
                        chunks = []
                        for delta, reason in ((message, None), ({}, finish)):
                            chunk = {
                                **base,
                                "object": "chat.completion.chunk",
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": delta,
                                        "finish_reason": reason,
                                    }
                                ],
                            }
                            chunks.append("data: " + json.dumps(chunk) + "\n\n")
                        raw = ("".join(chunks) + "data: [DONE]\n\n").encode()
                        content_type = "text/event-stream"
                    else:
                        raw = json.dumps(
                            {
                                **base,
                                "choices": [
                                    {
                                        "index": 0,
                                        "message": message,
                                        "finish_reason": finish,
                                    }
                                ],
                            }
                        ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc))
                    self.send_error(400, "fixture assertion failed")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config_path = self.root / "openclaw/openclaw.json"
        config = json.loads(config_path.read_text())
        config.update(
            {
                "logging": {
                    "file": str(self.root / "openclaw.log"),
                    "consoleLevel": "silent",
                },
                "agents": {
                    "defaults": {
                        "model": {"primary": "siqfixture/siq-fixture", "fallbacks": []},
                        "workspace": str(self.workspace),
                        "skipBootstrap": True,
                    },
                    "list": [
                        {
                            "id": fixture.AGENT,
                            "default": True,
                            "workspace": str(self.workspace),
                        }
                    ],
                },
                "tools": {"allow": ["read", "write"], "fs": {"workspaceOnly": True}},
                "models": {
                    "mode": "replace",
                    "providers": {
                        "siqfixture": {
                            "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                            "apiKey": "synthetic-fixture-key",
                            "api": "openai-completions",
                            "models": [
                                {
                                    "id": "siq-fixture",
                                    "name": "SIQ Fixture",
                                    "contextWindow": 131072,
                                    "maxTokens": 512,
                                    "reasoning": False,
                                    "input": ["text"],
                                }
                            ],
                        }
                    },
                },
            }
        )
        config_path.write_text(json.dumps(config))
        # The full CLI imports built-in public surfaces (e.g. speech-core)
        # even when no channel is configured. The explicit plugin allowlist
        # still restricts activation to SIQ; don't hide installed core files.
        self.env.pop("OPENCLAW_DISABLE_BUNDLED_PLUGINS", None)
        self.env.update(
            {
                "OPENCLAW_HOME": str(self.root / "native-home"),
                "PI_CODING_AGENT_DIR": str(self.root / "pi"),
                "NODE_DISABLE_COMPILE_CACHE": "1",
                "OPENCLAW_NO_RESPAWN": "1",
                "SIQ_FIXTURE_ENDPOINTS": json.dumps(
                    [
                        f"127.0.0.1:{server.server_port}",
                        f"127.0.0.1:{urlsplit(self.endpoint).port}",
                    ]
                ),
            }
        )
        try:
            self.run_cli()
            key, session_id = self.session()
            require(not self.receipts(), "warmup unexpectedly called a tool")
            self.api(
                "/v1/intent-bindings",
                {
                    "platform": "openclaw",
                    "session_id": key,
                    "agent_id": fixture.AGENT,
                    "intent_id": "int-native-fixture",
                },
                expected=201,
            )
            for _ in range(2):
                self.run_cli()
                require(
                    self.session() == (key, session_id),
                    "native continuation changed session",
                )
            records = self.receipts()
            parent = ""
            for seq, call in enumerate(calls, start=1):
                decision = self.assert_call(
                    records,
                    call["id"],
                    "allow" if call["id"].startswith("allowed") else "deny",
                )
                require(
                    decision["session_id"] == key,
                    "native routing key detached from receipt",
                )
                require(
                    decision["task_seq"] == seq, "sequence reset across CLI processes"
                )
                require(
                    decision.get("parent_action_id", "") == parent,
                    "action chain changed",
                )
                if decision["action"] == "allow":
                    parent = decision["action_id"]
            # This selector is supplied by the operator fixture; OpenClaw
            # itself derives and persists a distinct native routing key.
            unbound_id = str(uuid.uuid4())
            self.run_cli(session_id=unbound_id)
            records = self.receipts()
            unbound = self.assert_call(records, "missing-binding", "deny", bound=False)
            require(
                unbound["session_id"] != key, "new session reused bound routing key"
            )
            require(
                not failures and len(requests) == len(steps),
                "incomplete model exchange: " + repr(failures),
            )
            require(
                not (self.workspace / "company-a/must-not-exist.txt").exists(),
                "denied write executed",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.stop()
        require(
            json.loads(self.command([str(self.binary), "verify"]))["verified"],
            "offline verify failed",
        )
        sources = [
            self.args.openclaw_root / p
            for p in (
                "openclaw.mjs",
                "package.json",
                "dist/entry.js",
                "dist/plugins/loader.js",
                "node_modules/@earendil-works/pi-ai/dist/providers/openai-completions.js",
            )
        ]
        for prefix in (
            "agent-command-",
            "pi-embedded-",
            "native-hook-relay-",
            "pi-tools.before-tool-call-",
            "tool-call-id-",
            "model-fallback-",
        ):
            sources.extend((self.args.openclaw_root / "dist").glob(prefix + "*.js"))
        return {
            "schema": "intent-v2-openclaw-conversation-validation/v1",
            "passed": True,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "siq_commit": self.command(["git", "rev-parse", "HEAD"], cwd=ROOT).strip(),
            "siq_dirty": bool(
                self.command(["git", "status", "--porcelain"], cwd=ROOT).strip()
            ),
            "openclaw_version": json.loads(
                (self.args.openclaw_root / "package.json").read_text()
            )["version"],
            "node_version": self.command([str(self.args.node), "--version"]).strip(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "guard_sha256": hashlib.sha256(
                (ROOT / "scripts/openclaw-fixture-guard.mjs").read_bytes()
            ).hexdigest(),
            "adapter_sha256": hashlib.sha256(
                (ROOT / "adapters/runtime/openclaw-agentshield/index.ts").read_bytes()
            ).hexdigest(),
            "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            "native_session_key": key,
            "native_session_id": session_id,
            "unbound_session_selector": unbound_id,
            "unbound_native_session_key": unbound["session_id"],
            "runtime_source_sha256": {
                str(p.relative_to(self.args.openclaw_root)): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in sources
            },
            "shared_harness_sha256": {
                name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
                for name in (
                    "validate-intent-v2-hermes.py",
                    "validate-intent-v2-openclaw.py",
                )
            },
            "cli_turns": 4,
            "completion_requests": len(requests),
            "streaming_requests": sum(r["stream"] for r in requests),
            "tool_calls": len(calls) + 1,
            "receipt_count": len(records),
            "history_id_mappings": history_id_mappings,
            "checks": self.checks
            + [
                "native_cli_session_creation",
                "native_stream_tool_dispatch",
                "native_post_hook_observation",
                "scope_and_write_denied",
                "cross_process_transcript_and_action_chain",
                "explicit_new_native_session_has_no_binding",
                "offline_receipt_chain_verified",
            ],
            "limitations": [
                "synthetic model and operator; no human approval proof",
                "embedded CLI path, not a live gateway or channel delivery",
                "no hold approval, session reset or CodeBuddy journey",
                "no OS isolation claim",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.openclaw_root = args.openclaw_root.resolve()
    args.node = args.node.absolute()
    with tempfile.TemporaryDirectory(prefix="siq-openclaw-conversation-") as tmp:
        harness = ConversationHarness(Path(tmp), args)
        try:
            report = harness.run()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": True,
                "completion_requests": report["completion_requests"],
                "receipt_count": report["receipt_count"],
            }
        )
    )


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
        print(
            f"OpenClaw conversation failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
