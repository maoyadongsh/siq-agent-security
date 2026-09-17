#!/usr/bin/env python3
"""Exercise the public OpenClaw CLI through the product managed bridge.

Uses the managed adapter install API, an issued runtime identity credential and
explicit raw-task-content grants against the real OpenClaw plugin hook path in
an isolated profile. Revocation fail-closed behaviour is verified in the same
session. Browser approval is verified separately.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "openclaw_fixture", ROOT / "scripts/validate-intent-v2-openclaw.py"
)
native = importlib.util.module_from_spec(loader)
loader.loader.exec_module(native)
fixture = native.fixture
require = fixture.require


class Harness(native.fixture.Harness):
    platform = "openclaw"
    read_tool = "read"
    write_tool = "write"

    def __init__(self, root, args):
        super().__init__(root, args)
        self.home = root / "home"
        self.home.mkdir(mode=0o700, exist_ok=True)
        # The daemon discovers OpenClaw's single config root from HOME; the
        # plugin resolves its state dir from OPENCLAW_STATE_DIR. Pinning both
        # to the same directory is what makes the managed install land where
        # the real plugin reads it.
        self.env["HOME"] = str(self.home)
        self.oc = self.home / ".openclaw"
        self.oc.mkdir()
        self.env.update(
            {
                "OPENCLAW_STATE_DIR": str(self.oc),
                "OPENCLAW_CONFIG_PATH": str(self.oc / "openclaw.json"),
            }
        )

    def build(self):
        # The inherited fixture build() compiles HEAD and ignores --binary.
        # This leg must execute the caller-selected accepted candidate exactly.
        selected = self.args.binary.resolve(strict=True)
        digest = hashlib.sha256(selected.read_bytes()).hexdigest()
        shutil.copy2(selected, self.binary)
        require(hashlib.sha256(self.binary.read_bytes()).hexdigest() == digest,
                "selected candidate changed during copy")

    def setup_authority(self):
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
            "---\nname: intent-fixture\ndescription: Read a synthetic report.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\nRead the fixture report.\n"
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
            tools=[self.read_tool, self.write_tool],
            filesystem={"read_only": [str(self.workspace)], "read_write": []},
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

        before = self.snapshot(self.oc)
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
        require(self.snapshot(self.oc) == before, "preview mutated host state")
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
            configured.get("runtimeIdentityId") == self.issued["identity"]["identity_id"],
            "installed identity missing",
        )
        require(
            configured.get("runtimeIdentityId") == self.issued["identity"]["identity_id"]
            and configured.get("agentId") == self.agent
            and configured.get("tokenPath") == self.issued["credential_path"]
            and configured.get("endpoint") == self.endpoint
            and configured.get("enforcementMode") == "block",
            "installed managed bridge mismatch",
        )
        plugin = self.oc / "plugins/siq-agent-security"
        for name in ("index.ts", "package.json", "openclaw.plugin.json"):
            installed = plugin / name
            require(installed.is_file(), "managed install missing asset " + name)
            require(
                installed.read_bytes() == (ROOT / "adapters/runtime/openclaw-agentshield" / name).read_bytes(),
                "installed asset differs from adapter source: " + name,
            )
        ocjson = json.loads((self.oc / "openclaw.json").read_text())
        require(
            str(plugin) in ocjson["plugins"]["load"]["paths"]
            and ocjson["plugins"]["entries"]["siq-agent-security"]["enabled"] is True,
            "installer did not register the plugin",
        )
        # The installed configuration must be valid without a repair step.
        require(
            "installPolicy" not in ocjson.get("security", {}),
            "installer injected an unsupported native configuration key",
        )
        catalog = self.api("/v1/adapter/instances?platform=openclaw")
        diagnosis = next(row["diagnosis"] for row in catalog["instances"] if row["instance_id"] == self.instance_id)
        require(diagnosis["runtime_state"] == "unverified", "installation claimed runtime verified")
        require(
            any(c["code"] == "instance_authority" and c["status"] == "pass" for c in diagnosis["checks"]),
            "managed authority diagnosis missing",
        )
        self.api(
            "/v1/raw-task-content/activation",
            {
                "schema_version": "local-raw-task-content-activate/v1",
                "actor_id": "automated-fixture-operator",
                "retention_seconds": 3600,
                "budget_bytes": 16 << 20,
            },
            expected=201,
        )
        self.raw_grant = None
        self.install_evidence = {
            "method": "managed_v3_preview_apply_with_public_openclaw_cli",
            "changed_file_count": len(plan["changes"]),
            "runtime_state": diagnosis["runtime_state"],
        }

    def snapshot(self, directory):
        return {
            str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*"))
            if p.is_file()
        }

    def run_cli(self):
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
        result = subprocess.run(
            command,
            cwd=self.workspace,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            if self.model_failures:
                raise RuntimeError(
                    "model exchange failed: " + repr(self.model_failures) + " requests=" + repr(self.model_requests_seen)
                )
            categories = [line[:220] for line in result.stderr.splitlines() if line.strip()]
            detail = repr(categories[-8:]).replace(str(self.root), "<fixture>")
            for value in (self.admin, self.issued["credential"]["token"] if "credential" in self.issued else ""):
                if value:
                    detail = detail.replace(value, "<redacted>")
            detail = re.sub(r"[a-fA-F0-9]{32,}", "<digest-or-token>", detail)
            raise RuntimeError(f"native CLI exit {result.returncode}: " + detail)
        payload = json.loads(result.stdout)
        require(
            any(p.get("text") == "fixture-conversation-complete" for p in payload.get("payloads", [])),
            "native CLI did not finish: payload_count=" + str(len(payload.get("payloads", [])))
            + " text_prefixes=" + repr([str(p.get("text", ""))[:100] for p in payload.get("payloads", [])])
            + " model_requests=" + str(len(self.model_requests_seen))
            + " model_failures=" + repr(self.model_failures[:2]),
        )

    def session_key(self):
        # OpenClaw 2026.5.x wrote agents/<id>/sessions/sessions.json.
        # Homebrew 2026.9.4 persists the same routing key in the agent sqlite.
        json_store = self.oc / "agents" / fixture.AGENT / "sessions/sessions.json"
        if json_store.is_file():
            entries = json.loads(json_store.read_text())
            require(bool(entries), "expected at least one native session")
            key, entry = next(iter(entries.items()))
            require(bool(entry.get("sessionId")), "native session ID missing")
            return key
        db = self.oc / "agents" / fixture.AGENT / "agent/openclaw-agent.sqlite"
        require(db.is_file(), "native session store missing")
        con = sqlite3.connect(str(db), timeout=5)
        try:
            rows = list(
                con.execute(
                    "SELECT session_key, current_session_id FROM session_nodes "
                    "WHERE session_key IS NOT NULL AND TRIM(session_key) != ''"
                )
            )
        finally:
            con.close()
        require(bool(rows), "expected at least one native session")
        preferred = "agent:" + fixture.AGENT + ":main"
        chosen = next((row for row in rows if row[0] == preferred), rows[0])
        require(bool(chosen[1]), "native session ID missing")
        return chosen[0]

    def assert_call(self, records, call_id, outcome):
        own = [row for row in records if row.get("tool_call_id") == call_id]
        decisions = [row for row in own if row.get("record_type") == "decision"]
        require(len(decisions) == 1, call_id + ": decision missing or duplicated")
        row = decisions[0]
        require(
            row["action"] == outcome and row["authority_status"] == "valid",
            call_id + ": wrong decision " + str(row.get("reason_code")),
        )
        require(row["intent_id"].startswith("int-ri-"), "decisions not backed by runtime identity")
        require(row["agent_id"] == self.agent, "environment overrode managed agent")
        require(
            row["matched_grant_id"] == self.issued["identity"]["grant_ref"]["grant_id"],
            call_id + ": wrong grant",
        )
        require(row["session_id"] == self.session_key(), "receipt session detached from native session")
        require(len(own) == (1 if outcome == "deny" else 2), call_id + ": unexpected observations")
        if outcome == "deny":
            require(row["reason_code"] == "grant_scope_violation", "wrong rejection layer")

    def public_cli(self):
        forbidden = self.workspace / "company-a/must-not-exist.txt"
        report = self.workspace / "company-a/report.txt"
        allowed_first = {
            "id": "allowed-first",
            "tool": self.read_tool,
            "params": {"path": str(report)},
        }
        write_denied = {
            "id": "write-denied",
            "tool": self.write_tool,
            "params": {"path": str(forbidden), "content": "must not execute"},
        }
        allowed_last = {
            "id": "allowed-last",
            "tool": self.read_tool,
            "params": {"path": str(report)},
        }
        raw_end = "expiry" if self.args.raw_expiry_seconds else "revoke"
        allowed_after_raw_end = {
            "id": "allowed-after-raw-" + raw_end,
            "tool": self.read_tool,
            "params": {"path": str(report)},
        }
        # Request sequence: warmup; deny probe; (raw grant created here)
        # allowed capture probe; completion; then revoke or naturally expire
        # ONLY the raw-content grant and make an allowed native call with zero
        # new raw captures;
        # finally revoke runtime identity and require every tool to fail closed.
        steps = [None, [write_denied], [allowed_first], None,
                 [allowed_after_raw_end], None,
                 [write_denied, allowed_first, allowed_last], None]
        requests, failures = [], []
        self.model_failures = failures
        self.model_requests_seen = requests
        harness = self
        self_harness = self

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
                base = {
                    "id": f"fixture-completion-{index}",
                    "created": int(time.time()),
                    "model": "siq-fixture",
                    "object": "chat.completion",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                }
                if stream:
                    if message.get("tool_calls"):
                        message["tool_calls"][0]["index"] = 0
                    chunks = []
                    for delta, reason in ((message, None), ({}, finish)):
                        chunks.append(
                            "data: "
                            + json.dumps(
                                {
                                    **base,
                                    "object": "chat.completion.chunk",
                                    "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
                                }
                            )
                            + "\n\n"
                        )
                    self.respond(("".join(chunks) + "data: [DONE]\n\n").encode(), "text/event-stream")
                    return
                self.respond({**base, "choices": [{"index": 0, "message": message, "finish_reason": finish}]})

            def do_POST(self):
                try:
                    require(self.path == "/v1/chat/completions", "unexpected model route")
                    size = int(self.headers.get("Content-Length", "0"))
                    require(0 < size < 2_000_000, "model request size invalid")
                    body = json.loads(self.rfile.read(size))
                    index = len(requests)
                    require(index < len(steps), "unexpected model retry")
                    # OpenClaw replays the full transcript: role=tool messages
                    # include every result issued so far, so compare against
                    # the cumulative issued set and pair with the newest tail.
                    results = [m for m in body["messages"] if m["role"] == "tool"]
                    issued = steps[index - 1] if index and isinstance(steps[index - 1], list) else []
                    cumulative = sum(len(s) for s in steps[:index] if isinstance(s, list))
                    require(
                        len(results) == cumulative,
                        f"native transcript mismatch: step={index} results={len(results)} issued={cumulative}",
                    )
                    revoked = harness.revoked
                    # Real-host behavior: openclaw 2026.5.12 strips
                    # non-alphanumerics from model-issued tool-call ids and
                    # appends an 8-hex disambiguator when the same id repeats
                    # within one session (this smoke deliberately re-issues the
                    # same ids in the revoked run).
                    for call, result in zip(issued, results[len(results) - len(issued):], strict=True):
                        plain = re.sub(r"[^a-zA-Z0-9]", "", call["id"])
                        replayed = result["tool_call_id"]
                        suffixed = replayed.startswith(plain) and re.fullmatch(r"[0-9a-f]{8}", replayed[len(plain):])
                        require(replayed in (call["id"], plain) or suffixed,
                                "unexpected native tool ID mapping result=" + repr(replayed) + " call=" + repr(call["id"]))
                        content = str(result.get("content", ""))
                        if call["id"].startswith("allowed") and not revoked:
                            require(
                                "fixture-visible-company-a" in content,
                                "allowed read missing; got " + repr(content[:300]),
                            )
                        else:
                            require("fixture-visible-" not in content, "denied content reached model")
                            require("siq-agent-security" in content,
                                    "SIQ rejection missing: " + repr(content[:300]))
                    requests.append({"tool_results": len(results), "stream": bool(body.get("stream"))})
                    if index == 2 and harness.raw_grant is None:
                        bindings = harness.api("/v1/intent-bindings")["items"]
                        require(len(bindings) == 1, "native session binding unavailable for raw grant")
                        harness.raw_binding = bindings[0]
                        harness.raw_grant = harness.api(
                            "/v1/raw-task-content/grants",
                            {
                                "schema_version": "local-raw-task-content-grant-create/v1",
                                "task_id": harness.raw_binding["task_id"],
                                "kinds": ["parameters", "output"],
                                "actor_id": "automated-fixture-operator",
                                "duration_seconds": harness.args.raw_expiry_seconds or 3600,
                                "retention_seconds": 3600,
                                "max_plaintext_bytes": 65536,
                            },
                            expected=201,
                        )
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
                                    "function": {
                                        "name": item["tool"],
                                        "arguments": json.dumps(item["params"]),
                                    },
                                }
                                for item in call
                            ],
                        }
                        finish = "tool_calls"
                    self.completion(index, message, finish, bool(body.get("stream")))
                except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc)[:300])
                    try:
                        rows = self_harness.receipts()
                        print(
                            "--- receipts at failure --- "
                            + json.dumps(
                                [
                                    {
                                        "type": row.get("record_type"),
                                        "tool": row.get("tool"),
                                        "call": row.get("tool_call_id"),
                                        "action": row.get("action"),
                                        "session": row.get("session_id"),
                                    }
                                    for row in rows
                                ]
                            ),
                            file=sys.stderr,
                        )
                    except Exception as inner:  # noqa: BLE001
                        print("receipt debug failed: " + repr(inner), file=sys.stderr)
                    self.send_error(400, "fixture assertion failed")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
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
                        "model": {"primary": "siqfixture/siq-fixture", "fallbacks": []},
                        "workspace": str(self.workspace),
                        "skipBootstrap": True,
                    },
                    "list": [
                        {"id": fixture.AGENT, "default": True, "workspace": str(self.workspace)}
                    ],
                },
                "tools": {"allow": [self.read_tool, self.write_tool], "fs": {"workspaceOnly": True}},
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
        require(
            "siq-agent-security"
            in json.loads(config_path.read_text())["plugins"]["load"]["paths"][0],
            "augmentation dropped installer plugin registration",
        )
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
        self.revoked = False
        try:
            self.run_cli()
            key = self.session_key()
            require(not self.receipts(), "warmup unexpectedly called a tool")
            require(
                self.api("/v1/intents")["items"] == [],
                "manual intent created before native enrollment",
            )
            self.run_cli()
            require(self.session_key() == key, "native continuation changed session")
            records = self.receipts()
            require(len(records) == 3, "unexpected receipt count: " + str(len(records)))
            self.assert_call(records, "write-denied", "deny")
            self.assert_call(records, "allowed-first", "allow")
            self.session_key()
            contracts = self.api("/v1/intents")["items"]
            require(len(contracts) == 1, "manual or duplicate intent was created")
            self.native_intent = contracts[0]
            require(self.native_intent["authority"]["issuer"] == "local-runtime-identity", "wrong issuer")
            require(
                all(record["session_id"] == key for record in records),
                "receipts do not match native session",
            )
            require(not forbidden.exists(), "forbidden write executed")
            self.raw_evidence()
            raw_before = self.api(
                "/v1/raw-task-content/records/search",
                {"schema_version": "local-raw-task-content-record-list/v1",
                 "task_id": self.raw_binding["task_id"]},
            )["items"]
            if self.args.raw_expiry_seconds:
                expires_at = datetime.fromisoformat(self.raw_grant["expires_at"].replace("Z", "+00:00"))
                deadline = time.monotonic() + self.args.raw_expiry_seconds + 20
                while datetime.now(UTC) <= expires_at:
                    require(time.monotonic() < deadline, "raw Grant did not reach real wall-clock expiry")
                    time.sleep(min(1.0, max(0.1, (expires_at - datetime.now(UTC)).total_seconds())))
                require(datetime.now(UTC) > expires_at, "raw Grant has not naturally expired")
                expired = self.api(
                    "/v1/raw-task-content/capture-permits",
                    {
                        "schema_version": "local-raw-task-content-capture-permit-create/v1",
                        "platform": self.platform,
                        "agent_id": self.agent,
                        "session_id": key,
                        "task_id": self.raw_binding["task_id"],
                        "grant_id": self.raw_grant["grant_id"],
                        "expected_grant_signature": self.raw_grant["signature"],
                        "kind": "parameters",
                        "ttl_seconds": 10,
                    },
                    token=Path(self.issued["credential_path"]).read_text().strip(), expected=410,
                )
                require(expired.get("reason_code") == "raw_task_content_authority_expired",
                        "expired raw Grant did not fail closed")
            else:
                self.api(
                    "/v1/raw-task-content/grants/" + self.raw_grant["grant_id"] + "/revoke",
                    {"schema_version": "local-raw-task-content-revoke/v1",
                     "expected_grant_signature": self.raw_grant["signature"],
                     "actor_id": "automated-fixture-operator"},
                )
            self.run_cli()
            require(self.session_key() == key, "raw-grant end changed native session")
            after_raw_end = self.receipts()
            self.assert_call(after_raw_end, allowed_after_raw_end["id"], "allow")
            raw_after = self.api(
                "/v1/raw-task-content/records/search",
                {"schema_version": "local-raw-task-content-record-list/v1",
                 "task_id": self.raw_binding["task_id"]},
            )["items"]
            require(
                len(raw_after) == len(raw_before) == 2
                and {item["record_id"] for item in raw_after}
                == {item["record_id"] for item in raw_before},
                "native call after raw Grant end created a new raw capture",
            )
            signed_count = len(after_raw_end)
            self.api(
                "/v1/runtime-identities/" + self.issued["identity"]["identity_id"] + "/revoke",
                {"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "automated-fixture-operator"},
            )
            self.revoked = True
            self.run_cli()
            require(
                len(self.receipts()) == signed_count,
                "revoked credential produced authorized receipts",
            )
            require(not failures and len(requests) == len(steps), "incomplete model exchange: " + repr(failures))
            require(not forbidden.exists(), "revoked write executed")
            raw_records = self.api(
                "/v1/raw-task-content/records/search",
                {
                    "schema_version": "local-raw-task-content-record-list/v1",
                    "task_id": self.raw_binding["task_id"],
                },
            )["items"]
            require(len(raw_records) == 2, "inactive raw Grant run captured additional raw content")
            self.stop()
            verified = json.loads(self.command([str(self.binary), "verify"]))
            require(verified["verified"], "receipt chain invalid")
            return {
                "schema_version": "personal-openclaw-managed-native-smoke/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "native_cli_sha256": hashlib.sha256(
                    (self.args.openclaw_root / "openclaw.mjs").read_bytes()
                ).hexdigest(),
                "openclaw_version": json.loads((self.args.openclaw_root / "package.json").read_text())["version"],
                "native_entrypoint": "public openclaw agent --local; real plugin hook lifecycle",
                "session_id_source": "native before_tool_call; plugin enrolls automatically; not injected",
                "checks": [
                    "openclaw_catalog_reports_native_unavailable",
                    "managed_preview_does_not_mutate_host",
                    "managed_install_uses_issued_identity",
                    "installed_assets_match_adapter_source",
                    "installer_registers_runtime_without_unsupported_install_policy",
                    "native_cli_uses_installed_config_without_security_key_workaround",
                    "diagnosis_keeps_runtime_unverified",
                    "native_cli_started",
                    "native_session_automatically_enrolled",
                    "instance_credential_used_without_manual_intent",
                    "environment_cannot_override_managed_agent",
                    "write_denied_before_execution",
                    "allowed_read",
                    "native_raw_parameters_captured_after_explicit_task_grant",
                    "native_raw_output_captured_after_explicit_task_grant",
                    "native_raw_grant_" + ("naturally_expired" if self.args.raw_expiry_seconds else "revoked") + "_while_runtime_identity_still_valid",
                    *(["expired_raw_grant_permit_rejected_410"] if self.args.raw_expiry_seconds else []),
                    "allowed_native_call_after_raw_grant_" + raw_end + "_adds_no_capture",
                    "receipt_chain_verified",
                    "revoked_identity_blocks_new_native_calls",
                ],
                "receipt_count": signed_count,
                "installation": self.install_evidence,
                "installer_configuration_compatible": True,
                "model_requests": list(requests),
                "raw_content": {
                    "record_count": 2,
                    "authority_ended_by": "natural_expiry" if self.args.raw_expiry_seconds else "revoke",
                    "kinds": ["output", "parameters"],
                    "task_binding_source": "server-signed native session binding",
                    # The grant identifier is not needed to assess this public
                    # report. Keep only a digest, never the full local handle.
                    "grant_id_sha256": hashlib.sha256(self.raw_grant["grant_id"].encode()).hexdigest(),
                    "plaintext_verified_via_admin_read": True,
                },
                "limitations": [
                    "isolated profile configured through product installer; browser workflow is separate evidence",
                    "synthetic model and operator; no real-user approval, Skill attribution or OS isolation proof",
                    "native startup may produce host history/cache; network isolation is not claimed",
                    "harness augments installer-written openclaw.json with synthetic model/tools config",
                ],
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def raw_evidence(self):
        raw_records = self.api(
            "/v1/raw-task-content/records/search",
            {
                "schema_version": "local-raw-task-content-record-list/v1",
                "task_id": self.raw_binding["task_id"],
            },
        )["items"]
        require(
            len(raw_records) == 2 and {record["kind"] for record in raw_records} == {"parameters", "output"},
            "native parameter/output ciphertext set incomplete: " + json.dumps(raw_records, sort_keys=True),
        )
        raw_content = {}
        for record in raw_records:
            content = self.api(
                f"/v1/raw-task-content/records/{record['record_id']}/read",
                {"schema_version": "local-raw-task-content-record-read/v1", "task_id": self.raw_binding["task_id"]},
            )
            require(content["contains_plaintext"] is True, "native raw read missing explicit marker")
            raw_content[record["kind"]] = content["fields"]
        parameter_fields = {field["path"]: field["value"] for field in raw_content["parameters"]}
        require(
            parameter_fields.get("/tool/name") == self.read_tool
            and parameter_fields.get("/tool/arguments/path")
            == json.dumps(str(self.workspace / "company-a/report.txt")),
            "native parameter plaintext does not match executed call",
        )
        require(
            any("fixture-visible-company-a" in field["value"] for field in raw_content["output"]),
            "native output plaintext does not match actual result",
        )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--raw-expiry-seconds", type=int, default=0,
                        help="use real wall-clock Grant expiry instead of revoke; minimum 60 seconds")
    args = parser.parse_args()
    require(args.raw_expiry_seconds == 0 or 60 <= args.raw_expiry_seconds <= 600,
            "--raw-expiry-seconds must be zero or between 60 and 600")
    args.openclaw_root, args.node, args.binary = (
        args.openclaw_root.resolve(),
        args.node.resolve(),
        args.binary.resolve(),
    )
    require(args.node.is_file(), "Node executable not found")
    require((args.openclaw_root / "openclaw.mjs").is_file(), "OpenClaw entrypoint not found")
    # The fixture's first policy probe is a real native write. Refuse an
    # incompatible host before creating that probe: a plugin import failure
    # would otherwise let the write run outside SIQ's hook boundary.
    host_package = json.loads((args.openclaw_root / "package.json").read_text())
    entry = host_package.get("exports", {}).get("./plugin-sdk/plugin-entry", {})
    entry_file = entry.get("default") if isinstance(entry, dict) else None
    require(isinstance(entry_file, str) and entry_file.startswith("./dist/plugin-sdk/")
            and (args.openclaw_root / entry_file).is_file(),
            "OpenClaw host lacks the SIQ plugin SDK entrypoint; native write probe refused")
    with tempfile.TemporaryDirectory(prefix="siq-openclaw-managed-native-") as temporary:
        root = Path(temporary)
        harness = Harness(root, args)
        harness.build()
        try:
            harness.start()
            harness.setup_authority()
            report = harness.public_cli()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x") as output:
        output.write(json.dumps(report, indent=2) + "\n")
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
        print(f"openclaw managed smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
