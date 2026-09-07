#!/usr/bin/env python3
"""Verify native idle rollover preserves SIQ binding, action ancestry and taint.

Uses real elapsed time and OpenClaw's native reset policy. No edited session
timestamps, fake clocks, gateway, real credentials or model-provider requests.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "conversation_fixture", ROOT / "scripts/validate-intent-v2-openclaw-conversation.py"
)
conversation = importlib.util.module_from_spec(loader)
loader.loader.exec_module(conversation)
require = conversation.require


class ResetHarness(conversation.ConversationHarness):
    def main_entry(self, key):
        store = (
            self.root
            / "openclaw/agents"
            / conversation.fixture.AGENT
            / "sessions/sessions.json"
        )
        return json.loads(store.read_text())[key]

    def run(self):
        baseline = super().run()
        key = baseline["native_session_key"]
        previous_id = baseline["native_session_id"]
        self.start()
        pii_file = self.workspace / "company-a/pii-fixture.txt"
        marker = "synthetic-person@example.test"
        pii_file.write_text(marker + "\n")
        calls = [
            {"id": "seedpii", "tool": "read", "params": {"path": str(pii_file)}},
            self.read("resetdenied", "company-b"),
            {"id": "resetallowed", "tool": "read", "params": {"path": str(pii_file)}},
        ]
        steps = [calls[0], None, calls[1], calls[2], None]
        requests, failures = [], []
        reset_history = {}
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
                    require(0 < size < 2_000_000, "invalid model request size")
                    body = json.loads(self.rfile.read(size))
                    index = len(requests)
                    require(index < len(steps), "unexpected model retry")
                    results = [m for m in body["messages"] if m["role"] == "tool"]
                    if index == 2:
                        reset_history["tool_results_retained"] = len(results)
                        reset_history["pii_marker_retained"] = marker in json.dumps(
                            body["messages"]
                        )
                        current = self_harness.main_entry(key)
                        reset_history["uuid_rotated_before_model_request"] = (
                            current["sessionId"] != previous_id
                        )
                        reset_history["session_file_unchanged"] = current.get(
                            "sessionFile"
                        ) == seed_entry.get("sessionFile")
                    retained = reset_history.get("tool_results_retained", 0)
                    expected_counts = [5, 6, retained, retained + 1, retained + 2]
                    require(
                        len(results) == expected_counts[index],
                        f"native transcript mismatch at request {index}: got {len(results)}, expected {expected_counts[index]}",
                    )
                    if index == 1:
                        require(
                            results[-1]["tool_call_id"] == "seedpii"
                            and marker in str(results[-1]["content"]),
                            "native PII seed read failed",
                        )
                    if index >= 3:
                        after_reset = results[retained:]
                        require(
                            after_reset[0]["tool_call_id"] == "resetdenied",
                            "reset result ID changed",
                        )
                        require(
                            "siq-agent-security" in str(after_reset[0]["content"])
                            and "fixture-visible-company-b"
                            not in str(after_reset[0]["content"]),
                            "reset lost resource denial",
                        )
                    if index == 4:
                        require(
                            results[-1]["tool_call_id"] == "resetallowed"
                            and marker in str(results[-1]["content"]),
                            "bound read did not recover after reset",
                        )
                    requests.append(
                        {
                            "tool_results": len(results),
                            "stream": bool(body.get("stream")),
                        }
                    )
                    call = steps[index]
                    message = {
                        "role": "assistant",
                        "content": "fixture-conversation-complete",
                    }
                    if call:
                        message = {
                            "role": "assistant",
                            "content": None,
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
                    require(
                        body.get("stream") is True,
                        "native protocol unexpectedly stopped streaming",
                    )
                    chunks = []
                    for delta, finish in (
                        (message, None),
                        ({}, "tool_calls" if call else "stop"),
                    ):
                        chunk = {
                            "id": f"reset-fixture-{index}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": "siq-fixture",
                            "choices": [
                                {"index": 0, "delta": delta, "finish_reason": finish}
                            ],
                            "usage": {
                                "prompt_tokens": 100,
                                "completion_tokens": 20,
                                "total_tokens": 120,
                            },
                        }
                        chunks.append("data: " + json.dumps(chunk) + "\n\n")
                    raw = ("".join(chunks) + "data: [DONE]\n\n").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc))
                    self.send_error(400, "reset fixture assertion failed")

        self_harness = self
        server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config_path = self.root / "openclaw/openclaw.json"
        config = json.loads(config_path.read_text())
        config["models"]["providers"]["siqfixture"]["baseUrl"] = (
            f"http://127.0.0.1:{server.server_port}/v1"
        )
        config_path.write_text(json.dumps(config))
        self.env["SIQ_FIXTURE_ENDPOINTS"] = json.dumps(
            [
                f"127.0.0.1:{server.server_port}",
                f"127.0.0.1:{urlsplit(self.endpoint).port}",
            ]
        )
        try:
            self.run_cli()
            entry = self.main_entry(key)
            seed_entry = entry
            require(
                entry["sessionId"] == previous_id, "seed did not resume native session"
            )
            seed = self.assert_call(self.receipts(), "seedpii", "allow")
            seed_observations = [
                r
                for r in self.receipts()
                if r.get("tool_call_id") == "seedpii"
                and r.get("record_type") == "observation"
            ]
            require(
                len(seed_observations) == 1
                and "pii" in seed_observations[0]["taint_labels"],
                "seed did not contaminate SIQ session",
            )
            config["session"] = {"reset": {"mode": "idle", "idleMinutes": 1}}
            config_path.write_text(json.dumps(config))
            last_interaction = entry["lastInteractionAt"] / 1000
            deadline = last_interaction + 61
            wait_started = time.monotonic()
            require(
                0 < deadline - time.time() < 65, "native idle deadline out of range"
            )
            print(
                "Native session is live; waiting for its configured one-minute idle expiry.",
                flush=True,
            )
            while time.time() < deadline:
                # Bound each sleep so parent orchestration can keep reporting.
                time.sleep(min(1, deadline - time.time()))
            waited = time.monotonic() - wait_started
            self.run_cli()
            reset_entry = self.main_entry(key)
            require(
                reset_entry["sessionId"] != previous_id,
                "native idle policy did not rotate UUID",
            )
            require(not failures and len(requests) == 5, "incomplete reset exchange")
            records = self.receipts()
            denied = self.assert_call(records, "resetdenied", "deny")
            allowed = self.assert_call(records, "resetallowed", "allow")
            require(
                denied["reason_code"] == "intent_resource_not_allowed",
                "reset denial came from wrong layer",
            )
            for seq, decision in (
                (seed["task_seq"] + 1, denied),
                (seed["task_seq"] + 2, allowed),
            ):
                require(
                    decision["session_id"] == key and decision["task_seq"] == seq,
                    "reset cleared bound sequence",
                )
                require(
                    decision["parent_action_id"] == seed["action_id"],
                    "reset cleared successful action ancestry",
                )
                require(
                    "pii" in decision["taint_labels"],
                    "reset laundered taint before the next read",
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.stop()
        require(
            json.loads(self.command([str(self.binary), "verify"]))["verified"],
            "offline reset chain verification failed",
        )
        reset_sources = list((self.args.openclaw_root / "dist").glob("reset-*.js"))
        transcript_cleared = (
            reset_history["tool_results_retained"] == 0
            and not reset_history["pii_marker_retained"]
        )
        return {
            "schema": "intent-v2-openclaw-idle-reset-validation/v1",
            "passed": transcript_cleared,
            "siq_invariants_passed": True,
            "native_transcript_cleared": transcript_cleared,
            "native_reset_observations": reset_history,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "baseline_conversation": baseline,
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "conversation_harness_sha256": hashlib.sha256(
                (
                    ROOT / "scripts/validate-intent-v2-openclaw-conversation.py"
                ).read_bytes()
            ).hexdigest(),
            "reset_source_sha256": {
                str(p.relative_to(self.args.openclaw_root)): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in reset_sources
            },
            "native_session_key": key,
            "previous_native_uuid": previous_id,
            "new_native_uuid": reset_entry["sessionId"],
            "idle_minutes": 1,
            "last_interaction_unix_seconds": last_interaction,
            "waited_seconds": waited,
            "reset_stage_completion_requests": len(requests),
            "receipt_count": len(records),
            "task_sequences": [
                seed["task_seq"],
                denied["task_seq"],
                allowed["task_seq"],
            ],
            "checks": [
                "real_elapsed_idle_rollover",
                "fixed_binding_survives_same_routing_key",
                "scope_denial_survives_rollover",
                "action_sequence_and_parent_survive_rollover",
                "pii_taint_survives_before_new_read",
                "offline_chain_verified",
            ],
            "limitations": [
                "native UUID rollover does not by itself prove transcript erasure; inspect native_transcript_cleared",
                "idle reset only; no gateway manual reset or channel journey",
                "same routing key intentionally remains the same SIQ authority/session",
                "synthetic model and operator; no human approval or OS isolation proof",
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
    with tempfile.TemporaryDirectory(prefix="siq-openclaw-reset-") as tmp:
        harness = ResetHarness(Path(tmp), args)
        try:
            report = harness.run()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "siq_invariants_passed": report["siq_invariants_passed"],
                "native_reset_observations": report["native_reset_observations"],
                "waited_seconds": report["waited_seconds"],
                "receipt_count": report["receipt_count"],
            }
        )
    )
    if not report["passed"]:
        sys.exit(1)


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
            f"OpenClaw reset validation failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
