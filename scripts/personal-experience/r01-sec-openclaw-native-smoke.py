#!/usr/bin/env python3
"""Verify a session-scoped Skill Execution Context through real OpenClaw hooks.

The run uses an isolated OpenClaw profile, the product import/install and
managed-adapter APIs, the public ``openclaw agent --local`` entrypoint, and a
local deterministic model fixture. The first native read enrolls the session
but is denied without a SEC. An administrator then issues a session-scoped SEC
and the same real file tool is allowed. Revoking the SEC makes a later call in
the same native session fail closed. No external or paid model is contacted.
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
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "openclaw_managed_fixture", ROOT / "scripts/personal-experience/openclaw-managed-native-smoke.py"
)
managed = importlib.util.module_from_spec(loader)
loader.loader.exec_module(managed)
require = managed.require
fixture = managed.fixture


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


class Harness(managed.Harness):
    def setup_authority(self):
        # Reuse the shipped managed-install journey, then replace its baseline
        # permission with an installation-bound Skill permission.
        super().setup_authority()
        self.api(
            "/v1/runtime-identities/" + self.issued["identity"]["identity_id"] + "/revoke",
            {"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "automated-fixture-operator"},
        )
        skill = self.root / "sec-openclaw-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: intent-fixture\ndescription: Read the controlled fixture report.\n"
            f"allowed-tools: {self.read_tool}\n---\nRead only the requested fixture report.\n"
        )
        imported = self.api(
            "/v1/skill-imports",
            {
                "schema_version": "local-skill-import-create/v1",
                "import_id": "si-" + "7" * 32,
                "source_kind": "local_dir",
                "path": str(skill),
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
        )["import"]
        result = self.api(
            f"/v1/skill-imports/{imported['import_id']}/permissions",
            {
                "schema_version": "local-skill-import-permission-create/v1",
                "request_id": "ip-" + "8" * 32,
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
            tools=[self.read_tool],
            filesystem={"read_only": [str(self.workspace)], "read_write": []},
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
                "request_id": "is-" + "9" * 32,
                "grant_id": result["grant"]["grant_id"],
                "expected_revision": result["state_revision"],
                "instance_id": self.instance_id,
                "directory_name": "intent-fixture",
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
        )["plan"]
        installed = self.api(
            "/v1/skill-installations/apply",
            {
                "schema_version": "local-skill-install-apply/v1",
                "plan_id": plan["plan_id"],
                "plan_signature": plan["signature"],
                "actor_id": "automated-fixture-operator",
                "confirm_install": True,
            },
        )
        installed_skill = self.oc / "skills" / "intent-fixture" / "SKILL.md"
        require(installed_skill.is_file(), "installation result missing OpenClaw Skill payload")
        require("name: intent-fixture" in installed_skill.read_text(), "installed OpenClaw Skill payload changed")
        self.api(
            f"/v1/skill-installations/operations/{installed['install_id']}/activate",
            {
                "schema_version": "local-skill-install-activate/v1",
                "operation_signature": installed["operation"]["signature"],
                "expected_revision": result["state_revision"],
                "actor_id": "automated-fixture-operator",
                "confirm_instance_scope": True,
            },
        )
        result = self.api(grant_path)
        self.skill_installation = {
            "install_id": installed["install_id"],
            "source_digest": imported["artifact_digest"],
            "grant_id": result["grant"]["grant_id"],
        }
        self.issued = self.api(
            "/v1/runtime-identities",
            {
                "schema_version": "local-runtime-identity-create/v1",
                "instance_id": self.instance_id,
                "grant_id": result["grant"]["grant_id"],
                "expected_grant_revision": result["state_revision"],
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
        configured = json.loads((self.oc / "siq-agent-security.json").read_text())
        require(
            configured["runtimeIdentityId"] == self.issued["identity"]["identity_id"],
            "adapter did not switch to installation-bound identity",
        )

    def issue_session_context(self, session_id):
        return self.api(
            "/v1/skill-contexts",
            {
                "schema_version": "local-skill-execution-context-issue/v1",
                "instance_id": self.instance_id,
                "session_id": session_id,
                "task_id": "",
                "install_id": self.skill_installation["install_id"],
                "ttl_seconds": 600,
                "actor_id": "automated-fixture-operator",
                "confirm_issue": True,
            },
            expected=201,
        )

    def revoke_context(self, context):
        return self.api(
            f"/v1/skill-contexts/{context['context_id']}/revoke",
            {
                "schema_version": "local-skill-execution-context-revoke/v1",
                "expected_context_signature": context["signature"],
                "actor_id": "automated-fixture-operator",
                "confirm_revoke": True,
            },
        )

    def native_sec(self):
        report_path = self.workspace / "company-a/report.txt"
        calls = {
            "pre-sec": {"id": "openclaw-pre-sec", "tool": self.read_tool, "params": {"path": str(report_path)}},
            "with-sec": {"id": "openclaw-with-sec", "tool": self.read_tool, "params": {"path": str(report_path)}},
            "after-revoke": {
                "id": "openclaw-after-revoke", "tool": self.read_tool, "params": {"path": str(report_path)}
            },
        }
        steps = [None, calls["pre-sec"], None, calls["with-sec"], None, calls["after-revoke"], None]
        requests, failures = [], []
        self.model_failures, self.model_requests_seen = failures, requests

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
                base = {"id": f"sec-fixture-{index}", "created": 0, "model": "siq-sec-fixture"}
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
                    index = len(requests)
                    require(index < len(steps), "unexpected model request")
                    results = [item for item in body.get("messages", []) if item.get("role") == "tool"]
                    expected_results = index // 2
                    require(len(results) == expected_results, "native transcript result count changed")
                    if index in (2, 4, 6):
                        latest = str(results[-1].get("content", ""))
                        if index == 4:
                            require("fixture-visible-company-a" in latest, "SEC-protected read did not execute")
                        else:
                            require("siq-agent-security" in latest, "unprotected read was not blocked")
                            require("fixture-visible-company-a" not in latest, "denied read leaked file content")
                    requests.append({"index": index, "tool_results": len(results), "stream": bool(body.get("stream"))})
                    call = steps[index]
                    message = {"role": "assistant", "content": "fixture-conversation-complete"}
                    finish = "stop"
                    if call is not None:
                        message = {"role": "assistant", "content": None, "tool_calls": [{
                            "id": call["id"], "type": "function",
                            "function": {"name": call["tool"], "arguments": json.dumps(call["params"])},
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
                "agents": {"defaults": {"model": {"primary": "siqfixture/siq-sec-fixture", "fallbacks": []},
                  "workspace": str(self.workspace), "skipBootstrap": True},
                 "list": [{"id": fixture.AGENT, "default": True, "workspace": str(self.workspace)}]},
                "tools": {"allow": [self.read_tool], "fs": {"workspaceOnly": True}},
                "models": {"mode": "replace", "providers": {"siqfixture": {
                    "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "apiKey": "synthetic-fixture-key",
                    "api": "openai-completions", "models": [{"id": "siq-sec-fixture", "name": "SIQ SEC Fixture",
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
        skill_catalog = self.command(
            [str(self.args.node), str(self.args.openclaw_root / "openclaw.mjs"), "skills", "list", "--agent", fixture.AGENT, "--json"],
            env=self.env,
            timeout=60,
        )
        require(
            "intent-fixture" in skill_catalog,
            "installed Skill absent from native OpenClaw catalog; payload="
            + repr((self.oc / "skills" / "intent-fixture" / "SKILL.md").read_text())
            + " catalog=" + repr(skill_catalog[:1200]),
        )
        try:
            self.run_cli()
            self.run_cli()
            pre_rows = [r for r in self.receipts() if r.get("tool_call_id") == calls["pre-sec"]["id"]]
            require(pre_rows, "pre-SEC receipt missing: " + repr([(r.get("tool_call_id"), r.get("reason_code")) for r in self.receipts()]))
            pre = pre_rows[0]
            require(pre["action"] == "deny", "pre-SEC native call was not denied")
            session = pre["session_id"]
            sec = self.issue_session_context(session)
            self.run_cli()
            protected = next(r for r in self.receipts() if r.get("tool_call_id") == calls["with-sec"]["id"])
            attribution = protected.get("skill_attribution") or {}
            require(
                protected["action"] == "allow" and attribution.get("status") == "verified"
                and attribution.get("evidence_level") == "controlled_session"
                and attribution.get("context_id") == sec["context_id"],
                "session SEC did not protect the native call",
            )
            want_binding = canonical_hash(
                {"platform": protected["platform"], "session_id": protected["session_id"],
                 "agent_id": protected["agent_id"], "task_id": "-", "tool": protected["tool"],
                 "tool_call_id": protected["tool_call_id"], "params": calls["with-sec"]["params"]}
            )
            require(attribution["call_binding"] == want_binding, "controlled-session call binding mismatch")
            self.revoke_context(sec)
            self.run_cli()
            revoked = next(r for r in self.receipts() if r.get("tool_call_id") == calls["after-revoke"]["id"])
            require(
                revoked["action"] == "deny" and revoked["reason_code"] == "skill_context_revoked",
                "revoked session SEC did not fail closed",
            )
            require(not failures and len(requests) == len(steps), "native model exchange incomplete: " + repr(failures))
            receipt_count = len(self.receipts())
            self.stop()
            verified = json.loads(self.command([str(self.binary), "verify"]))
            require(verified["verified"], "receipt chain verification failed")
            return {
                "schema_version": "personal-r01-sec-openclaw-native/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "native_cli_sha256": hashlib.sha256((self.args.openclaw_root / "openclaw.mjs").read_bytes()).hexdigest(),
                "openclaw_version": json.loads((self.args.openclaw_root / "package.json").read_text())["version"],
                "native_entrypoint": "public openclaw agent --local; real plugin hook and file tool lifecycle",
                "checks": [
                    "product_skill_import_install_and_activation",
                    "managed_adapter_uses_installation_bound_identity",
                    "native_session_enrolled_without_manual_intent",
                    "missing_sec_denied_before_file_read",
                    "admin_issues_controlled_session_sec",
                    "native_read_allowed_with_verified_attribution",
                    "controlled_session_call_binding_recomputed",
                    "revoked_sec_denied_in_same_native_session",
                    "installed_skill_present_in_native_catalog",
                    "receipt_chain_verified",
                ],
                "receipt_count": receipt_count,
                "skill_installation": self.skill_installation,
                "limitations": [
                    "OpenClaw exposes no trustworthy per-Skill tool-causality field; evidence level is controlled_session",
                    "native catalog discovery proves availability, not that one model tool call was caused by the Skill instructions",
                    "local deterministic model and automated fixture operator; no external or paid model",
                    "same-UID compromise and OS sandbox isolation remain outside the SEC threat boundary",
                ],
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def main():
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
    with tempfile.TemporaryDirectory(prefix="siq-openclaw-sec-native-") as temporary:
        harness = Harness(Path(temporary), args)
        harness.build()
        try:
            harness.start()
            harness.setup_authority()
            report = harness.native_sec()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"OpenClaw SEC native smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
