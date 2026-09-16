#!/usr/bin/env python3
"""Taskbook B05: real-host fail-closed behaviour while the SEC service is down.

Runs the managed OpenClaw adapter journey against the public ``openclaw agent
--local`` entrypoint and a local deterministic model fixture, then stops the
SEC daemon mid-journey. While the service is unreachable every necessary tool
call must be denied (block path; managed installs also stay deny under an
audit_only enforcement-mode override) and the host must show ZERO independent
side effects: a dedicated marker file is never written and an isolated
loopback receiver counts no further requests. After restarting the daemon on
the same port the offline fail-closed pending lines are promoted onto the
signed receipt chain and normal authorized calls resume.

Side-effect channels are deliberately concrete:
  * file writes use dedicated marker paths never used elsewhere,
  * network egress uses curl against an in-process loopback receiver that the
    fixture guard never allowlists, so a hit can only come from a real
    subprocess spawned by an executed host tool. The receiver proves it counts
    real HTTP traffic with a harness self-test before any tool runs; every
    later assertion is that the hit count never moves again.

Product contract exercised on the way: exec-class tools are never
intent-compatible (a shell command always carries an unknown effect), so the
up-leg exec egress is a REAL-HOST deny with ``runtime_effect_unknown`` while
the service is up -- which also proves the up-leg deny is a service decision,
not a transport failure, and still produces zero egress.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections import Counter
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "openclaw_managed_fixture", ROOT / "scripts/personal-experience/openclaw-managed-native-smoke.py"
)
managed = importlib.util.module_from_spec(loader)
loader.loader.exec_module(managed)
require = managed.require
fixture = managed.fixture

EGRESS_BODY = "b05-egress-receiver-ok"
UP_MARKER = "b05-up-marker.txt"
DOWN_MARKER = "b05-down-marker.txt"
AUDIT_MARKER = "b05-audit-override-marker.txt"
DOWN_CALL_IDS = ("b05-down-write", "b05-down-read", "b05-down-egress", "b05-audit-write")


def id_variants(call_id):
    """OpenClaw strips non-alphanumerics from tool-call ids and may append a
    short disambiguator; normalize both sides before comparing."""
    plain = re.sub(r"[^a-zA-Z0-9]", "", call_id)

    def matches(value):
        return value == call_id or value == plain or (
            value.startswith(plain) and len(value) <= len(plain) + 8
        )

    return matches


class Harness(managed.Harness):
    def setup_authority(self):
        # Same managed journey as the shipped smoke, but the fixture grant is
        # read/write over the workspace and includes the exec tool: the write
        # is the allow-path positive control, and exec documents the product
        # contract that shell tools are never intent-compatible (the up-leg
        # deny must arrive as a service decision, not a transport failure).
        require(not (self.oc / "siq-agent-security.json").exists(), "fixture preinstalled managed adapter")
        require(not (self.oc / "plugins").exists(), "fixture preinstalled plugin assets")
        require(not (self.oc / "openclaw.json").exists(), "fixture preinstalled openclaw config")
        catalog = self.api("/v1/adapter/instances?platform=openclaw")
        require(catalog["native_available"] is False, "openclaw native availability over-claimed")
        target = next(row for row in catalog["instances"] if row["active"])
        self.instance_id = target["instance_id"]
        self.agent = "hri-" + self.instance_id[3:]
        skill = self.root / "fixture-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: intent-fixture\ndescription: Fixture tools for B05 side-effect controls.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool} exec\n---\nRun the fixture steps.\n"
        )
        adm = self.api("/v1/admit", {"path": str(skill)})["admission"]
        require(adm["verdict"] != "quarantine", "benign fixture quarantined")
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
            tools=[self.read_tool, self.write_tool, "exec"],
            filesystem={"read_only": [], "read_write": [str(self.workspace)]},
        )
        for index, overlap in enumerate(result["grant"]["overlap_conflicts"]):
            if overlap["resolution"] == "unresolved":
                action("resolve-overlap", index=index)
        challenge = action("challenge")["challenge"]
        action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        require(result["grant"]["status"] == "approved", "grant approval did not transition")
        action("deploy")
        self.issued = self.api(
            "/v1/runtime-identities",
            {
                "schema_version": "local-runtime-identity-create/v1",
                "instance_id": self.instance_id,
                "grant_id": result["grant"]["grant_id"],
                "expected_grant_revision": result["state_revision"],
                "actor_id": "automated-fixture-operator",
                "session_ttl_seconds": 28800,
            },
            expected=201,
        )
        require(self.issued["identity"]["runtime_state"] == "unverified", "issuance claimed protection")
        plan = self.api(
            "/v1/adapter/preview",
            {
                "platform": "openclaw",
                "action": "install",
                "instance_id": self.instance_id,
                "runtime_identity_id": self.issued["identity"]["identity_id"],
            },
        )
        require(plan["schema_version"] == "local-adapter-plan/v3", "managed plan missing")
        self.api(
            "/v1/adapter/install",
            {
                "platform": "openclaw",
                "instance_id": self.instance_id,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
                "runtime_identity_id": plan["runtime_identity_id"],
                "actor_id": "automated-fixture-operator",
            },
        )
        configured = json.loads((self.oc / "siq-agent-security.json").read_text())
        require(
            configured.get("runtimeIdentityId") == self.issued["identity"]["identity_id"]
            and configured.get("agentId") == self.agent
            and configured.get("tokenPath") == self.issued["credential_path"]
            and configured.get("endpoint") == self.endpoint
            and configured.get("enforcementMode") == "block",
            "installed managed bridge mismatch",
        )
        self.managed_config_path = self.oc / "siq-agent-security.json"

    def start_fixed(self, port):
        """Restart the daemon on the exact port the plugin config pins."""
        self.endpoint = f"http://127.0.0.1:{port}"
        self.env["SIQ_AGENT_SECURITY_ENDPOINT"] = self.endpoint
        self.log = tempfile.TemporaryFile(mode="w+t")  # noqa: SIM115 -- closed in stop
        self.proc = subprocess.Popen(
            [str(self.binary), "serve", "--port", str(port), "--mode", "block"],
            cwd=self.workspace,
            env=self.env,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            require(self.proc.poll() is None, "restarted daemon exited before readiness")
            self.log.seek(0)
            found = re.search(r"admin pairing code \(single use, 5 min\): (\S+)", self.log.read())
            if found:
                try:
                    pair = self.api("/v1/pair", {"code": found[1]}, token="")
                    self.admin = pair["session"]
                    return
                except Exception:  # noqa: BLE001 -- listener not accepting yet
                    self.restart_pair_attempts = getattr(self, "restart_pair_attempts", 0) + 1
            time.sleep(0.05)
        raise RuntimeError("restarted daemon readiness timeout")

    def pending_lines(self):
        # appendPending writes under the daemon state dir (the tokenPath's
        # managed grandparent), i.e. <root>/state/pending -- NOT ~/.openclaw.
        path = self.state / "pending/decisions.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def service_down_leg(self):
        report_path = self.workspace / "company-a/report.txt"
        up_marker_path = self.workspace / UP_MARKER
        down_marker_path = self.workspace / DOWN_MARKER
        audit_marker_path = self.workspace / AUDIT_MARKER
        requests, failures = [], []
        self.model_failures, self.model_requests_seen = failures, requests
        harness = self

        # Isolated loopback receiver. It is intentionally NOT in
        # SIQ_FIXTURE_ENDPOINTS: the fixture guard only filters in-process
        # node sockets, and this receiver must be reachable solely by real
        # curl subprocesses spawned by an executed host tool.
        class Receiver(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def hit(self):
                harness.hits.append(self.path)
                raw = EGRESS_BODY.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self.hit()

            def do_POST(self):
                self.hit()

        receiver = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        receiver_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
        receiver_thread.start()
        self.receiver_port = receiver.server_port
        self.hits = []
        egress = f"curl -s -X POST http://127.0.0.1:{self.receiver_port}/b05-egress"

        # The receiver must prove it counts real HTTP traffic before any tool
        # runs, otherwise a flat hit count later would be indistinguishable
        # from a broken listener.
        with urlopen(
            f"http://127.0.0.1:{self.receiver_port}/b05-receiver-selftest", timeout=5
        ) as probe:
            require(probe.read().decode() == EGRESS_BODY, "loopback receiver self-test returned the wrong body")
        require(len(self.hits) == 1, "loopback receiver did not count its self-test hit")

        calls = {
            "warmup": None,
            "up-control": [
                {"id": "b05-up-write", "tool": self.write_tool,
                 "params": {"path": str(up_marker_path), "content": "b05-positive-control-side-effect"}},
                {"id": "b05-up-egress", "tool": "exec", "params": {"command": egress}},
            ],
            "down-block": [
                {"id": "b05-down-write", "tool": self.write_tool,
                 "params": {"path": str(down_marker_path), "content": "must never reach disk"}},
                {"id": "b05-down-read", "tool": self.read_tool, "params": {"path": str(report_path)}},
                {"id": "b05-down-egress", "tool": "exec", "params": {"command": egress}},
            ],
            "down-audit-override": [
                {"id": "b05-audit-write", "tool": self.write_tool,
                 "params": {"path": str(audit_marker_path), "content": "audit_only must not weaken managed"}},
            ],
            "recovery": [
                {"id": "b05-recover-read", "tool": self.read_tool, "params": {"path": str(report_path)}},
            ],
        }
        steps = [
            calls["warmup"],
            calls["up-control"],
            None,
            calls["down-block"],
            None,
            calls["down-audit-override"],
            None,
            calls["recovery"],
            None,
        ]
        positive_controls = {
            "b05-up-write": lambda content: (
                "b05-positive-control-side-effect" in content or "wrote" in content.lower()
            ),
            "b05-recover-read": lambda content: "fixture-visible-company-a" in content,
        }
        # Up-leg exec is denied by an actual service decision (shell always
        # carries an unknown effect); the down-leg calls are denied fail-closed
        # without any service round-trip. Both must show the deny reason.
        deny_reasons = {"b05-up-egress": "runtime_effect_unknown"}

        class Model(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, value, content_type="application/json"):
                raw = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def completion(self, index, message, finish, stream):
                base = {"id": f"b05-fixture-{index}", "created": 0, "model": "siq-b05-fixture"}
                if stream:
                    for tool_index, tool_call in enumerate(message.get("tool_calls", [])):
                        tool_call["index"] = tool_index
                    chunks = [
                        {**base, "object": "chat.completion.chunk",
                         "choices": [{"index": 0, "delta": message, "finish_reason": None}]},
                        {**base, "object": "chat.completion.chunk",
                         "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                    ]
                    raw = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
                    self.respond(raw.encode(), "text/event-stream")
                    return
                self.respond(
                    {**base, "object": "chat.completion",
                     "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
                )

            def do_POST(self):
                try:
                    require(self.path == "/v1/chat/completions", "unexpected model route")
                    size = int(self.headers.get("Content-Length", "0"))
                    require(0 < size < 2_000_000, "model request size invalid")
                    body = json.loads(self.rfile.read(size))
                    index = len(requests)
                    require(index < len(steps), "unexpected model request")
                    results = [
                        m for m in body.get("messages", []) if m.get("role") == "tool"
                    ]
                    cumulative = sum(len(s) for s in steps[:index] if isinstance(s, list))
                    require(
                        len(results) == cumulative,
                        f"native transcript mismatch: step={index} results={len(results)} issued={cumulative}",
                    )
                    issued = steps[index - 1] if index and isinstance(steps[index - 1], list) else []
                    for call, result in zip(issued, results[len(results) - len(issued):], strict=True):
                        content = str(result.get("content", ""))
                        if call["id"] in positive_controls:
                            require(
                                positive_controls[call["id"]](content),
                                call["id"] + " positive control did not execute: " + repr(content[:300]),
                            )
                            require(
                                "siq-agent-security" not in content,
                                call["id"] + " positive control was unexpectedly rejected",
                            )
                        else:
                            require(
                                "siq-agent-security" in content,
                                call["id"] + " was not rejected while the service was down",
                            )
                            require(
                                "fixture-visible-" not in content and EGRESS_BODY not in content,
                                call["id"] + " leaked protected content",
                            )
                            if call["id"] in deny_reasons:
                                require(
                                    deny_reasons[call["id"]] in content,
                                    call["id"] + " deny did not carry the expected contract reason: "
                                    + repr(content[:300]),
                                )
                    requests.append({"index": index, "tool_results": len(results)})
                    call = steps[index]
                    message = {"role": "assistant", "content": "fixture-conversation-complete"}
                    finish = "stop"
                    if call is not None:
                        message = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": item["id"],
                                    "type": "function",
                                    "function": {"name": item["tool"], "arguments": json.dumps(item["params"])},
                                }
                                for item in call
                            ],
                        }
                        finish = "tool_calls"
                    self.completion(index, message, finish, bool(body.get("stream")))
                except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc)[:300])
                    self.send_error(400, "fixture assertion failed")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        pending = []
        try:
            config_path = self.oc / "openclaw.json"
            config = json.loads(config_path.read_text())
            plugins = config["plugins"]
            plugins.setdefault("allow", [])
            if "siq-agent-security" not in plugins["allow"]:
                plugins["allow"].append("siq-agent-security")
            config.update(
                {
                    "logging": {"file": str(self.root / "openclaw.log"), "consoleLevel": "silent"},
                    "agents": {
                        "defaults": {
                            "model": {"primary": "siqfixture/siq-b05-fixture", "fallbacks": []},
                            "workspace": str(self.workspace),
                            "skipBootstrap": True,
                        },
                        "list": [{"id": fixture.AGENT, "default": True, "workspace": str(self.workspace)}],
                    },
                    "tools": {"allow": [self.read_tool, self.write_tool, "exec"], "fs": {"workspaceOnly": True}},
                    "models": {
                        "mode": "replace",
                        "providers": {
                            "siqfixture": {
                                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                                "apiKey": "synthetic-fixture-key",
                                "api": "openai-completions",
                                "models": [
                                    {
                                        "id": "siq-b05-fixture",
                                        "name": "SIQ B05 Fixture",
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
            self.env.pop("OPENCLAW_DISABLE_BUNDLED_PLUGINS", None)
            self.env.update(
                {
                    "OPENCLAW_HOME": str(self.root / "native-home"),
                    "PI_CODING_AGENT_DIR": str(self.root / "pi"),
                    "NODE_DISABLE_COMPILE_CACHE": "1",
                    "OPENCLAW_NO_RESPAWN": "1",
                    "SIQ_FIXTURE_ENDPOINTS": json.dumps(
                        [f"127.0.0.1:{server.server_port}", f"127.0.0.1:{urlsplit(self.endpoint).port}"]
                    ),
                }
            )

            # Turn 1: warmup (no tools). Turn 2: the allow-path positive
            # control (marker write) plus the exec contract denial, with the
            # service UP for both.
            self.run_cli()
            require(len(self.hits) == 1, "receiver moved before any tool ran")
            self.run_cli()
            require(
                up_marker_path.is_file() and up_marker_path.read_text() == "b05-positive-control-side-effect",
                "positive-control marker write did not execute",
            )
            require(
                len(self.hits) == 1,
                "UP-LEG VIOLATION: exec denied by decision still produced network egress",
            )
            up_receipts = self.receipts()
            up_egress = id_variants("b05-up-egress")
            up_egress_receipts = [r for r in up_receipts if up_egress(str(r.get("tool_call_id", "")))]
            require(
                len(up_egress_receipts) == 1 and up_egress_receipts[0].get("action") == "deny"
                and "runtime_effect_unknown" in str(up_egress_receipts[0].get("reason", "")),
                "up-leg exec was not denied with the documented shell contract: " + repr(
                    [(r.get("tool_call_id"), r.get("action"), r.get("reason")) for r in up_egress_receipts]
                ),
            )
            daemon_port = urlsplit(self.endpoint).port

            # Service DOWN: stop the daemon; every necessary call must be
            # denied with zero independent side effects.
            self.stop()
            require(self.pending_lines() == [], "fail-closed pending lines appeared while the service was up")
            self.run_cli()
            require(
                not down_marker_path.exists(),
                "DOWN-LEG VIOLATION: denied write executed (marker file exists)",
            )
            require(len(self.hits) == 1, "DOWN-LEG VIOLATION: denied exec still produced network egress")
            pending = self.pending_lines()
            down_pending = [p for p in pending if p.get("schema") == "pending_decision/v1"]
            require(
                len(down_pending) == 3
                and Counter(p.get("tool") for p in down_pending)
                == Counter([self.write_tool, self.read_tool, "exec"]),
                "expected exactly one pending line per down-leg tool",
            )
            for line in down_pending:
                require(line["signed"] is False, "pending line claimed to be signed")
                require(line["outcome"] == "deny" and line["enforcement_mode"] == "block", "wrong pending outcome")
                # The plugin's offline marker is the "decision service
                # unavailable (...)" reason prefix; the siq-agent-security
                # marker lives in the host-facing blockReason instead.
                require(
                    line["reason"].startswith("decision service unavailable ("),
                    "pending reason missing fail-closed marker: " + repr(line["reason"])[:200],
                )
            require({p["platform"] for p in down_pending} == {"openclaw"}, "pending lines from unexpected platform")

            # audit_only override leg: a managed install must keep failing
            # closed even if the local enforcement-mode field is downgraded.
            override = json.loads(self.managed_config_path.read_text())
            require(override.get("enforcementMode") == "block", "managed mode unexpectedly changed")
            override["enforcementMode"] = "audit_only"
            self.managed_config_path.write_text(json.dumps(override))
            try:
                self.run_cli()
            finally:
                restore = json.loads(self.managed_config_path.read_text())
                restore["enforcementMode"] = "block"
                self.managed_config_path.write_text(json.dumps(restore))
            require(
                not audit_marker_path.exists(),
                "audit_only override let a managed-install write execute while the service was down",
            )
            pending = self.pending_lines()
            require(
                len(pending) == len(down_pending) + 1
                and pending[:-1] == down_pending
                and pending[-1].get("tool") == self.write_tool
                and pending[-1].get("signed") is False
                and pending[-1].get("outcome") == "deny"
                and pending[-1].get("enforcement_mode") == "block",
                "audit_only override did not append exactly one fail-closed write record",
            )
            require(len(self.hits) == 1, "audit_only override produced network egress while the service was down")

            # Recovery: restart on the SAME pinned port and re-pair as admin;
            # startup must promote the offline fail-closed lines onto the
            # signed receipt chain.
            self.start_fixed(daemon_port)
            self.run_cli()
            require(
                report_path.is_file() and len(self.hits) == 1,
                "recovery leg changed side-effect counters",
            )
            records = self.receipts()
            promoted = [r for r in records if str(r.get("reason", "")).startswith("promoted pending fail-closed")]
            require(
                len(promoted) == len(pending),
                "restarted daemon did not promote each offline fail-closed line exactly once",
            )
            require(all(r.get("action") == "deny" for r in promoted), "promoted fail-closed receipts must stay deny")
            for call_id in DOWN_CALL_IDS:
                matches = id_variants(call_id)
                require(
                    not any(matches(str(r.get("tool_call_id", ""))) for r in records),
                    call_id + ": unreachable service produced an authorized receipt",
                )
            recovered = id_variants("b05-recover-read")
            require(
                any(recovered(str(r.get("tool_call_id", ""))) and r.get("action") == "allow" for r in records),
                "recovery read was not allow-receipted",
            )
            cursor = self.state / "pending/promoted.lines"
            require(cursor.is_file(), "promotion cursor missing")
            require(
                int(cursor.read_text().strip()) == len(pending),
                "promotion cursor does not match pending line count",
            )
            require(not failures and len(requests) == len(steps), "incomplete model exchange: " + repr(failures))

            receipt_count = len(records)
            self.stop()
            verified = json.loads(self.command([str(self.binary), "verify"]))
            require(verified["verified"], "receipt chain verification failed after promotion")
            return {
                "schema_version": "personal-b05-service-down-side-effects/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "native_cli_sha256": hashlib.sha256(
                    (self.args.openclaw_root / "openclaw.mjs").read_bytes()
                ).hexdigest(),
                "openclaw_version": json.loads((self.args.openclaw_root / "package.json").read_text())["version"],
                "native_entrypoint": "public openclaw agent --local; real plugin hook lifecycle",
                "checks": [
                    "managed_install_with_read_write_exec_grant",
                    "loopback_receiver_selftest_proves_hit_counting",
                    "positive_control_marker_write_executed_with_service_up",
                    "up_leg_exec_denied_runtime_effect_unknown_contract",
                    "up_leg_denied_exec_produced_zero_egress",
                    "service_down_denies_file_write_before_execution",
                    "service_down_denies_read_without_content_leak",
                    "service_down_zero_loopback_egress_from_denied_exec",
                    "fail_closed_pending_lines_signed_false_recorded",
                    "managed_audit_only_override_still_fails_closed",
                    "same_port_restart_recovers_pairing",
                    "pending_lines_promoted_onto_signed_receipt_chain",
                    "unreachable_service_produced_no_authorized_receipts",
                    "recovered_service_allows_authorized_read",
                    "promotion_cursor_matches_pending_lines",
                    "receipt_chain_verified_after_promotion",
                ],
                "receipt_count": receipt_count,
                "pending_line_count": len(pending),
                "promoted_receipt_count": len(promoted),
                "loopback_receiver_hits": len(self.hits),
                "limitations": [
                    "local deterministic model and automated fixture operator; no external or paid model",
                    ("exec-class tools are never intent-compatible (shell always carries an unknown effect), "
                    "so no authorized-egress allow path exists through the real host; the loopback receiver "
                    "therefore proves the zero-egress property on the denial paths, backed by a self-test"),
                    "exec egress uses curl; host-level firewall isolation is not claimed",
                    "same-UID compromise and OS sandbox isolation remain outside the threat boundary",
                ],
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            receiver.shutdown()
            receiver.server_close()
            receiver_thread.join(timeout=5)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.openclaw_root, args.node, args.binary = (
        args.openclaw_root.resolve(), args.node.resolve(), args.binary.resolve()
    )
    require(args.node.is_file(), "Node executable not found")
    require((args.openclaw_root / "openclaw.mjs").is_file(), "OpenClaw entrypoint not found")
    with tempfile.TemporaryDirectory(prefix="siq-b05-service-down-") as temporary:
        harness = Harness(Path(temporary), args)
        harness.build()
        try:
            harness.start()
            harness.setup_authority()
            report = harness.service_down_leg()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x") as output:
        output.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Subprocess errors may contain native transcripts, credentials and
        # private fixture paths. Persist only the failure category.
        frames = traceback.extract_tb(exc.__traceback__)
        frame = frames[-2] if len(frames) > 1 and frames[-1].name in ("check", "require") else frames[-1]
        print(json.dumps({"passed": False, "error_type": type(exc).__name__,
                          "failure_location": {"file": Path(frame.filename).name,
                                               "line": frame.lineno, "function": frame.name}}), file=sys.stderr)
        sys.exit(1)
