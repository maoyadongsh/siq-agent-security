#!/usr/bin/env python3
"""Run a real daemon discovery scan inside a fully isolated temporary HOME.

Fixtures are two named Hermes profiles (each with config.yaml and a same-named
synthetic Skill of a different version) plus one OpenClaw state directory
(openclaw.json with one synthetic agent workspace and Skill). The candidate
daemon is driven through POST /v1/discovery/preview, POST /v1/discovery/scan
and the GET /v1/discovery, /v1/assets and /v1/inventory readbacks. Assertions
cover separate instance identity, per-instance Skill attribution, metadata-only
responses (Skill body and config sentinel strings must never surface) and
confinement to the isolated HOME. No model calls, real user configuration or
external services are touched.
"""

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("discovery_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)

PROFILES = ("fixture-alpha", "fixture-beta")
SKILL_NAME = "fixture-shared-skill"
SKILL_VERSIONS = {"fixture-alpha": "1.0.0", "fixture-beta": "2.0.0"}
OPENCLAW_AGENT = "fixture-openclaw-agent"
OPENCLAW_WORKSPACE = ".openclaw/workspaces/fixture-agent"
OPENCLAW_SKILL = "fixture-openclaw-skill"
OPENCLAW_SKILL_VERSION = "3.1.4"
PRIVATE_DIR = "private-fixture-notes"
DECOY_SKILL = "fixture-decoy-skill"

SENTINELS = {
    "skill_alpha_body": "SIQ-DISCOVERY-SENTINEL-ALPHA-9c51f0",
    "skill_beta_body": "SIQ-DISCOVERY-SENTINEL-BETA-3d27aa",
    "skill_openclaw_body": "SIQ-DISCOVERY-SENTINEL-OPENCLAW-64b8e1",
    "config_alpha": "SIQ-DISCOVERY-SENTINEL-CONFIG-ALPHA-1b2c3d",
    "config_beta": "SIQ-DISCOVERY-SENTINEL-CONFIG-BETA-4e5f60",
    "openclaw_config": "SIQ-DISCOVERY-SENTINEL-OCFG-77ab12",
    "private_notes": "SIQ-DISCOVERY-SENTINEL-PRIVATE-08f7e6",
    "decoy_skill_body": "SIQ-DISCOVERY-SENTINEL-DECOY-2a91c4",
}


def skill_md(name, version, sentinel):
    return (
        f"---\nname: {name}\ndescription: Synthetic discovery fixture skill.\nversion: {version}\n---\n"
        f"Fixture body text that must never become discovery metadata. {sentinel}\n"
    )


def iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from iter_strings(key)
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


class Harness(fixture.Harness):
    def build_isolated_home(self, real_home):
        self.real_home = real_home
        home = self.root / "home"
        home.mkdir(mode=0o700)
        self.env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "LOCALAPPDATA": str(home / "AppData/Local"),
                "HERMES_HOME": str(home / ".hermes"),
            }
        )
        for profile in PROFILES:
            suffix = profile.rsplit("-", 1)[1]
            base = home / ".hermes/profiles" / profile
            (base / "skills" / SKILL_NAME).mkdir(parents=True)
            (base / "config.yaml").write_text(f"model: fixture-model\n# {SENTINELS['config_' + suffix]}\n")
            (base / "skills" / SKILL_NAME / "SKILL.md").write_text(
                skill_md(SKILL_NAME, SKILL_VERSIONS[profile], SENTINELS["skill_" + suffix + "_body"])
            )
        openclaw = home / ".openclaw"
        skill_dir = openclaw / "workspaces/fixture-agent/skills" / OPENCLAW_SKILL
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            skill_md(OPENCLAW_SKILL, OPENCLAW_SKILL_VERSION, SENTINELS["skill_openclaw_body"])
        )
        (openclaw / "openclaw.json").write_text(
            json.dumps(
                {
                    "agents": {"list": [{"id": OPENCLAW_AGENT, "name": OPENCLAW_AGENT, "workspace": "~/" + OPENCLAW_WORKSPACE}]},
                    "fixture_note": SENTINELS["openclaw_config"],
                }
            )
        )
        private = home / PRIVATE_DIR
        private.mkdir()
        (private / "notes.txt").write_text("Unregistered private fixture. " + SENTINELS["private_notes"] + "\n")
        (private / "SKILL.md").write_text(skill_md(DECOY_SKILL, "9.9.9", SENTINELS["decoy_skill_body"]))

    def discovery_probe(self):
        checks = []
        responses = []

        def call(path, body=None, expected=200):
            payload = self.api(path, body, expected=expected)
            responses.append(payload)
            return payload

        preview = call("/v1/discovery/preview", {})
        fixture.require(preview["schema_version"] == "local-discovery-preview/v1", "preview schema changed")
        roots = {(row["path"], row["kind"]): row["status"] for row in preview["roots"]}
        expected_roots = (
            {("~/.hermes/profiles/" + p, "profile_directory") for p in PROFILES}
            | {("~/.hermes/profiles/" + p + "/skills", "skill_directory") for p in PROFILES}
            | {
                ("~/.openclaw/openclaw.json", "platform_config"),
                ("~/" + OPENCLAW_WORKSPACE + "/skills", "skill_directory"),
            }
        )
        missing = sorted(key for key in expected_roots if roots.get(key) != "available")
        fixture.require(not missing, "preview roots missing: " + repr(missing))
        fixture.require(
            all(row["path"].startswith("~") for row in preview["roots"]), "preview leaked an unredacted path"
        )
        checks.append("preview_roots_match_isolated_layout")

        started = call("/v1/discovery/scan", {}, expected=202)
        fixture.require(started["run"]["state"] == "running", "scan did not start asynchronously")
        run = started["run"]
        deadline = time.monotonic() + 30
        while run["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            run = call("/v1/discovery")["run"]
        fixture.require(run["state"] != "running", "discovery scan did not finish")
        fixture.require(run["state"] == "succeeded", "scan state: " + run["state"] + " " + run.get("error", ""))
        fixture.require(run["issue_count"] == 0, "scan reported unreadable fixture paths")
        fixture.require(run["skill_count"] == 3 and run["asset_count"] == 7, "unexpected scan counts")
        checks.append("discovery_scan_async_lifecycle_succeeded")

        assets = call("/v1/assets")["assets"]
        report = call("/v1/inventory")
        details = [call("/v1/assets/" + row["id"]) for row in assets if row["source_type"] == "skill_dir"]

        instances = {row["name"]: row for row in assets if row["source_type"] == "hermes_profile"}
        fixture.require(set(instances) == set(PROFILES), "named hermes instances not discovered separately")
        alpha, beta = instances["fixture-alpha"], instances["fixture-beta"]
        fixture.require(alpha["id"] != beta["id"], "instance candidate identities merged")
        fixture.require(
            alpha["attributes"]["instance_id"] != beta["attributes"]["instance_id"],
            "instance_id attribute merged",
        )
        checks.append("named_hermes_instances_discovered_with_separate_identities")

        shared = [row for row in assets if row["source_type"] == "skill_dir" and row["name"] == SKILL_NAME]
        fixture.require(len(shared) == 2, "same-name skills merged or missed")
        by_profile = {}
        for row in shared:
            owner = next((p for p in PROFILES if "/profiles/" + p + "/" in row["source_locator"]), None)
            fixture.require(owner is not None, "skill locator outside fixture profiles")
            by_profile[owner] = row
        fixture.require(set(by_profile) == set(PROFILES), "skill missing for one profile")
        fixture.require(
            by_profile["fixture-alpha"]["id"] != by_profile["fixture-beta"]["id"],
            "skill installation identity merged",
        )
        fixture.require(
            by_profile["fixture-alpha"]["content_hash"] != by_profile["fixture-beta"]["content_hash"],
            "different skill versions merged into one digest",
        )
        for profile, row in by_profile.items():
            owners = {rel["source_id"] for rel in row.get("relationships", [])}
            fixture.require(owners == {"agent:hermes:" + profile}, "skill relationship leaked across instances")
        checks.append("same_name_skill_versions_discovered_as_separate_installations")
        checks.append("skills_attributed_to_owning_instance")

        fixture.require(
            any(row["source_type"] == "platform_config" and row["name"] == "openclaw" for row in assets),
            "openclaw platform config missing",
        )
        agent = next((row for row in assets if row["source_type"] == "openclaw_agent"), None)
        fixture.require(agent is not None and agent["name"] == OPENCLAW_AGENT, "openclaw agent not discovered")
        oc_skill = next(
            (row for row in assets if row["source_type"] == "skill_dir" and row["name"] == OPENCLAW_SKILL), None
        )
        fixture.require(oc_skill is not None and oc_skill["framework"] == "openclaw", "openclaw skill missing")
        owners = {rel["source_id"] for rel in oc_skill.get("relationships", [])}
        fixture.require(owners == {"agent:openclaw:" + OPENCLAW_AGENT}, "openclaw skill owner wrong")
        checks.append("openclaw_state_agent_and_workspace_skill_discovered")

        candidate_names = {(c["source_type"], c["name"]) for c in report["candidates"]}
        asset_names = {(row["source_type"], row["name"]) for row in assets}
        fixture.require(asset_names <= candidate_names, "ledger assets disagree with inventory readback")
        fixture.require(set(report["platforms"]) == {"hermes", "openclaw"}, "unexpected platforms discovered")
        fixture.require(report["home"] == "~", "inventory home not redacted")
        checks.append("inventory_readback_agrees_with_ledger_projection")

        serialized = json.dumps(responses, ensure_ascii=False)
        leaked = sorted(name for name, sentinel in SENTINELS.items() if sentinel in serialized)
        fixture.require(not leaked, "fixture content surfaced in discovery responses: " + ",".join(leaked))
        checks.append("skill_bodies_and_config_content_never_serialized")
        fixture.require(
            DECOY_SKILL not in serialized and PRIVATE_DIR not in serialized,
            "unregistered private directory surfaced in discovery responses",
        )
        checks.append("unregistered_private_directory_not_discovered")
        fixture.require(self.real_home not in serialized, "real user home path leaked")
        fixture.require(str(self.root) not in serialized, "unredacted temporary path leaked")
        absolutes = sorted({s for s in iter_strings(responses) if s.startswith("/")})
        fixture.require(not absolutes, "absolute paths in discovery responses: " + repr(absolutes[:3]))
        checks.append("responses_confined_to_redacted_isolated_home")

        observed_instances = [
            {
                "candidate_id": row["id"],
                "name": row["name"],
                "framework": row["framework"],
                "source_type": row["source_type"],
                "instance_id": row.get("attributes", {}).get("instance_id"),
                "config_dir": row.get("attributes", {}).get("config_dir"),
            }
            for row in assets
            if row["source_type"] in ("hermes_profile", "openclaw_agent", "platform_config")
        ]

        def declared_version(locator):
            for profile in PROFILES:
                if "/profiles/" + profile + "/" in locator:
                    return SKILL_VERSIONS[profile]
            return OPENCLAW_SKILL_VERSION

        observed_skills = [
            {
                "candidate_id": row["id"],
                "name": row["name"],
                "framework": row["framework"],
                "source_locator": row["source_locator"],
                "content_hash": row.get("content_hash"),
                "identity_version": row.get("attributes", {}).get("identity_version"),
                "declared_version_in_fixture": declared_version(row["source_locator"]),
                "related_instances": sorted({rel["source_id"] for rel in row.get("relationships", [])}),
            }
            for row in assets
            if row["source_type"] == "skill_dir"
        ]
        return {
            "schema_version": "personal-discovery-native-smoke/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True,
            "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "checks": checks,
            "discovery_run": {
                key: run.get(key) for key in ("run_id", "state", "asset_count", "skill_count", "issue_count")
            },
            "preview_root_count": len(preview["roots"]),
            "observed_platforms": report["platforms"],
            "observed_instances": observed_instances,
            "observed_skills": observed_skills,
            "fixture": {
                "hermes_profiles": [
                    {"name": p, "skill_name": SKILL_NAME, "skill_version": SKILL_VERSIONS[p]} for p in PROFILES
                ],
                "openclaw": {
                    "agent": OPENCLAW_AGENT,
                    "skill_name": OPENCLAW_SKILL,
                    "skill_version": OPENCLAW_SKILL_VERSION,
                },
            },
            "sentinel_leak_check": {"sentinel_count": len(SENTINELS), "leaked": leaked},
            "skill_detail_readbacks": len(details),
            "limitations": [
                "synthetic profiles, Skills and operator in a temporary HOME; no real user configuration was read",
                "discovery metadata only; no runtime execution, admission, grant or approval journey is claimed",
                "path confinement is asserted from redacted API responses, not from syscall tracing",
                "single Linux host; no cross-OS or other-platform discovery claim",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.binary, args.out = args.binary.resolve(), args.out.resolve()
    real_home = str(Path.home())
    with tempfile.TemporaryDirectory(prefix="siq-discovery-native-") as temporary:
        root = Path(temporary)
        harness = Harness(root, args)
        harness.build_isolated_home(real_home)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            report = harness.discovery_probe()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        # Assertion messages carry only synthetic fixture names and temp paths.
        print(f"discovery native smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
