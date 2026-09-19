#!/usr/bin/env python3
"""Run a full SIQ Skill V1→V2 update journey through a real OpenClaw process.

The harness uses an isolated HOME/profile, the product's public management
APIs, ``openclaw agent --local``, the real plugin hook and the real file tool.
A local deterministic model fixture chooses the tool call; no external or paid
model is contacted. The administrator issues the required signed session SEC
through the public API. The journey covers: V1 install/authorize/attach, real
native read with attribution, cancel-before-confirm, confirm update V2,
re-authorize, safe removal, plus the UP01–UP10 negative/concurrent acceptance
probes that are expressible at this interface level.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
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

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "r01_sec_openclaw", REPO / "scripts/personal-experience/r01-sec-openclaw-native-smoke.py"
)
r01sec = importlib.util.module_from_spec(loader)
loader.loader.exec_module(r01sec)
managed = r01sec.managed
fixture = r01sec.fixture
require = fixture.require


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def grant_digest(grant_doc):
    """Python replica of skillcontext.GrantDigest: Go's encoding/json unmarshal
    turns every number into float64 and canon.writeFloat renders the CPython
    float repr, so the replica re-reads the document with parse_int=float."""
    refloated = json.loads(json.dumps(grant_doc), parse_int=float, parse_float=float)
    raw = json.dumps(refloated, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class Harness(r01sec.Harness):
    def setup_authority(self):
        super().setup_authority()
        self.current_install = self.skill_installation["install_id"]
        self.steps = []
        self.calls_issued = []
        self.session_override = None
        self.override_steps = []
        self.model_failures, self.model_requests_seen = [], []

    def attribution_relations(self, sec, row, grant_doc, install_view):
        """Field-by-field correlation across install record, runtime identity,
        grant document, SEC and decision receipt, anchored on the product's real
        reference fields (skillcontext store.go Issue/liveInstall and receipt
        engine.go's attribution copy). Digest domains are compared only where
        the product itself derives one field from the other."""
        attribution = row.get("skill_attribution") or {}
        sec_subject = sec.get("subject") or {}
        sec_skill = sec.get("skill") or {}
        sec_install = sec.get("install") or {}
        sec_authority = sec.get("authority") or {}
        grant_skill = grant_doc.get("skill") or {}
        plan = install_view.get("plan") or {}
        identity = next(
            (i for i in self.api("/v1/runtime-identities")["items"]
             if i["identity_id"] == self.issued["identity"]["identity_id"]),
            {},
        )
        checks = {
            "grant_id_same_everywhere": row.get("matched_grant_id") == sec_authority.get("grant_id")
                == grant_doc.get("grant_id") == plan.get("grant_id")
                == (identity.get("grant_ref") or {}).get("grant_id"),
            "install_record_live": install_view.get("schema_version") == "local-skill-install-view/v1"
                and install_view.get("status") == "installed_unverified",
            "sec_install_pin_matches_record": sec_install.get("install_id") == self.skill_installation["install_id"]
                and sec_install.get("claim_signature") == install_view.get("claim_signature"),
            "install_source_digest_matches_import": (plan.get("source") or {}).get("artifact_digest")
                == self.skill_installation["source_digest"],
            "sec_subject_matches_real_call": sec_subject.get("platform") == self.platform
                and sec_subject.get("instance_id") == self.instance_id
                and sec_subject.get("agent_id") == self.agent
                and sec_subject.get("session_id") == row.get("session_id"),
            "sec_skill_matches_grant_skill": bool(grant_skill.get("content_hash"))
                and sec_skill.get("skill_id") == grant_skill.get("skill_id")
                and sec_skill.get("content_hash") == grant_skill.get("content_hash"),
            "receipt_attribution_copies_sec": attribution.get("skill_id") == sec_skill.get("skill_id")
                and attribution.get("content_hash") == sec_skill.get("content_hash")
                and attribution.get("context_id") == sec.get("context_id")
                and attribution.get("evidence_level") == sec.get("evidence_level") == "controlled_session",
            "sec_grant_digest_recomputed": bool(sec_authority.get("grant_digest"))
                and sec_authority.get("grant_digest") == grant_digest(grant_doc),
        }
        failed = [name for name, ok in checks.items() if not ok]
        detail = "relations=8/8" if not failed else "failed=" + ",".join(failed)
        return (not failed, detail)

    def attribution_mismatch_negative(self, sec, row, grant_doc, install_view):
        """Tamper one digest-bearing field per copy and require the relation
        check to detect every mismatch, proving the assertion is not vacuous."""
        detections = []
        broken_grant = json.loads(json.dumps(grant_doc))
        broken_grant["status"] = "tampered-" + str(broken_grant.get("status"))
        detections.append(not self.attribution_relations(sec, row, broken_grant, install_view)[0])
        broken_sec = json.loads(json.dumps(sec))
        broken_sec.setdefault("install", {})["claim_signature"] = (
            "0" * 128 if sec.get("install", {}).get("claim_signature") != "0" * 128 else "1" * 128
        )
        detections.append(not self.attribution_relations(broken_sec, row, grant_doc, install_view)[0])
        broken_install = json.loads(json.dumps(install_view))
        broken_install["claim_signature"] = (
            "f" * 128 if install_view.get("claim_signature") != "f" * 128 else "e" * 128
        )
        detections.append(not self.attribution_relations(sec, row, grant_doc, broken_install)[0])
        broken_row = json.loads(json.dumps(row))
        broken_row.setdefault("skill_attribution", {})["content_hash"] = (
            "0" * 64 if (row.get("skill_attribution") or {}).get("content_hash") != "0" * 64 else "1" * 64
        )
        detections.append(not self.attribution_relations(sec, broken_row, grant_doc, install_view)[0])
        return all(detections), "detections=" + str(sum(detections)) + "/4"

    def run_cli(self):
        if not self.session_override:
            return super().run_cli()
        # The product forbids re-binding an enrolled session to a new runtime
        # identity, so the post-update journey runs in an explicit new session.
        command = [
            str(self.args.node),
            "--import",
            str(REPO / "scripts/openclaw-fixture-guard.mjs"),
            str(self.args.openclaw_root / "openclaw.mjs"),
            "agent",
            "--local",
            "--agent",
            fixture.AGENT,
            "--session-id",
            self.session_override,
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
            for value in (self.admin, self.issued.get("credential", {}).get("token", "")):
                if value:
                    detail = detail.replace(value, "<redacted>")
            detail = re.sub(r"[a-fA-F0-9]{32,}", "<digest-or-token>", detail)
            raise RuntimeError(f"native CLI exit {result.returncode}: " + detail)
        payload = json.loads(result.stdout)
        require(
            any(p.get("text") == "fixture-conversation-complete" for p in payload.get("payloads", [])),
            "native run_cli did not complete the fixture conversation",
        )

    def issue_session_context(self, session_id, install_id=None):
        return self.api(
            "/v1/skill-contexts",
            {
                "schema_version": "local-skill-execution-context-issue/v1",
                "instance_id": self.instance_id,
                "session_id": session_id,
                "task_id": "",
                "install_id": install_id or self.skill_installation["install_id"],
                "ttl_seconds": 600,
                "actor_id": "automated-fixture-operator",
                "confirm_issue": True,
            },
            expected=201,
        )

    def restart(self):
        """Restart the daemon on the same port and re-pair, without touching state."""
        port = urlsplit(self.endpoint).port
        self.stop()
        self.log = tempfile.TemporaryFile(mode="w+t")  # noqa: SIM115 -- closed in stop()
        self.proc = subprocess.Popen(
            [str(self.binary), "serve", "--port", str(port), "--mode", "block"],
            cwd=self.workspace,
            env=self.env,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            require(self.proc.poll() is None, "daemon exited before readiness after restart")
            self.log.seek(0)
            found = re.search(r"admin pairing code \(single use, 5 min\): (\S+)", self.log.read())
            if found:
                try:
                    pair = self.api("/v1/pair", {"code": found[1]}, token="")
                    self.admin = pair["session"]
                    return
                except RuntimeError:
                    pass
            time.sleep(0.2)
        require(False, "daemon did not re-pair after restart")

    def refuse(self, route, body, *, status=409):
        """Require the exact refusal status; auth failures and 5xx are not success."""
        try:
            self.api(route, body)
        except RuntimeError as exc:
            message = str(exc)
            require(re.search(rf"expected 200, got {status};", message) is not None,
                    "negative case did not receive the expected refusal status: " + message[:300])
            return message
        require(False, "expected refusal was not returned: " + route)

    def _start_model(self):
        # Two model transcripts exist: the original session and, after the V2
        # update, the explicit new session. Each request is validated against
        # the transcript it actually belongs to.
        harness = self
        calls_issued = self.calls_issued
        # A second native session may use the same fixture server during the
        # raw-content isolation leg. Each OpenClaw session starts with an
        # empty model transcript; never reuse another session's index.
        counters = {"main": 0}
        failures, requests_seen, contents_seen = [], [], []
        self.model_failures, self.model_requests_seen = failures, requests_seen
        self.model_contents_seen = contents_seen

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
                base = {"id": f"r04-fixture-{index}", "created": 0, "model": "siq-r04-fixture"}
                if not stream:
                    self.respond(
                        {**base, "object": "chat.completion", "choices": [{"index": 0, "message": message,
                         "finish_reason": finish}], "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                         "total_tokens": 2}}
                    )
                    return
                if message.get("tool_calls"):
                    message["tool_calls"][0]["index"] = 0
                chunks = [
                    {**base, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": message, "finish_reason": None}]},
                    {**base, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                ]
                raw = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
                self.respond(raw.encode(), "text/event-stream")

            def do_POST(self):
                try:
                    require(self.path == "/v1/chat/completions", "unexpected model route")
                    size = int(self.headers.get("Content-Length", "0"))
                    require(0 < size < 2_000_000, "model request size invalid")
                    body = json.loads(self.rfile.read(size))
                    steps = harness.override_steps if harness.session_override else harness.steps
                    transcript = harness.session_override or "main"
                    index = counters.get(transcript, 0)
                    counters[transcript] = index + 1
                    require(index < len(steps), "unexpected model request")
                    results = [item for item in body.get("messages", []) if item.get("role") == "tool"]
                    expected_results = sum(1 for entry in steps[:index] if entry is not None)
                    require(len(results) == expected_results, "native transcript result count changed")
                    previous = steps[index - 1] if index > 0 else None
                    if isinstance(previous, dict):
                        call = previous
                        require(results, "expected a tool result for the issued call")
                        latest = results[-1]
                        content = str(latest.get("content", ""))
                        contents_seen.append({"index": index, "content": content[:240]})
                        if call.get("expect") == "allow":
                            require("fixture-visible-company-a" in content, "allowed read did not return file content")
                            require("siq-agent-security" not in content, "allowed read leaked block notice")
                        elif call.get("expect") == "deny":
                            require("siq-agent-security" in content, "denied read was not blocked")
                            require("fixture-visible-company-a" not in content, "denied read leaked file content")
                    requests_seen.append({"transcript": transcript, "index": index, "tool_results": len(results)})
                    entry = steps[index]
                    message = {"role": "assistant", "content": "fixture-conversation-complete"}
                    finish = "stop"
                    if entry is not None:
                        calls_issued.append(entry)
                        message = {"role": "assistant", "content": None, "tool_calls": [{
                            "id": entry["id"], "type": "function",
                            "function": {"name": entry["tool"], "arguments": json.dumps(entry["params"])},
                        }]}
                        finish = "tool_calls"
                    self.completion(index, message, finish, bool(body.get("stream")))
                except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc)[:300])
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
                "agents": {"defaults": {"model": {"primary": "siqfixture/siq-r04-fixture", "fallbacks": []},
                  "workspace": str(self.workspace), "skipBootstrap": True},
                 "list": [{"id": fixture.AGENT, "default": True, "workspace": str(self.workspace)}]},
                "tools": {"allow": [self.read_tool], "fs": {"workspaceOnly": True}},
                "models": {"mode": "replace", "providers": {"siqfixture": {
                    "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "apiKey": "synthetic-fixture-key",
                    "api": "openai-completions", "models": [{"id": "siq-r04-fixture", "name": "SIQ R04 Fixture",
                    "contextWindow": 131072, "maxTokens": 512, "reasoning": False, "input": ["text"]}],
                }}},
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
        return server, thread

    def native_turn(self, call=None):
        steps = self.override_steps if self.session_override else self.steps
        steps.append(call)
        if call is not None:
            steps.append(None)
        self.run_cli()

    def read_call(self, call_id, expect="allow"):
        return {
            "id": call_id,
            "tool": self.read_tool,
            "params": {"path": str(self.workspace / "company-a/report.txt")},
            "expect": expect,
        }

    def decision_for(self, before, call_id):
        records = self.receipts()[before:]
        decisions = [
            row for row in records if row.get("record_type") == "decision" and row.get("tool_call_id") == call_id
        ]
        if not decisions:
            # Some denials are recorded under a host-remapped call id; match the
            # turn instead: this helper is only used for single-call turns.
            decisions = [row for row in records if row.get("record_type") == "decision"]
        summary = [
            {key: row.get(key) for key in ("record_type", "tool_call_id", "action", "reason_code", "tool")}
            for row in records
        ]
        require(len(decisions) == 1, call_id + ": decision missing or duplicated; window=" + json.dumps(summary))
        return decisions[0]

    def _candidate(self, import_hex, request_hex, marker_name="fixture-skill-v2"):
        source = self.root / marker_name
        source.mkdir(exist_ok=True)
        (source / "SKILL.md").write_text(
            "---\nname: intent-fixture-v2\ndescription: Read the updated synthetic report.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\n"
            "UPDATED_VERSION_TWO_MARKER: read the fixture report.\n"
        )
        imported = self.api(
            "/v1/skill-imports",
            {
                "schema_version": "local-skill-import-create/v1",
                "import_id": "si-" + import_hex,
                "source_kind": "local_dir",
                "path": str(source),
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
        )["import"]
        result = self.api(
            "/v1/skill-imports/" + imported["import_id"] + "/permissions",
            {
                "schema_version": "local-skill-import-permission-create/v1",
                "request_id": "ip-" + request_hex,
                "artifact_digest": imported["artifact_digest"],
                "analysis_sha256": imported["analysis_sha256"],
                "instance_id": self.instance_id,
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
        )
        route = "/v1/grants/" + result["grant"]["grant_id"]

        def action(name, **body):
            nonlocal result
            result = self.api(
                route + "/" + name,
                {"expected_revision": result["state_revision"], "actor_id": "automated-fixture-operator", **body},
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
        return source, imported, route, result, action

    def _approve(self, action):
        challenge = action("challenge")["challenge"]
        return action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])

    def _compare(self, operation_signature, candidate_grant_id, candidate_revision):
        return self.api(
            f"/v1/skill-installations/operations/{self.current_install}/update-comparison",
            {
                "schema_version": "local-skill-update-compare/v1",
                "operation_signature": operation_signature,
                "candidate_grant_id": candidate_grant_id,
                "expected_candidate_revision": candidate_revision,
            },
        )

    def _removal_view(self):
        return self.api(f"/v1/skill-installations/operations/{self.current_install}/removal")

    def _prepare(self, operation_signature, candidate, previous_revision, binding_signature, request_hex):
        return self.api(
            f"/v1/skill-installations/operations/{self.current_install}/update-plans",
            {
                "schema_version": "local-skill-update-stage-create/v1",
                "request_id": "up-" + request_hex,
                "operation_signature": operation_signature,
                "candidate_grant_id": candidate["grant"]["grant_id"],
                "expected_candidate_revision": candidate["state_revision"],
                "expected_previous_revision": previous_revision,
                "expected_binding_signature": binding_signature,
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
        )["plan"]

    def update_and_run(self):
        target = self.oc / "skills/intent-fixture/SKILL.md"
        require(target.exists(), "V1 target missing")
        v1_bytes = target.read_bytes()
        catalog_before = self.command(
            [str(self.args.node), str(self.args.openclaw_root / "openclaw.mjs"), "skills", "list",
             "--agent", fixture.AGENT, "--json"],
            env=self.env,
            timeout=60,
        )
        require("intent-fixture" in catalog_before, "V1 Skill absent from native catalog before update")
        operations_before = len(self.api("/v1/skill-installations/operations")["items"])
        identities_before = {
            row["identity_id"] for row in self.api("/v1/runtime-identities")["items"]
        }
        openclaw_config_path = self.oc / "openclaw.json"
        adapter_config_path = self.oc / "siq-agent-security.json"
        openclaw_config_sha = hashlib.sha256(openclaw_config_path.read_bytes()).hexdigest()
        # Unknown user-owned files must survive update and removal untouched.
        user_files = {
            self.oc / "skills/user-own-skill/NOTES.txt": "user owned: keep\n",
            self.oc / "skills/README-user.txt": "user owned: keep\n",
            self.root / "user-data.txt": "user owned: keep\n",
        }
        for path, content in user_files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

        results = []
        self.update_results = results

        def record(check_id, expectation, ok, actual, evidence="controlled"):
            results.append({
                "id": check_id, "expectation": expectation, "actual": actual,
                "status": "pass" if ok else "fail", "evidence_level": evidence,
            })
            require(ok, check_id + ": " + actual)

        server, thread = self._start_model()
        try:
            # Journey step 2/3: V1 runs on the real host after explicit authorize+attach.
            self.native_turn()
            self.native_turn()
            before = len(self.receipts())
            self.native_turn(self.read_call("r04-pre-sec", expect="deny"))
            pre = self.decision_for(before, "r04-pre-sec")
            record("missing_sec_denied_before_v1_read", "pre-SEC native read denied fail-closed",
                   pre["action"] == "deny", "action=" + pre["action"])
            session = pre["session_id"]
            sec1 = self.issue_session_context(session)
            before = len(self.receipts())
            self.native_turn(self.read_call("r04-v1-read", expect="allow"))
            v1_row = self.decision_for(before, "r04-v1-read")
            attribution = v1_row.get("skill_attribution") or {}
            record(
                "v1_native_read_allowed_with_verified_session_attribution",
                "V1 native read allowed with verified controlled_session attribution bound to the issued SEC",
                v1_row["action"] == "allow" and attribution.get("status") == "verified"
                and attribution.get("evidence_level") == "controlled_session"
                and attribution.get("context_id") == sec1["context_id"],
                "action=" + v1_row["action"] + " attribution=" + json.dumps(attribution)[:220],
            )
            record(
                "v1_call_binding_recomputed",
                "controlled-session call binding matches the canonical hash of the real call",
                attribution.get("call_binding") == canonical_hash(
                    {"platform": v1_row["platform"], "session_id": v1_row["session_id"],
                     "agent_id": v1_row["agent_id"], "task_id": "-", "tool": v1_row["tool"],
                     "tool_call_id": v1_row["tool_call_id"], "params": self.read_call("r04-v1-read")["params"]}
                ),
                "call_binding=" + str(attribution.get("call_binding"))[:16] + "…",
            )
            content_hash_v1 = attribution.get("content_hash")
            old_view = self.api("/v1/skill-installations/operations/" + self.current_install)
            old_grant_route = "/v1/grants/" + old_view["plan"]["grant_id"]
            v1_grant_view = self.api(old_grant_route)
            v1_grant_doc = v1_grant_view["grant"]
            v1_revision_start = v1_grant_view["state_revision"]
            old_identity = self.issued["identity"]["identity_id"]
            sec1_read = self.api("/v1/skill-contexts/" + sec1["context_id"])
            relations_ok, relations_detail = self.attribution_relations(sec1_read, v1_row, v1_grant_doc, old_view)
            record(
                "v1_attribution_correlates_grant_install_sec",
                "install record, runtime identity, grant document, SEC and receipt correlate field-by-field: one grant id across all five, SEC pins the install claim signature and the real subject, receipt attribution copies the SEC skill/content hash, SEC authority grant digest recomputes from the live grant document",
                relations_ok and bool(content_hash_v1) and bool(self.skill_installation["source_digest"]),
                relations_detail + " matched_grant_id=" + str(v1_row.get("matched_grant_id")) + " content_hash="
                + str(content_hash_v1)[:16] + "… install_digest=" + str(self.skill_installation["source_digest"])[:16] + "…",
            )
            mismatch_ok, mismatch_detail = self.attribution_mismatch_negative(sec1_read, v1_row, v1_grant_doc, old_view)
            record(
                "v1_attribution_digest_mismatch_detected",
                "tampering any one side's digest (grant document, SEC install pin, install claim signature, receipt content hash) is detected by the relation check",
                mismatch_ok,
                mismatch_detail,
            )

            # UP01 + journey step 4: candidate import alone must not change anything.
            source, imported, candidate_route, candidate, action = self._candidate("d" * 32, "e" * 32)
            catalog = self.command(
                [str(self.args.node), str(self.args.openclaw_root / "openclaw.mjs"), "skills", "list",
                 "--agent", fixture.AGENT, "--json"],
                env=self.env, timeout=60,
            )
            up01_removal = self._removal_view()
            record(
                "up01_import_generates_check_data_only",
                "importing a candidate creates only import/analysis data: no install, no permission change, no confirmation",
                len(self.api("/v1/skill-installations/operations")["items"]) == operations_before
                and {row["identity_id"] for row in self.api("/v1/runtime-identities")["items"]} == identities_before
                and self.api(old_grant_route)["state_revision"] == v1_revision_start
                and target.read_bytes() == v1_bytes
                and "intent-fixture-v2" not in catalog
                and up01_removal["status"] == "not_requested",
                "installations=" + str(len(self.api("/v1/skill-installations/operations")["items"]))
                + " grant_revision=" + str(self.api(old_grant_route)["state_revision"])
                + " target_unchanged=" + str(target.read_bytes() == v1_bytes)
                + " v2_in_catalog=" + str("intent-fixture-v2" in catalog)
                + " removal_status=" + up01_removal["status"],
            )

            # Journey step 4 comparison is read-only; permission growth is displayed.
            preview = self._compare(old_view["operation"]["signature"], candidate["grant"]["grant_id"],
                                    candidate["state_revision"])
            preview_dump = json.dumps(preview)
            record(
                "comparison_requires_confirmation_with_content_and_permission_diff",
                "update-comparison demands explicit confirmation, reports content changes and shows the added permission",
                preview["requires_confirmation"] and preview["content_changes_total"] > 0
                and self.write_tool in preview_dump,
                "requires_confirmation=" + str(preview["requires_confirmation"])
                + " content_changes_total=" + str(preview["content_changes_total"])
                + " permission_displayed=" + str(self.write_tool in preview_dump),
            )
            record(
                "comparison_is_read_only",
                "comparison changes neither the installed target nor V1 authority",
                target.read_bytes() == v1_bytes
                and self.api(old_grant_route)["state_revision"] == v1_revision_start
                and self.api(candidate_route)["state_revision"] == candidate["state_revision"],
                "target_unchanged=" + str(target.read_bytes() == v1_bytes)
                + " v1_revision=" + str(self.api(old_grant_route)["state_revision"])
                + " expected_revision=" + str(v1_revision_start)
                + " candidate_revision=" + str(self.api(candidate_route)["state_revision"]),
            )

            # UP02: repeated comparison and cancel-before-confirm keep V1 intact.
            preview_again = self._compare(old_view["operation"]["signature"], candidate["grant"]["grant_id"],
                                          candidate["state_revision"])
            before = len(self.receipts())
            self.native_turn(self.read_call("r04-v1-cancelled", expect="allow"))
            cancelled_row = self.decision_for(before, "r04-v1-cancelled")
            record(
                "up02_cancel_and_repeated_requests_keep_v1",
                "cancel (no confirmation) and duplicate comparison cause no update; V1 keeps running with unchanged permissions",
                preview_again["requires_confirmation"] == preview["requires_confirmation"]
                and preview_again["content_changes_total"] == preview["content_changes_total"]
                and cancelled_row["action"] == "allow"
                and (cancelled_row.get("skill_attribution") or {}).get("context_id") == sec1["context_id"]
                and target.read_bytes() == v1_bytes
                and self._removal_view()["status"] == "not_requested",
                "duplicate_compare_match=" + str(preview_again["content_changes_total"] == preview["content_changes_total"])
                + " v1_still_allows=" + str(cancelled_row["action"])
                + " target_unchanged=" + str(target.read_bytes() == v1_bytes),
            )

            # UP07 integrity subcase: a request with a wrong snapshot digest must fail.
            up07_source = self.root / "fixture-skill-v2-stale"
            up07_source.mkdir()
            (up07_source / "SKILL.md").write_text(
                "---\nname: intent-fixture-v2-stale\ndescription: Stale digest probe.\n"
                f"allowed-tools: {self.read_tool}\n---\nSTALE_MARKER\n"
            )
            up07_import = self.api(
                "/v1/skill-imports",
                {
                    "schema_version": "local-skill-import-create/v1",
                    "import_id": "si-" + "b" * 32,
                    "source_kind": "local_dir",
                    "path": str(up07_source),
                    "actor_id": "automated-fixture-operator",
                },
                expected=201,
            )["import"]
            (up07_source / "SKILL.md").write_text(
                "---\nname: intent-fixture-v2-stale\ndescription: Stale digest probe.\n"
                f"allowed-tools: {self.read_tool}\n---\nMUTATED_AFTER_IMPORT_MARKER\n"
            )
            up07_error = self.refuse(
                "/v1/skill-imports/" + up07_import["import_id"] + "/permissions",
                {
                    "schema_version": "local-skill-import-permission-create/v1",
                    "request_id": "ip-" + "3" * 32,
                    "artifact_digest": "0" * 64,
                    "analysis_sha256": up07_import["analysis_sha256"],
                    "instance_id": self.instance_id,
                    "actor_id": "automated-fixture-operator",
                },
            )
            record(
                "up07_stale_candidate_digest_refused",
                "permission analysis with a wrong imported snapshot digest returns 409 changed",
                "got 409;" in up07_error and "changed" in up07_error,
                up07_error[:200],
            )
            shutil.rmtree(up07_source)

            # Import owns an immutable snapshot. Disappearing external source
            # does not change the valid comparison, installed bytes or authority.
            moved = source.with_name("fixture-skill-v2-moved-away")
            before_source_loss = (self.api(old_grant_route), self.api(candidate_route), target.read_bytes())
            source.rename(moved)
            try:
                up10_preview = self._compare(old_view["operation"]["signature"], candidate["grant"]["grant_id"],
                                            candidate["state_revision"])
                record("up10_source_unavailable_recorded", "missing external local source preserves the imported snapshot comparison, grants and target",
                       up10_preview["requires_confirmation"]
                       and up10_preview["content_changes_total"] == preview["content_changes_total"]
                       and before_source_loss == (self.api(old_grant_route), self.api(candidate_route), target.read_bytes()),
                       "snapshot_comparison_http=200 content_delta_unchanged=true grants_and_target_unchanged=true")
            finally:
                moved.rename(source)

            # Journey step 5: confirm update only after explicit challenge/approve of the candidate.
            candidate = self._approve(action)
            comparison = self._compare(old_view["operation"]["signature"], candidate["grant"]["grant_id"],
                                       candidate["state_revision"])
            removal = self._removal_view()
            record(
                "approved_candidate_recomparison_and_removal_view",
                "re-comparison after approval succeeds and removal view reports not_requested with a binding signature",
                comparison["requires_confirmation"] and removal["status"] == "not_requested"
                and bool(removal["binding_signature"]),
                "requires_confirmation=" + str(comparison["requires_confirmation"])
                + " removal_status=" + removal["status"]
                + " binding=" + str(removal["binding_signature"])[:16] + "…",
            )

            # UP06: a user-modified install target must not be silently overwritten.
            target.write_bytes(v1_bytes + b"\n<!-- user edit while update pending -->\n")
            up06_error = ""
            try:
                up06_plan = self._prepare(
                    old_view["operation"]["signature"], candidate, comparison["previous_revision"],
                    removal["binding_signature"], "6" * 32,
                )
                up06_error = self.refuse(
                    "/v1/skill-installations/updates",
                    {
                        "schema_version": "local-skill-update-commit/v1",
                        "update_id": up06_plan["update_id"],
                        "plan_signature": up06_plan["signature"],
                        "actor_id": up06_plan["actor_id"],
                        "confirm_update": True,
                    },
                )
                up06_layer = "commit"
            except RuntimeError as exc:
                up06_error = str(exc)
                up06_layer = "prepare"
            record(
                "up06_user_modified_target_not_silently_overwritten",
                "prepare or commit refuses when the installed target was modified after installation",
                "got 409;" in up06_error and "skill_install_changed" in up06_error
                and target.read_bytes() == v1_bytes + b"\n<!-- user edit while update pending -->\n",
                "refused at " + up06_layer + ": " + up06_error[:200],
            )
            target.write_bytes(v1_bytes)

            # UP03/UP04: drift after approval cannot ride an older confirmation.
            prepared = self._prepare(
                old_view["operation"]["signature"], candidate, comparison["previous_revision"],
                removal["binding_signature"], "f" * 32,
            )
            record(
                "prepared_update_leaves_v1_in_place_before_confirmation",
                "staging the update changes nothing on the host before explicit confirmation",
                target.read_bytes() == v1_bytes,
                "target_unchanged=" + str(target.read_bytes() == v1_bytes),
            )
            up04_error = self.refuse(
                candidate_route + "/patch-desired",
                {
                    "expected_revision": candidate["state_revision"],
                    "actor_id": "automated-fixture-operator",
                    "tools": [self.read_tool, self.write_tool],
                    "filesystem": {"read_only": [str(self.workspace), str(self.root)],
                                   "read_write": [str(self.root / "extra-rw")]},
                }, status=400,
            )
            record(
                "up04_new_permissions_require_fresh_confirmation",
                "widening permissions after approval is refused by the state machine; added permissions must re-enter pending approval and a fresh confirmation",
                bool(up04_error) and "pending_approval" in up04_error,
                up04_error[:220],
            )
            up03_error = self.refuse(
                "/v1/skill-installations/updates",
                {
                    "schema_version": "local-skill-update-commit/v1",
                    "update_id": prepared["update_id"],
                    "plan_signature": prepared["signature"][:-8] + "00000000",
                    "actor_id": prepared["actor_id"],
                    "confirm_update": True,
                },
            )
            record(
                "up03_forged_plan_signature_refused",
                "commit refuses a forged plan signature (separate from content drift)",
                bool(up03_error),
                up03_error[:220],
            )

            # Actual candidate mutation with the valid signed confirmation.
            source_file = self.state / "skill-installations" / "update-stages" / prepared["update_id"] / "payload" / "SKILL.md"
            approved_bytes = source_file.read_bytes()
            before_drift = (self.api(old_grant_route), self.api(candidate_route), target.read_bytes())
            try:
                source_file.write_bytes(approved_bytes + b"\nCANDIDATE_DRIFT_NEGATIVE_FIXTURE\n")
                drift_error = self.refuse("/v1/skill-installations/updates", {
                    "schema_version": "local-skill-update-commit/v1",
                    "update_id": prepared["update_id"], "plan_signature": prepared["signature"],
                    "actor_id": prepared["actor_id"], "confirm_update": True,
                })
                record("up03_candidate_drift_after_approval_refused",
                       "valid signed confirmation cannot commit changed candidate bytes; installed content and both grants remain unchanged",
                       "got 409;" in drift_error and "changed" in drift_error
                       and before_drift == (self.api(old_grant_route), self.api(candidate_route), target.read_bytes()),
                       "valid_signature=true candidate_changed=true grants_and_target_unchanged=true " + drift_error)
            finally:
                source_file.write_bytes(approved_bytes)

            # UP08: restart the daemon on the same state; recovery must use real records.
            self.restart()
            update = self.api(
                "/v1/skill-installations/updates",
                {
                    "schema_version": "local-skill-update-commit/v1",
                    "update_id": prepared["update_id"],
                    "plan_signature": prepared["signature"],
                    "actor_id": prepared["actor_id"],
                    "confirm_update": True,
                },
            )
            record(
                "up08_commit_after_daemon_restart_from_recorded_plan",
                "after restart the prepared update commits from the durable transaction record, without blind rewrites",
                update["status"] == "updated_unverified",
                "commit_status=" + update["status"],
                evidence="controlled",
            )
            record(
                "update_replaces_target_bytes",
                "confirmed update writes V2 content to the installed target",
                target.read_bytes() == (source / "SKILL.md").read_bytes(),
                "target_matches_v2=" + str(target.read_bytes() == (source / "SKILL.md").read_bytes()),
            )
            record(
                "update_revokes_v1_grant",
                "V1 Grant becomes revoked after the update commits",
                self.api(old_grant_route)["grant"]["status"] == "revoked",
                "v1_grant_status=" + self.api(old_grant_route)["grant"]["status"],
            )
            old_row = next(
                row for row in self.api("/v1/runtime-identities")["items"] if row["identity_id"] == old_identity
            )
            record(
                "v1_runtime_identity_becomes_unavailable",
                "V1 runtime identity drops to grant_unavailable and is retired explicitly",
                old_row["status"] == "grant_unavailable"
                and self.api(f"/v1/runtime-identities/{old_identity}/revoke",
                             {"schema_version": "local-runtime-identity-revoke/v1",
                              "actor_id": "automated-fixture-operator"})["revoked"] is True,
                "v1_identity_status=" + old_row["status"],
            )

            # UP09: the V1 session SEC must not authorize V2.
            before = len(self.receipts())
            self.native_turn(self.read_call("r04-old-sec-on-v2", expect="deny"))
            after_receipts = len(self.receipts())
            content_note = self.model_contents_seen[-1]["content"] if self.model_contents_seen else ""
            no_leak = "siq-agent-security" in content_note and "fixture-visible-company-a" not in content_note
            up09_expectation = (
                "the pre-update session SEC no longer authorizes reads after the update; denial has no tool side effect"
            )
            try:
                up09_row = self.decision_for(before, "r04-old-sec-on-v2")
                record(
                    "up09_old_context_cannot_authorize_new_version",
                    up09_expectation,
                    up09_row["action"] == "deny" and no_leak,
                    "action=" + str(up09_row.get("action")) + " reason_code=" + str(up09_row.get("reason_code"))
                    + " no_leak=" + str(no_leak),
                )
            except RuntimeError:
                record(
                    "up09_old_context_cannot_authorize_new_version",
                    up09_expectation,
                    no_leak and after_receipts == before,
                    "hook refused the stale session SEC before attribution (no decision receipt written, receipts "
                    f"{before}->{after_receipts}); tool content: " + content_note,
                    evidence="observed",
                )

            # Journey step 6: activate V2, new identity, new authorization, real host load.
            installation = update["installation"]
            new_install = installation["install_id"]
            activation = self.api(
                f"/v1/skill-installations/operations/{new_install}/activate",
                {
                    "schema_version": "local-skill-install-activate/v1",
                    "operation_signature": installation["signature"],
                    "expected_revision": candidate["state_revision"],
                    "actor_id": "automated-fixture-operator",
                    "confirm_instance_scope": True,
                },
            )
            self.current_install = new_install
            self.skill_installation = {
                "install_id": new_install,
                "source_digest": imported["artifact_digest"],
                "grant_id": candidate["grant"]["grant_id"],
            }
            self.issued = self.api(
                "/v1/runtime-identities",
                {
                    "schema_version": "local-runtime-identity-create/v1",
                    "instance_id": self.instance_id,
                    "grant_id": candidate["grant"]["grant_id"],
                    "expected_grant_revision": activation["state_revision"],
                    "actor_id": "automated-fixture-operator",
                    "session_ttl_seconds": 3600,
                },
                expected=201,
            )
            adapter = self.api(
                "/v1/adapter/preview",
                {
                    "platform": "openclaw",
                    "action": "install",
                    "instance_id": self.instance_id,
                    "runtime_identity_id": self.issued["identity"]["identity_id"],
                },
            )
            self.api(
                "/v1/adapter/install",
                {
                    "platform": "openclaw",
                    "instance_id": self.instance_id,
                    "plan_id": adapter["plan_id"],
                    "plan_digest": adapter["plan_digest"],
                    "runtime_identity_id": adapter["runtime_identity_id"],
                    "actor_id": "automated-fixture-operator",
                },
            )
            configured = json.loads(adapter_config_path.read_text())
            record(
                "v2_activation_identity_and_adapter_rebind",
                "V2 needs new activation, identity and adapter binding; the adapter config points at the new identity",
                configured["runtimeIdentityId"] == self.issued["identity"]["identity_id"],
                "runtimeIdentityId=" + str(configured["runtimeIdentityId"])[:16] + "…",
            )
            # The product forbids re-binding an enrolled session to a new runtime
            # identity, so the post-update phase runs in an explicit new OpenClaw
            # session (--session-id). This is a supported CLI path, not a manual
            # production-state replacement; the step and reason are recorded here.
            self.session_override = "r04-v2-session-" + canonical_hash({"v2_install": new_install})[:12]
            before_pre = len(self.receipts())
            self.native_turn(self.read_call("r04-v2-pre-sec", expect="deny"))
            pre_rows = self.receipts()[before_pre:]
            pre_denied = any(
                row.get("record_type") == "decision"
                and row.get("tool_call_id") == "r04-v2-pre-sec"
                and row.get("action") == "deny"
                for row in pre_rows
            )
            pre_row = next(
                (row for row in pre_rows if row.get("tool_call_id") == "r04-v2-pre-sec" and row.get("action") == "deny"),
                None,
            )
            pre_denied = pre_row is not None
            # OpenClaw namespaces the CLI session id ("agent:<agent>:explicit:<id>");
            # the SEC must be issued against the effective id from the receipt.
            v2_session = (pre_row or {}).get("session_id")
            record(
                "v2_new_session_pre_sec_denied",
                "the new session enrolls under the V2 identity and is denied before any SEC exists",
                pre_denied and bool(v2_session),
                "pre_sec_denied=" + str(pre_denied) + " session=" + str(v2_session),
            )
            require(pre_denied and v2_session, "new session pre-SEC deny did not produce a decision receipt")
            sec2 = self.issue_session_context(v2_session, install_id=new_install)
            catalog = self.command(
                [str(self.args.node), str(self.args.openclaw_root / "openclaw.mjs"), "skills", "list",
                 "--agent", fixture.AGENT, "--json"],
                env=self.env, timeout=60,
            )
            before = len(self.receipts())
            self.native_turn(self.read_call("r04-v2-read", expect="allow"))
            v2_row = self.decision_for(before, "r04-v2-read")
            attribution2 = v2_row.get("skill_attribution") or {}
            record(
                "v2_native_read_allowed_with_new_sec",
                "V2 native read allowed only through the freshly issued SEC bound to the new installation",
                v2_row["action"] == "allow" and attribution2.get("status") == "verified"
                and attribution2.get("context_id") == sec2["context_id"]
                and attribution2.get("content_hash") not in (None, content_hash_v1),
                "action=" + v2_row["action"] + " context_matches=" + str(attribution2.get("context_id") == sec2["context_id"])
                + " content_changed=" + str(attribution2.get("content_hash") not in (None, content_hash_v1)),
            )
            record(
                "v2_loaded_in_native_catalog",
                "the updated Skill is present in the real OpenClaw catalog after the update",
                "intent-fixture-v2" in catalog,
                "catalog_contains_v2=" + str("intent-fixture-v2" in catalog),
            )

            # Journey step 7: safe removal; unknown user files must be preserved.
            remove_view = self._removal_view()
            removed = self.api(
                f"/v1/skill-installations/operations/{self.current_install}/removal",
                {
                    "schema_version": "local-skill-install-remove/v1",
                    "operation_signature": remove_view["record"]["operation"]["signature"],
                    "expected_grant_revision": remove_view["state_revision"],
                    "expected_binding_signature": remove_view["binding_signature"],
                    "actor_id": "automated-fixture-operator",
                    "confirm_remove": True,
                },
            )
            record(
                "removal_revokes_authority_and_removes_target",
                "explicit removal revokes the V2 grant and removes the installed target",
                removed["status"] == "removed" and removed["result"]["grant_revoked"]
                and not target.parent.exists(),
                "status=" + removed["status"] + " grant_revoked=" + str(removed["result"]["grant_revoked"])
                + " target_gone=" + str(not target.parent.exists()),
            )
            current_row = next(
                row for row in self.api("/v1/runtime-identities")["items"]
                if row["identity_id"] == self.issued["identity"]["identity_id"]
            )
            record(
                "v2_identity_survives_nothing_after_removal",
                "the V2 runtime identity is grant_unavailable after removal",
                current_row["status"] == "grant_unavailable",
                "v2_identity_status=" + current_row["status"],
            )
            preserved = {str(path): path.is_file() and path.read_text() == content
                         for path, content in user_files.items()}
            record(
                "unknown_user_files_preserved",
                "user files outside the managed install target survive update and removal byte-for-byte",
                all(preserved.values()),
                json.dumps(preserved),
            )
            record(
                "host_config_final_state_preserved",
                "OpenClaw host config keeps the plugin wiring and adapter state file remains after skill removal",
                openclaw_config_path.is_file() and adapter_config_path.is_file()
                and "siq-agent-security" in openclaw_config_path.read_text(),
                "openclaw_json_present=" + str(openclaw_config_path.is_file())
                + " adapter_state_present=" + str(adapter_config_path.is_file())
                + " openclaw_config_sha256_before=" + openclaw_config_sha[:16] + "…",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        require(
            not self.model_failures
            and len(self.model_requests_seen) == len(self.steps) + len(self.override_steps),
            "native model exchange incomplete: " + repr(self.model_failures),
        )
        receipt_count = len(self.receipts())
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        record("receipt_chain_verified", "signed receipt chain verifies", verified["verified"],
               "verified=" + str(verified["verified"]))

        return {
            "schema_version": "personal-r04-openclaw-native-update/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": all(item["status"] == "pass" for item in results),
            "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "native_cli_sha256": hashlib.sha256((self.args.openclaw_root / "openclaw.mjs").read_bytes()).hexdigest(),
            "openclaw_version": json.loads((self.args.openclaw_root / "package.json").read_text())["version"],
            "native_entrypoint": "public openclaw agent --local; real plugin hook and file tool lifecycle",
            "results": results,
            "checks": [item["id"] for item in results],
            "up_coverage": {
                "UP01": "pass", "UP02": "pass", "UP03": "pass", "UP04": "pass",
                "UP05": "partial (stale-binding refusals exercised; concurrent operator interleaving out of scope here)",
                "UP06": "pass", "UP07": "partial (source digest refusal only; old/future state compatibility not covered)", "UP08": "pass", "UP09": "pass", "UP10": "partial (local source unavailable only)",
            },
            "receipt_count": receipt_count,
            "v1_install_id": old_view["install_id"],
            "v2_install_id": installation["install_id"],
            "v1_content_hash": content_hash_v1,
            "v2_content_hash": attribution2.get("content_hash"),
            "session_attribution_limitation": (
                "OpenClaw exposes no trustworthy per-task Skill tool-causality field; evidence level is "
                "controlled_session throughout, not controlled_task"
            ),
            "limitations": [
                "local deterministic model and synthetic operator; no external or paid model",
                "candidate V2 is an explicitly imported local directory; public-network scheduled fetch is separate (does not close J6)",
                "session-level attribution only (controlled_session); same-UID compromise and OS sandbox isolation remain outside the SEC threat boundary",
                "UP05 covers stale-binding refusals, not two live operators racing; UP10 records the product's chosen safe behaviour",
                "a session enrolled under the V1 identity can never be re-bound to the V2 identity (runtimeidentity.Store refuses the switch; SEC issuance then fails with skill_context_session_unbound), so the post-update journey uses an explicit new OpenClaw session (--session-id) — a supported CLI path, not a manual production-state replacement",
                "update flows here are local-dir journeys; production Git obeys R03 and is unchanged",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists() and not args.out.with_suffix(".failure.json").exists(),
            "refusing to overwrite a previous run report")
    args.openclaw_root, args.node, args.binary = (
        args.openclaw_root.resolve(), args.node.resolve(), args.binary.resolve()
    )
    require(args.node.is_file(), "Node executable not found")
    require((args.openclaw_root / "openclaw.mjs").is_file(), "OpenClaw entrypoint not found")
    with tempfile.TemporaryDirectory(prefix="siq-r04-openclaw-update-") as temporary:
        harness = Harness(Path(temporary), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.update_and_run()
        except Exception as exc:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            failure = args.out.with_suffix(".failure.json")
            with failure.open("x", encoding="utf-8") as handle:
                failure.chmod(0o600)
                json.dump({"passed": False, "error_type": type(exc).__name__,
                           "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                           "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           "checks": [{"id": item["id"], "status": item["status"]}
                                      for item in getattr(harness, "update_results", [])]}, handle, indent=2)
            raise
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["results"])}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- report category only, exit nonzero
        print(f"OpenClaw native update smoke failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
