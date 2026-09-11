#!/usr/bin/env python3
"""Verify SIQ-installed Skill permissions with the public Hermes CLI in isolation.

Uses existing native conversation checks; no sibling internal code imports.
The selected permission envelope scopes the instance, not trusted Skill attribution.
"""

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "managed_fixture", REPO / "scripts/personal-experience/managed-instance-native-smoke.py"
)
managed = importlib.util.module_from_spec(loader)
loader.loader.exec_module(managed)
fixture = managed.fixture


class Harness(managed.Harness):
    def withdraw_runtime_authority(self):
        if not self.args.remove_installed_skill:
            return super().withdraw_runtime_authority()
        route = "/v1/skill-installations/operations/" + self.skill_installation["install_id"] + "/removal"
        view = self.api(route)
        fixture.require(view["status"] == "not_requested" and view["will_revoke_grant"], "wrong removal scope")
        identity_id = self.issued["identity"]["identity_id"]
        row = next(item for item in self.api("/v1/runtime-identities")["items"] if item["identity_id"] == identity_id)
        fixture.require(row["status"] == "issued", "identity already unavailable before removal")
        result = self.api(
            route,
            {
                "schema_version": "local-skill-install-remove/v1",
                "operation_signature": view["record"]["operation"]["signature"],
                "expected_grant_revision": view["state_revision"],
                "expected_binding_signature": view["binding_signature"],
                "actor_id": "automated-fixture-operator",
                "confirm_remove": True,
            },
        )
        fixture.require(result["status"] == "removed" and result["result"]["grant_revoked"], "removal incomplete")
        target = Path(self.env["HERMES_HOME"]) / "skills/intent-fixture"
        fixture.require(not target.exists(), "removed target retained")
        row = next(item for item in self.api("/v1/runtime-identities")["items"] if item["identity_id"] == identity_id)
        fixture.require(row["status"] == "grant_unavailable", "removed installation retained runtime authority")
        grant_id = self.issued["identity"]["grant_ref"]["grant_id"]
        current = self.api("/v1/grants/" + grant_id)
        fixture.require(current["grant"]["status"] == "revoked", "removal did not revoke Grant")
        fixture.require(current["grant"]["signature"] == result["result"]["grant_signature"], "wrong Grant evidence")
        return {
            "method": "explicit_installed_skill_removal",
            "check": "skill_removal_blocks_still_issued_identity_in_new_native_session",
            "identity_status_before": "issued",
            "identity_status_after": row["status"],
            "identity_revoke_endpoint_called": False,
            "removal_result": result["result"],
            "target_absent": True,
        }

    def setup_authority(self):
        catalog = self.api("/v1/adapter/instances?platform=hermes")
        target = next(row for row in catalog["instances"] if row["active"])
        self.instance_id = target["instance_id"]
        self.agent = "hri-" + self.instance_id[3:]
        skill = self.root / "fixture-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: intent-fixture\ndescription: Read a synthetic report.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\nRead the fixture report.\n"
        )
        imported = self.api(
            "/v1/skill-imports",
            {
                "schema_version": "local-skill-import-create/v1",
                "import_id": "si-" + "a" * 32,
                "source_kind": "local_dir",
                "path": str(skill),
                "actor_id": "automated-fixture-operator",
            },
            expected=201,
        )["import"]
        result = self.api(
            "/v1/skill-imports/" + imported["import_id"] + "/permissions",
            {
                "schema_version": "local-skill-import-permission-create/v1",
                "request_id": "ip-" + "b" * 32,
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
            **(
                {"network": [{"endpoint": host, "effect": "allow"} for host in self.network_endpoints]}
                if hasattr(self, "network_endpoints")
                else {}
            ),
            filesystem={
                "read_only": [str(self.workspace)],
                "read_write": [],
            },
        )
        for index, overlap in enumerate(result["grant"]["overlap_conflicts"]):
            if overlap["resolution"] == "unresolved":
                action("resolve-overlap", index=index)
        challenge = action("challenge")["challenge"]
        action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        fixture.require(result["grant"]["status"] == "approved", "grant approval did not transition")
        plan = self.api(
            "/v1/skill-installations/plans",
            {
                "schema_version": "local-skill-install-stage-create/v1",
                "request_id": "is-" + "c" * 32,
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
        fixture.require(installed["status"] == "installed_unverified", "Skill installation failed")
        activation = self.api(
            "/v1/skill-installations/operations/" + installed["install_id"] + "/activate",
            {
                "schema_version": "local-skill-install-activate/v1",
                "operation_signature": installed["operation"]["signature"],
                "expected_revision": result["state_revision"],
                "actor_id": "automated-fixture-operator",
                "confirm_instance_scope": True,
            },
        )
        result = self.api(grant_path)
        fixture.require(result["grant"]["status"] == "approved", "installed permission not prepared")
        fixture.require(activation["state_revision"] == result["state_revision"], "activation version mismatch")
        self.skill_installation = {
            "install_id": installed["install_id"],
            "binding_id": activation["binding"]["binding_id"],
            "source_digest": imported["artifact_digest"],
            "runtime_verified": False,
        }

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
        fixture.require(self.issued["identity"]["runtime_state"] == "unverified", "issuance claimed protection")
        profile = Path(self.env["HERMES_HOME"])
        before = (profile / "config.yaml").read_bytes()
        plugin_config = profile / "plugins/siq-agent-security/config.json"
        fixture.require(not plugin_config.exists(), "fixture preinstalled managed adapter")
        plan = self.api(
            "/v1/adapter/preview",
            {
                "platform": "hermes",
                "action": "install",
                "instance_id": self.instance_id,
                "runtime_identity_id": self.issued["identity"]["identity_id"],
                "native_enable": True,
            },
        )
        fixture.require(plan["schema_version"] == "local-adapter-plan/v3", "managed plan missing")
        fixture.require(
            (profile / "config.yaml").read_bytes() == before and not plugin_config.exists(), "preview mutated host"
        )
        self.api(
            "/v1/adapter/install",
            {
                "platform": "hermes",
                "instance_id": self.instance_id,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
                "runtime_identity_id": plan["runtime_identity_id"],
                "actor_id": "automated-fixture-operator",
            },
        )
        configured = json.loads(plugin_config.read_text())
        fixture.require(
            configured["runtime_identity_id"] == self.issued["identity"]["identity_id"]
            and configured["agent_id"] == self.agent
            and configured["token_path"] == self.issued["credential_path"],
            "installed identity mismatch",
        )
        fixture.require("fixture_setting: retain" in (profile / "config.yaml").read_text(), "host setting lost")
        fixture.require(
            (self.root / "hermes/config.yaml").read_text() == "fixture_default: unchanged\n", "other profile changed"
        )
        catalog = self.api("/v1/adapter/instances?platform=hermes")
        diagnosis = next(row["diagnosis"] for row in catalog["instances"] if row["instance_id"] == self.instance_id)
        fixture.require(diagnosis["runtime_state"] == "unverified", "installation claimed runtime verified")
        fixture.require(
            any(c["code"] == "instance_authority" and c["status"] == "pass" for c in diagnosis["checks"]),
            "managed authority diagnosis missing",
        )
        self.install_evidence = {
            "method": "managed_v3_preview_apply_and_public_cli_native_enable",
            "changed_file_count": len(plan["changes"]),
            "runtime_state": diagnosis["runtime_state"],
        }
        self.env["SIQ_AGENT_SECURITY_AGENT_ID"] = "forged-environment-agent"
        fixture.require(self.api("/v1/intents")["items"] == [], "manual intent created")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--remove-installed-skill", action="store_true", help="Withdraw via Skill removal, not identity revocation")
    parser.add_argument(
        "--legacy-binary", type=Path, help="Run only a read/auth compatibility probe on the copied state"
    )
    args = parser.parse_args()
    if args.remove_installed_skill and args.legacy_binary:
        parser.error("removal and legacy-reader probes are separate runs")
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.installer_managed_profile = True
    with tempfile.TemporaryDirectory(prefix="siq-installed-runtime-") as tmp:
        h = Harness(Path(tmp), args)
        shutil.copy2(args.binary, h.binary)
        try:
            h.start()
            h.setup_authority()
            if args.legacy_binary:
                legacy = args.legacy_binary.resolve()
                credential = Path(h.issued["credential_path"]).read_text().strip()
                h.stop()
                shutil.copy2(legacy, h.binary)
                h.start()
                row = next(
                    item
                    for item in h.api("/v1/runtime-identities")["items"]
                    if item["identity_id"] == h.issued["identity"]["identity_id"]
                )
                fixture.require(row["status"] == "grant_unavailable", "old daemon accepted new installed permission")
                h.api(
                    "/v1/runtime-sessions",
                    {"schema_version": "local-runtime-session-enroll/v1", "session_id": "legacy-must-not-enroll"},
                    token=credential,
                    expected=401,
                )
                fixture.require(not h.api("/v1/intents")["items"], "old daemon created runtime authority")
                result = {
                    "schema_version": "installed-permission-legacy-reader/v1",
                    "passed": True,
                    "candidate_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                    "legacy_sha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
                    "checks": [
                        "unrevoked_identity_grant_unavailable",
                        "old_enrollment_rejected",
                        "no_runtime_intent_created",
                    ],
                    "scope": (
                        "Previous M25 binary reads new approved-content binding in temporary state; "
                        "no host task execution. Not a universal state-format downgrade guard."
                    ),
                }
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({"passed": True, "checks": len(result["checks"])}))
                return
            result = h.public_cli()
            result["schema_version"] = "personal-installed-skill-runtime-native/v1"
            if args.remove_installed_skill:
                result["schema_version"] = "personal-installed-skill-removal-native/v1"
            result["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            result["skill_installation"] = h.skill_installation
            result["checks"].extend(
                ["product_skill_import_approval_installation", "installed_content_bound_instance_permission"]
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"passed": True, "checks": len(result["checks"])}))
        finally:
            h.stop()


if __name__ == "__main__":
    main()
