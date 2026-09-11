#!/usr/bin/env python3
"""Verify public Hermes inventory recognizes an SIQ-installed synthetic Skill.

No Skill scripts or model tasks execute. All writes use temporary profiles.
"""

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("daemon_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-install-management-") as temp:
        root = Path(temp)
        args.installer_managed_profile = True
        h = fixture.Harness(root, args)
        shutil.copy2(args.binary, h.binary)
        source = root / "skill"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: install-fixture\ndescription: Read a synthetic report.\n"
            "allowed-tools: read_file\n---\nRead a report.\n"
        )
        config = Path(h.env["HERMES_HOME"]) / "config.yaml"
        config_before = config.read_bytes()
        try:
            h.start()
            target = next(
                item
                for item in h.api("/v1/adapter/instances?platform=hermes")["instances"]
                if item["active"] and item["detected"]
            )
            imported = h.api(
                "/v1/skill-imports",
                {
                    "schema_version": "local-skill-import-create/v1",
                    "import_id": "si-" + "a" * 32,
                    "source_kind": "local_dir",
                    "path": str(source),
                    "actor_id": "fixture-human",
                },
                expected=201,
            )
            rec = imported["import"]
            prepared = h.api(
                "/v1/skill-imports/" + rec["import_id"] + "/permissions",
                {
                    "schema_version": "local-skill-import-permission-create/v1",
                    "request_id": "ip-" + "b" * 32,
                    "artifact_digest": rec["artifact_digest"],
                    "analysis_sha256": rec["analysis_sha256"],
                    "instance_id": target["instance_id"],
                    "actor_id": "fixture-human",
                },
                expected=201,
            )
            grant_id = prepared["grant"]["grant_id"]
            route = "/v1/grants/" + grant_id
            challenge = h.api(
                route + "/challenge",
                {
                    "expected_revision": 0,
                    "actor_id": "fixture-human",
                },
            )["challenge"]
            h.api(
                route + "/approve",
                {
                    "expected_revision": 0,
                    "actor_id": "fixture-human",
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                },
            )
            staged = h.api(
                "/v1/skill-installations/plans",
                {
                    "schema_version": "local-skill-install-stage-create/v1",
                    "request_id": "is-" + "c" * 32,
                    "grant_id": grant_id,
                    "expected_revision": 1,
                    "instance_id": target["instance_id"],
                    "directory_name": "install-fixture",
                    "actor_id": "fixture-human",
                },
                expected=201,
            )["plan"]
            result = h.api(
                "/v1/skill-installations/apply",
                {
                    "schema_version": "local-skill-install-apply/v1",
                    "plan_id": staged["plan_id"],
                    "plan_signature": staged["signature"],
                    "actor_id": "fixture-human",
                    "confirm_install": True,
                },
            )
            fixture.require(result["status"] == "installed_unverified", "installation failed")
            profile = Path(h.env["HERMES_HOME"])
            entry = profile / "skills/install-fixture/SKILL.md"
            fixture.require(entry.read_bytes() == (source / "SKILL.md").read_bytes(), "wrong installed contents")
            checks["product_installs_exact_candidate_into_named_profile"] = True
            commands = []
            for mode in ["all", "local"]:
                command = [str(args.hermes_cli), "skills", "list", "--source", mode, "--enabled-only"]
                output = subprocess.run(
                    command,
                    env={**h.env, "NO_COLOR": "1"},
                    cwd=h.workspace,
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
                (args.out_dir / ("skills-" + mode + ".txt")).write_text(output.stdout + output.stderr)
                commands.append(
                    {
                        "command": ["hermes", *command[1:]],
                        "exit_code": output.returncode,
                        "stdout_sha256": hashlib.sha256(output.stdout.encode()).hexdigest(),
                    }
                )
                fixture.require(output.returncode == 0, "public skills list failed")
                fixture.require("install-fixture" in output.stdout, "installed Skill absent from public inventory")
                checks["public_cli_" + mode + "_enabled_inventory_recognizes_skill"] = True
            readback = h.api("/v1/skill-installations/operations/" + result["install_id"])
            fixture.require(
                readback["operation"]["signature"] == result["operation"]["signature"], "host changed target"
            )
            fixture.require(config.read_bytes() == config_before, "host changed profile configuration")
            fixture.require(h.api(route)["grant"]["status"] == "approved", "inventory activated grant")
            fixture.require(not h.api("/v1/runtime-identities")["items"], "inventory issued runtime identity")
            checks["inventory_keeps_target_configuration_and_authority_unchanged"] = True
            payload = {
                "schema_version": "skill-install-hermes-recognition/v1",
                "generated_at": datetime.now(UTC).isoformat(),
                "status": "passed",
                "checks": checks,
                "commands": commands,
                "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "hermes_cli_sha256": hashlib.sha256(args.hermes_cli.read_bytes()).hexdigest(),
                "scope": (
                    "Real public Hermes skills list; synthetic SIQ-installed Skill and isolated profile. "
                    "No Skill script, model task or runtime protection verification."
                ),
            }
            (args.out_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"status": "passed", "checks": len(checks)}))
        finally:
            h.stop()


if __name__ == "__main__":
    main()
