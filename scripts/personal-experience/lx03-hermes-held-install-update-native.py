#!/usr/bin/env python3
"""Check a native Hermes held write across a real V1→V2 Skill update.

The fixture uses the shipping import/install/activate/identity/SEC chain and
the public Hermes CLI. A local deterministic model and operator are the only
synthetic participants. The V2 update is committed after a V1 hold is approved
but before Hermes retries the identical write. No external model is called.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "r04_hermes_native", REPO / "scripts/personal-experience/r04-hermes-native-update-smoke.py"
)
r04 = importlib.util.module_from_spec(loader)
loader.loader.exec_module(r04)
fixture = r04.fixture


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Harness(r04.Harness):
    def setup_authority(self):
        self.require_approval_tools = (self.write_tool,)
        self.narrow_read_write = self.workspace / "company-a"
        super().setup_authority()

    def _resolve_and_update(self, target: Path):
        decisions = [
            row for row in self.receipts()
            if row.get("record_type") == "decision" and row.get("tool_call_id") == "held-write-v1"
        ]
        fixture.require(len(decisions) == 1 and decisions[0]["action"] == "hold", "V1 native write did not hold")
        attribution = decisions[0].get("skill_attribution") or {}
        fixture.require(
            attribution.get("status") == "verified"
            and attribution.get("evidence_level") == "controlled_task",
            "V1 held write lacked installed Skill attribution",
        )
        fixture.require(not target.exists(), "V1 held write reached the file tool")
        pending = [
            item for item in self.api("/v1/confirmations")["items"]
            if item.get("tool_call_id") == "held-write-v1"
        ]
        fixture.require(
            len(pending) == 1 and pending[0]["status"] == "pending",
            "inbox count=" + str(len(pending)) + " statuses="
            + repr([item.get("status") for item in pending])
            + " reason=" + str(decisions[0].get("reason_code")),
        )
        item = pending[0]
        resolution = self.api(
            "/v1/confirmations/" + item["action_id"] + "/resolve",
            {
                "schema_version": "local-confirmation-resolve/v1",
                "decision_receipt_id": item["decision_receipt_id"],
                "decision_hash": item["decision_hash"],
                "params_digest": item["params_digest"],
                "approve": True,
                "actor_id": "fixture-console-reviewer",
            },
        )
        fixture.require(resolution["action"] == "allow", "V1 hold was not approved")

        old_view = self.api("/v1/skill-installations/operations/" + self.current_install)
        old_grant_route = "/v1/grants/" + old_view["plan"]["grant_id"]
        old_content = (
            Path(self.env["HERMES_HOME"]) / "skills/intent-fixture/SKILL.md"
        ).read_bytes()
        source, _imported, _candidate_route, candidate, action = self._candidate()
        compare_body = {
            "schema_version": "local-skill-update-compare/v1",
            "operation_signature": old_view["operation"]["signature"],
            "candidate_grant_id": candidate["grant"]["grant_id"],
            "expected_candidate_revision": candidate["state_revision"],
        }
        preview = self.api(
            f"/v1/skill-installations/operations/{self.current_install}/update-comparison", compare_body
        )
        fixture.require(preview["requires_confirmation"] and preview["content_changes_total"] > 0,
                        "V2 comparison did not disclose content change")
        challenge = action("challenge")["challenge"]
        candidate = action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        compare_body["expected_candidate_revision"] = candidate["state_revision"]
        comparison = self.api(
            f"/v1/skill-installations/operations/{self.current_install}/update-comparison", compare_body
        )
        removal = self.api(f"/v1/skill-installations/operations/{self.current_install}/removal")
        plan = self.api(
            f"/v1/skill-installations/operations/{self.current_install}/update-plans",
            {
                "schema_version": "local-skill-update-stage-create/v1",
                "request_id": "up-" + "9" * 32,
                "operation_signature": old_view["operation"]["signature"],
                "candidate_grant_id": candidate["grant"]["grant_id"],
                "expected_candidate_revision": candidate["state_revision"],
                "expected_previous_revision": comparison["previous_revision"],
                "expected_binding_signature": removal["binding_signature"],
                "actor_id": "fixture-console-reviewer",
            },
            expected=201,
        )["plan"]
        update = self.api(
            "/v1/skill-installations/updates",
            {
                "schema_version": "local-skill-update-commit/v1",
                "update_id": plan["update_id"],
                "plan_signature": plan["signature"],
                "actor_id": plan["actor_id"],
                "confirm_update": True,
            },
        )
        installed_file = Path(self.env["HERMES_HOME"]) / "skills/intent-fixture/SKILL.md"
        fixture.require(update["status"] == "updated_unverified", "V2 update did not commit")
        fixture.require(
            installed_file.read_bytes() == (source / "SKILL.md").read_bytes()
            and installed_file.read_bytes() != old_content,
            "V2 content digest did not replace V1",
        )
        fixture.require(self.api(old_grant_route)["grant"]["status"] == "revoked",
                        "V1 Grant survived V2 update")
        fixture.require(not target.exists(), "update itself created held write target")
        stale = [
            item for item in self.api("/v1/confirmations")["items"]
            if item.get("action_id") == pending[0]["action_id"]
        ]
        fixture.require(len(stale) == 1 and stale[0]["status"] == "unavailable",
                        "approved V1 hold stayed actionable after V2 update")
        self.held_update = {
            "v1_install_id": old_view["install_id"],
            "v2_install_id": update["installation"]["install_id"],
            "v1_content_sha256": hashlib.sha256(old_content).hexdigest(),
            "v2_content_sha256": digest(installed_file),
            "hold_decision_receipt_id": decisions[0]["receipt_id"],
        }

    def run_held_update(self):
        target = self.workspace / "company-a/held-update-target.txt"
        params = {"path": str(target), "content": "held-update-fixture-content"}
        calls = [
            {"id": "held-write-v1", "tool": self.write_tool, "params": params, "outcome": "deny"},
            {"id": "held-write-retry", "tool": self.write_tool, "params": params, "outcome": "deny"},
        ]
        controller, thread, subjects, failures = self._start_context_controller()

        def step(index):
            if index == 1:
                self._resolve_and_update(target)

        self._native_step_callback = step
        try:
            self._run_native(
                calls,
                "Use the installed intent-fixture Skill to write a synthetic report after approval.",
                expected_prompt_text="intent-fixture",
                skills=("intent-fixture",),
            )
        finally:
            self._native_step_callback = None
            controller.shutdown()
            controller.server_close()
            thread.join(timeout=2)
            try:
                self.command(
                    [str(self.args.hermes_cli), "plugins", "disable", "sec-bootstrap"],
                    cwd=self.workspace, env=self.env,
                )
            finally:
                shutil.rmtree(Path(self.env["HERMES_HOME"]) / "plugins/sec-bootstrap", ignore_errors=True)

        fixture.require(not failures and len(subjects) == 1 and len(self.contexts) == 1,
                        "native SEC controller did not bind one task")
        fixture.require(hasattr(self, "held_update"), "update did not run between hold and retry")
        fixture.require(not target.exists(), "old approved write executed after installation update")
        rows = self.receipts()
        resolutions = [
            row for row in rows
            if row.get("record_type") == "hold_resolution"
            and row.get("decision_receipt_id") == self.held_update["hold_decision_receipt_id"]
        ]
        fixture.require(len(resolutions) == 1 and resolutions[0]["action"] == "allow",
                        "approved V1 hold resolution missing")
        fixture.require(not any(row.get("record_type") in {"hold_reservation", "observation"}
                                for row in rows), "old hold was consumed or observed after update")
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        fixture.require(verified["verified"], "receipt chain invalid")
        return {
            "schema_version": "linux-lx03-hermes-held-install-update-native/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True,
            "binary_sha256": digest(self.binary),
            "driver_sha256": digest(Path(__file__)),
            "native_cli_sha256": digest(self.args.hermes_cli),
            "checks": [
                "v1_skill_installed_with_per_use_write_approval",
                "native_hermes_task_sec_issued_from_host_identity",
                "v1_native_write_held_without_file_effect",
                "console_resolution_approved_and_signed",
                "v2_content_diff_confirmed_and_update_committed_before_native_retry",
                "v1_grant_revoked_and_install_digest_changed",
                "approved_v1_confirmation_unavailable_after_update",
                "native_retry_of_same_write_blocked_without_file_effect",
                "approved_hold_not_reserved_or_observed_after_update",
                "receipt_chain_verified",
            ],
            "v1_install_id": self.held_update["v1_install_id"],
            "v2_install_id": self.held_update["v2_install_id"],
            "v1_content_sha256": self.held_update["v1_content_sha256"],
            "v2_content_sha256": self.held_update["v2_content_sha256"],
            "signed_receipt_count": len(rows),
            "limitations": [
                "the update revokes V1 Grant and runtime credential; native retry rejection is not attributed solely to install digest",
                "synthetic model and operator in isolated HOME; no external tool effect or human click",
                "one daemon and one Hermes CLI process; no cross-system exactly-once claim",
                "stock OpenClaw approval checkpoint is a separate unresolved capability",
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
    with tempfile.TemporaryDirectory(prefix="siq-lx03-held-install-update-") as tmp:
        harness = Harness(Path(tmp), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.run_held_update()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]) }))


if __name__ == "__main__":
    main()
