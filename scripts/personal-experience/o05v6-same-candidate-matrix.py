#!/usr/bin/env python3
"""Build the honest same-candidate N09 matrix for the local-o05-v6 batch.

Only reports whose binary_sha256 equals the frozen batch candidate may become
legs. Reports produced on a different binary (for example the Linux desktop
notification run) stay out of the matrix and are recorded in the notes instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = "docs/evidence/personal-experience/local-o05-v6-20260917-043146"
DEFAULT_OUT = ROOT / EVIDENCE_DIR

LEGS = (
    (
        "OC_B05",
        "openclaw",
        "linux",
        f"{EVIDENCE_DIR}/d07-20260916-204918/b05-service-down.json",
    ),
    (
        "HC_APPR",
        "hermes",
        "linux",
        f"{EVIDENCE_DIR}/d07-20260916-204918/hermes-approval-gap.json",
    ),
)

REQUIREMENTS = {
    "J1": "Clean product package installation, service start, pairing, and management UI evidence.",
    "J2": "Complete default and nondefault Agent/Skill discovery with instance relationships.",
    "J3": "Confirmed attachment to the selected native instance with unrelated settings preserved.",
    "J4": "Final-candidate native permission matrix covering relevant tools and zero denied effects.",
    "J5": "Human approval, visible notification, trusted native retry, replay, outage, and recovery evidence.",
    "J6": "Native install/update/removal using an enabled production remote source and permission review.",
    "J7": "Host-provided causal binding from one specific Skill to the actual native tool call.",
    "J8": "Native required call blocked before side effect while the SIQ service is unavailable.",
    "J9": "Service and native-session restart recovery with old authority constrained and no duplicate effect.",
    "J10": "Full product and adapter uninstall with authority revocation and user-data preservation.",
    "J11": "Redaction, explicit raw capture, expiry/revocation, and isolated export lifecycle evidence.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_report(ref: str) -> dict:
    report = json.loads((ROOT / ref).read_text())
    if report.get("passed") is not True:
        raise RuntimeError(f"report is not green: {ref}")
    if not isinstance(report.get("checks"), list) or not report["checks"]:
        raise RuntimeError(f"report has no explicit checks: {ref}")
    return report


def coverage(leg_id: str, *checks: str) -> dict:
    return {"leg_id": leg_id, "checks": list(checks)}


LEG_REFS = {leg_id: ref for leg_id, _, _, ref in LEGS}


def row(
    item: str,
    *,
    status: str = "unverified",
    classification: str = "component_integration",
    entries: tuple[dict, ...] = (),
    note: str,
) -> dict:
    refs = [LEG_REFS[entry["leg_id"]] for entry in entries]
    result = {
        "item": item,
        "status": status,
        "classification": classification,
        "evidence_refs": refs,
        "coverage": list(entries),
        "note": note,
    }
    if status == "unverified":
        result["required_evidence"] = REQUIREMENTS[item]
    return result


def blocked(item: str, reason: str, note: str) -> dict:
    return {
        "item": item,
        "status": "blocked",
        "classification": "static_check",
        "evidence_refs": [],
        "coverage": [],
        "note": note,
        "reason": reason,
        "required_evidence": REQUIREMENTS[item],
    }


def out_of_scope_linux_workbuddy(item: str) -> dict:
    return {
        "item": item,
        "status": "out_of_scope",
        "classification": "static_check",
        "evidence_refs": [],
        "coverage": [],
        "note": "2026-09-17 product scope: Linux supports Hermes and OpenClaw only; "
                "see docs/personal-platform-scope-decision-20260917.md.",
        "reason": "product_scope_excluded",
    }


def openclaw_linux_rows() -> list[dict]:
    return [
        row("J1", note="No clean product package installation was run in this batch."),
        row("J2", note="No same-candidate OpenClaw discovery journey was run in this batch."),
        row("J3", note="No same-candidate OpenClaw instance attachment journey was run in this batch."),
        row("J4", note="No same-candidate OpenClaw native permission matrix was run in this batch."),
        row(
            "J5",
            note=(
                "The Linux desktop notification leg passed its transport checks but used binary 029dc6f0, "
                "not this candidate; visual rendering is not observable on a headless host."
            ),
        ),
        row("J6", note="No same-candidate OpenClaw Skill update/removal journey used a production source."),
        row("J7", note="No same-candidate OpenClaw single-Skill causal attribution journey was run in this batch."),
        row(
            "J8",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "OC_B05",
                    "service_down_denies_file_write_before_execution",
                    "service_down_denies_read_without_content_leak",
                    "service_down_zero_loopback_egress_from_denied_exec",
                    "fail_closed_pending_lines_signed_false_recorded",
                    "managed_audit_only_override_still_fails_closed",
                    "unreachable_service_produced_no_authorized_receipts",
                ),
            ),
            note=(
                "Real OpenClaw 2026.5.12 native CLI: with the SIQ service down, file writes and reads are denied "
                "before effect, the audit-only override still fails closed, and denied exec produced zero loopback "
                "egress against a positive control. No authorized-egress allow path is claimed."
            ),
        ),
        row(
            "J9",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "OC_B05",
                    "same_port_restart_recovers_pairing",
                    "pending_lines_promoted_onto_signed_receipt_chain",
                    "promotion_cursor_matches_pending_lines",
                    "receipt_chain_verified_after_promotion",
                    "recovered_service_allows_authorized_read",
                ),
            ),
            note=(
                "SIQ service restart on the same port recovered pairing and promoted the four pending lines onto "
                "the signed receipt chain without re-executing them; a native host session restart and the "
                "no-duplicate-effect constraint were not exercised."
            ),
        ),
        row("J10", note="No same-candidate OpenClaw product uninstall journey was run in this batch."),
        row(
            "J11",
            note=(
                "Task-scoped raw-content export and retention were exercised at the control-api component level, "
                "not through a native OpenClaw host journey; the natural-expiry leg has no verdict yet."
            ),
        ),
    ]


def hermes_linux_rows() -> list[dict]:
    return [
        row("J1", note="No clean product package installation was run in this batch."),
        row("J2", note="No same-candidate Hermes discovery journey was run in this batch."),
        row("J3", note="No same-candidate Hermes instance attachment journey was run in this batch."),
        row("J4", note="No same-candidate Hermes native permission matrix was run in this batch."),
        row(
            "J5",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "HC_APPR",
                    "hold_blocks_before_execution",
                    "approved_retry_reserved_before_native_execution",
                    "approved_native_side_effect_exactly_once",
                    "denied_retry_blocked_without_execution",
                    "reservation_and_observation_linked",
                    "receipt_chain_verified",
                ),
            ),
            note=(
                "Real `hermes chat --oneshot`: both attempts were held before execution, the console approval "
                "produced exactly one local side effect and the console denial produced none, and the reservation "
                "is linked to the observation. At-most-once locally only; human clicking and visual notification "
                "remain separate and open."
            ),
        ),
        row("J6", note="No same-candidate Hermes Skill update/removal journey used a production source."),
        row("J7", note="No same-candidate Hermes single-Skill causal attribution journey was run in this batch."),
        row("J8", note="This batch did not stop the SIQ daemon during a required native Hermes call."),
        row("J9", note="No same-candidate Hermes daemon and native-session restart journey was run."),
        row("J10", note="No same-candidate Hermes product uninstall journey was run in this batch."),
        row(
            "J11",
            note=(
                "Task-scoped raw-content export and retention were exercised at the control-api component level, "
                "not through a native Hermes host journey; the natural-expiry leg has no verdict yet."
            ),
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    reports = {leg_id: read_report(ref) for leg_id, _, _, ref in LEGS}
    binaries = {report["binary_sha256"] for report in reports.values()}
    if len(binaries) != 1:
        raise RuntimeError("reports do not use one candidate binary")

    legs = []
    evidence_sha256 = {}
    for leg_id, platform_name, os_name, ref in LEGS:
        report = reports[leg_id]
        recorded_at = report["recorded_at"]
        report_hash = sha256(ROOT / ref)
        evidence_sha256[ref] = report_hash
        legs.append(
            {
                "leg_id": leg_id,
                "platform": platform_name,
                "os": os_name,
                "binary_sha256": report["binary_sha256"],
                "started_at": recorded_at,
                "finished_at": recorded_at,
                "report_ref": ref,
                "report_sha256": report_hash,
                "checks_passed": len(report["checks"]),
            }
        )

    cells = [
        {"platform": "hermes", "os": "linux", "rows": hermes_linux_rows()},
        {"platform": "openclaw", "os": "linux", "rows": openclaw_linux_rows()},
        {
            "platform": "workbuddy",
            "os": "linux",
            "rows": [out_of_scope_linux_workbuddy(item) for item in REQUIREMENTS],
        },
    ]
    for os_name in ("macos", "windows"):
        for platform_name in ("hermes", "openclaw", "workbuddy"):
            cells.append(
                {
                    "platform": platform_name,
                    "os": os_name,
                    "rows": [
                        blocked(
                            item,
                            "environment_unavailable",
                            f"{os_name} native evidence is owned by the external platform track.",
                        )
                        for item in REQUIREMENTS
                    ],
                }
            )

    recorded_at = datetime.now(UTC).isoformat()
    matrix = {
        "schema_version": "personal-acceptance-baseline/v2",
        "batch": "local-o05-v6-20260917",
        "recorded_at": recorded_at,
        "legs": legs,
        "cells": cells,
        "evidence_sha256": evidence_sha256,
        "notes": [
            "Both legs use one locally built candidate binary; leg timestamps are the reports' own recorded_at "
            "instants, matching the convention of the earlier generator.",
            "No row is classified complete_acceptance. controlled_start records only the native or component "
            "behavior named by its coverage checks.",
            "The Linux desktop notification report is not a leg: it was produced on binary 029dc6f0, not this "
            "candidate, and its visual rendering is not observable on a headless host.",
            "The control-api raw-content export report (192 checks) is component level with real daemon and HTTP "
            "but no native host capture, and the natural-expiry leg has no verdict yet; neither fills a matrix row.",
            "The r07 guard-route report has no checks list and is route navigation evidence only.",
            "Linux WorkBuddy is product-scope excluded, not passed; real hosted Git, macOS, Windows and clean "
            "package installation remain blocked or unverified.",
            "This matrix validates integrity and declared coverage; it does not close N09 or authorize T01-T06.",
        ],
    }
    summary = {
        "schema_version": "personal-acceptance-baseline-summary/v1",
        "recorded_at": recorded_at,
        "passed": True,
        "candidate_binary_sha256": binaries.pop(),
        "legs": [
            {
                "leg_id": leg["leg_id"],
                "passed": True,
                "report_sha256": leg["report_sha256"],
            }
            for leg in legs
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "matrix.json").write_text(json.dumps(matrix, indent=2) + "\n")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {args.out / 'matrix.json'} and {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
