#!/usr/bin/env python3
"""Run a full SIQ Skill V1→V2 update through a real Hermes process.

The harness uses an isolated HOME/profile, the product's public management
APIs, ``hermes chat --oneshot``, real plugin hooks and the real file tool. A
local deterministic model fixture chooses the tool call; no external or paid
model is contacted. A test-only pre-LLM observer reports host-generated task
identity so the administrator can issue the required signed SEC.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "r01_native", REPO / "scripts/personal-experience/r01-sec-hermes-native-smoke.py"
)
r01 = importlib.util.module_from_spec(loader)
loader.loader.exec_module(r01)
fixture = r01.fixture


class Harness(r01.Harness):
    def setup_authority(self):
        # Use the shipping import→approval→install→activate→identity→adapter
        # path, without R01's second Skill fixture.
        r01.installed.Harness.setup_authority(self)
        self.current_install = self.skill_installation["install_id"]
        self.contexts = []

    def _candidate(self):
        source = self.root / "fixture-skill-v2"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: intent-fixture-v2\ndescription: Read the updated synthetic report.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\n"
            "UPDATED_VERSION_TWO_MARKER: read the fixture report.\n"
        )
        imported = self.api(
            "/v1/skill-imports",
            {
                "schema_version": "local-skill-import-create/v1",
                "import_id": "si-" + "d" * 32,
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
                "request_id": "ip-" + "e" * 32,
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
        return source, imported, route, result, action

    def _start_context_controller(self):
        failures = []
        subjects = []
        harness = self
        lock = threading.Lock()

        class Controller(BaseHTTPRequestHandler):
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
                    fixture.require(self.path == "/bind", "unexpected context controller route")
                    size = int(self.headers.get("Content-Length", "0"))
                    fixture.require(0 < size <= 2048, "context controller request budget")
                    body = json.loads(self.rfile.read(size))
                    fixture.require(set(body) == {"session_id", "task_id"}, "context identity fields changed")
                    subject = (body["session_id"], body["task_id"])
                    fixture.require(
                        all(isinstance(v, str) and 0 < len(v) <= 256 for v in subject),
                        "bad native identity",
                    )
                    with lock:
                        if subject not in subjects:
                            subjects.append(subject)
                            credential = Path(harness.issued["credential_path"]).read_text().strip()
                            harness.api(
                                "/v1/runtime-sessions",
                                {"schema_version": "local-runtime-session-enroll/v1", "session_id": subject[0]},
                                token=credential,
                            )
                            context = harness.api(
                                "/v1/skill-contexts",
                                harness._context_body(harness.current_install, subject[0], subject[1]),
                                expected=201,
                            )
                            harness.contexts.append(
                                {
                                    "install_id": harness.current_install,
                                    "context_id": context["context_id"],
                                    "session_id": subject[0],
                                    "task_id": subject[1],
                                }
                            )
                    self.respond(200, {"ready": True})
                except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
                    failures.append(type(exc).__name__ + ": " + str(exc)[:200])
                    self.respond(500, {"ready": False})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Controller)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.controller_failures = failures
        self._install_bootstrap_observer(f"http://127.0.0.1:{server.server_port}/bind")
        return server, thread, subjects, failures

    def _native_read(self, call_id, marker, skill_name):
        before = len(self.receipts())
        self._run_native(
            [
                {
                    "id": call_id,
                    "tool": self.read_tool,
                    "params": {"path": str(self.workspace / "company-a/report.txt")},
                    "outcome": "allow",
                }
            ],
            "Use the installed intent-fixture Skill and read the synthetic report.",
            expected_prompt_text=marker,
            skills=(skill_name,),
        )
        records = self.receipts()[before:]
        decisions = [
            row for row in records if row.get("record_type") == "decision" and row.get("tool_call_id") == call_id
        ]
        fixture.require(len(decisions) == 1 and decisions[0]["action"] == "allow", "native read was not allowed once")
        attribution = decisions[0].get("skill_attribution") or {}
        fixture.require(
            attribution.get("status") == "verified" and attribution.get("evidence_level") == "controlled_task",
            "native read lacks trusted Skill attribution",
        )
        return decisions[0]

    def update_and_run(self):
        target = Path(self.env["HERMES_HOME"]) / "skills/intent-fixture/SKILL.md"
        fixture.require(target.exists(), "V1 target missing")
        v1_bytes = target.read_bytes()
        server, thread, subjects, failures = self._start_context_controller()
        try:
            first = self._native_read("r04-v1-read", "intent-fixture", "intent-fixture")
            old_view = self.api("/v1/skill-installations/operations/" + self.current_install)
            old_grant_route = "/v1/grants/" + old_view["plan"]["grant_id"]
            old_identity = self.issued["identity"]["identity_id"]

            source, imported, candidate_route, candidate, action = self._candidate()
            pending_revision = candidate["state_revision"]
            compare_body = {
                "schema_version": "local-skill-update-compare/v1",
                "operation_signature": old_view["operation"]["signature"],
                "candidate_grant_id": candidate["grant"]["grant_id"],
                "expected_candidate_revision": pending_revision,
            }
            preview = self.api(
                f"/v1/skill-installations/operations/{self.current_install}/update-comparison", compare_body
            )
            fixture.require(
                preview["requires_confirmation"] and preview["content_changes_total"] > 0,
                "V2 diff missing",
            )
            fixture.require(target.read_bytes() == v1_bytes, "comparison changed V1 target")
            fixture.require(
                self.api(old_grant_route)["state_revision"] == old_view["plan"]["grant_revision"] + 1,
                "comparison changed V1 authority",
            )
            fixture.require(
                self.api(candidate_route)["state_revision"] == pending_revision,
                "comparison changed candidate authority",
            )

            challenge = action("challenge")["challenge"]
            candidate = action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
            compare_body["expected_candidate_revision"] = candidate["state_revision"]
            comparison = self.api(
                f"/v1/skill-installations/operations/{self.current_install}/update-comparison", compare_body
            )
            removal = self.api(f"/v1/skill-installations/operations/{self.current_install}/removal")
            fixture.require(removal["status"] == "not_requested", "V1 already removing")
            prepared = self.api(
                f"/v1/skill-installations/operations/{self.current_install}/update-plans",
                {
                    "schema_version": "local-skill-update-stage-create/v1",
                    "request_id": "up-" + "f" * 32,
                    "operation_signature": old_view["operation"]["signature"],
                    "candidate_grant_id": candidate["grant"]["grant_id"],
                    "expected_candidate_revision": candidate["state_revision"],
                    "expected_previous_revision": comparison["previous_revision"],
                    "expected_binding_signature": removal["binding_signature"],
                    "actor_id": "automated-fixture-operator",
                },
                expected=201,
            )["plan"]
            fixture.require(target.read_bytes() == v1_bytes, "prepared update changed V1 before confirmation")
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
            fixture.require(update["status"] == "updated_unverified", "V2 update did not finish")
            fixture.require(target.read_bytes() == (source / "SKILL.md").read_bytes(), "V2 target bytes mismatch")
            fixture.require(self.api(old_grant_route)["grant"]["status"] == "revoked", "V1 Grant stayed active")
            old_credential = Path(self.issued["credential_path"]).read_text().strip()
            stale_call = "r04-v1-stale-after-update"
            stale_request = {
                "platform": first["platform"],
                "session_id": first["session_id"],
                "agent_id": first["agent_id"],
                "task_id": first.get("task_id", ""),
                "runtime_task_id": first.get("runtime_task_id", ""),
                "tool": self.read_tool,
                "tool_call_id": stale_call,
                "params": {"path": str(self.workspace / "company-a/report.txt")},
                "skill": {
                    "skill_id": first["skill_attribution"]["skill_id"],
                    "content_hash": first["skill_attribution"]["content_hash"],
                    **(
                        {"version": first["skill_attribution"]["version"]}
                        if first["skill_attribution"].get("version") else {}
                    ),
                },
            }
            stale_before = len(self.receipts())
            stale_refusal = self.api(
                "/v1/decide", stale_request, token=old_credential, expected=401
            )
            stale_records = self.receipts()[stale_before:]
            fixture.require(
                (stale_refusal.get("reason_code") or stale_refusal.get("error")) == "unauthorized"
                and not stale_records
                and target.read_bytes() == (source / "SKILL.md").read_bytes(),
                "V1 scoped credential remained usable after confirmed V2 update",
            )
            old_row = next(
                row for row in self.api("/v1/runtime-identities")["items"] if row["identity_id"] == old_identity
            )
            fixture.require(old_row["status"] == "grant_unavailable", "V1 runtime identity stayed usable")
            revoked = self.api(
                f"/v1/runtime-identities/{old_identity}/revoke",
                {
                    "schema_version": "local-runtime-identity-revoke/v1",
                    "actor_id": "automated-fixture-operator",
                },
            )
            fixture.require(revoked["revoked"] is True, "V1 runtime identity was not explicitly retired")

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
            self.issued = self.api(
                "/v1/runtime-identities",
                {
                    "schema_version": "local-runtime-identity-create/v1",
                    "instance_id": self.instance_id,
                    "grant_id": candidate["grant"]["grant_id"],
                    "expected_grant_revision": activation["state_revision"],
                    "actor_id": "automated-fixture-operator",
                    "session_ttl_seconds": 28800,
                },
                expected=201,
            )
            adapter = self.api(
                "/v1/adapter/preview",
                {
                    "platform": "hermes",
                    "action": "install",
                    "instance_id": self.instance_id,
                    "runtime_identity_id": self.issued["identity"]["identity_id"],
                    "native_enable": True,
                },
            )
            self.api(
                "/v1/adapter/install",
                {
                    "platform": "hermes",
                    "instance_id": self.instance_id,
                    "plan_id": adapter["plan_id"],
                    "plan_digest": adapter["plan_digest"],
                    "runtime_identity_id": adapter["runtime_identity_id"],
                    "actor_id": "automated-fixture-operator",
                },
            )
            self.current_install = new_install
            second = self._native_read("r04-v2-read", "intent-fixture-v2", "intent-fixture-v2")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            try:
                self.command(
                    [str(self.args.hermes_cli), "plugins", "disable", "sec-bootstrap"],
                    cwd=self.workspace,
                    env=self.env,
                )
            finally:
                shutil.rmtree(Path(self.env["HERMES_HOME"]) / "plugins/sec-bootstrap", ignore_errors=True)

        fixture.require(
            not failures and len(subjects) == 2 and len(self.contexts) == 2,
            "native context sequence failed",
        )
        fixture.require(
            first["skill_attribution"]["content_hash"] != second["skill_attribution"]["content_hash"],
            "V2 attribution retained V1 content",
        )
        fixture.require(self.contexts[0]["install_id"] != self.contexts[1]["install_id"], "V2 reused V1 SEC")
        fixture.require(
            not (Path(self.env["HERMES_HOME"]) / "plugins/sec-bootstrap").exists(),
            "test observer files retained",
        )

        remove_route = f"/v1/skill-installations/operations/{self.current_install}/removal"
        remove_view = self.api(remove_route)
        removed = self.api(
            remove_route,
            {
                "schema_version": "local-skill-install-remove/v1",
                "operation_signature": remove_view["record"]["operation"]["signature"],
                "expected_grant_revision": remove_view["state_revision"],
                "expected_binding_signature": remove_view["binding_signature"],
                "actor_id": "automated-fixture-operator",
                "confirm_remove": True,
            },
        )
        fixture.require(removed["status"] == "removed" and removed["result"]["grant_revoked"], "V2 removal incomplete")
        fixture.require(not target.parent.exists(), "V2 target remained after removal")
        current_identity = self.issued["identity"]["identity_id"]
        current_row = next(
            row for row in self.api("/v1/runtime-identities")["items"] if row["identity_id"] == current_identity
        )
        fixture.require(current_row["status"] == "grant_unavailable", "V2 identity survived removal")
        fixture.require(
            "fixture_setting: retain" in (Path(self.env["HERMES_HOME"]) / "config.yaml").read_text(),
            "host setting lost",
        )
        fixture.require(
            (self.root / "hermes/config.yaml").read_text() == "fixture_default: unchanged\n",
            "other profile changed",
        )

        records = self.receipts()
        self.stop()
        chain = json.loads(self.command([str(self.binary), "verify"]))
        fixture.require(chain["verified"], "receipt chain invalid")
        return {
            "schema_version": "personal-r04-hermes-native-update/v2",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True,
            "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "native_cli_sha256": hashlib.sha256(self.args.hermes_cli.read_bytes()).hexdigest(),
            "native_entrypoint": "public hermes chat --oneshot with normal plugin hooks and file tool",
            "checks": [
                "v1_installed_activated_and_loaded_in_native_prompt",
                "v1_native_read_has_controlled_task_attribution",
                "pending_candidate_comparison_is_read_only",
                "cancel_before_confirmation_preserves_v1_files_and_authority",
                "approved_candidate_recomparison_and_signed_plan",
                "explicit_update_replaces_bytes_and_revokes_v1_grant",
                "v1_scoped_decision_credential_refused_after_v2_update_without_receipt_or_effect",
                "v1_runtime_identity_becomes_unavailable",
                "v1_runtime_identity_explicitly_retired_before_replacement",
                "v2_requires_new_activation_identity_and_sec",
                "v2_loaded_in_native_prompt_and_real_read_executes",
                "v2_attribution_binds_new_content_and_installation",
                "receipt_chain_verified",
                "explicit_v2_removal_revokes_authority_and_removes_target",
                "host_settings_and_other_profile_preserved",
                "test_observer_disabled_and_files_removed",
            ],
            "update_id": prepared["update_id"],
            "v1_install_id": old_view["install_id"],
            "v2_install_id": self.current_install,
            "v1_context_id": self.contexts[0]["context_id"],
            "v2_context_id": self.contexts[1]["context_id"],
            "v1_content_hash": first["skill_attribution"]["content_hash"],
            "v2_content_hash": second["skill_attribution"]["content_hash"],
            "stale_v1_http_refusal_reason_code": stale_refusal.get("reason_code") or stale_refusal["error"],
            "signed_receipt_count": len(records),
            "limitations": [
                "local deterministic model and synthetic operator; no external or paid model",
                "candidate V2 is an explicitly imported local directory; public-network scheduled fetch is separate",
                "test-only observer reports host session/task IDs and carries no SIQ credential or signing authority",
                "Linux/Hermes only; Windows, macOS, OpenClaw and WorkBuddy remain separate acceptance legs",
                "local state and an external side effect cannot provide a cross-system exactly-once transaction",
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
    args.raw_expiry_seconds = 0
    args.raw_dual_task = False
    with tempfile.TemporaryDirectory(prefix="siq-r04-native-update-") as tmp:
        harness = Harness(Path(tmp), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.update_and_run()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
