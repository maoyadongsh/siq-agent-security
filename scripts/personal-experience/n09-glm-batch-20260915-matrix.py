#!/usr/bin/env python3
"""Build the honest N09 matrix for the glm-linux r06/r04/r07 batch candidate.

Only legs with machine-readable reports enter the matrix. The R06 lifecycle
evidence (docs/evidence/personal-experience/r06-linux-lifecycle-20260915-161515/)
is real-machine markdown evidence without a structured checks list, so it is
cited in notes rather than asserted as validator-checked coverage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "docs/evidence/personal-experience/n09-glm-batch-20260915"

LEGS = (
    (
        "R04OC",
        "openclaw",
        "linux",
        "docs/evidence/personal-experience/r04-openclaw-native-update-20260915-171614/r04-openclaw-native-update.json",
    ),
    (
        "R07",
        "openclaw",
        "linux",
        "docs/evidence/personal-experience/r07-linux-user-journey-20260915-211053/r07-linux-user-journey.json",
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
    }


LEG_REFS = {leg_id: ref for leg_id, _, _, ref in LEGS}


def openclaw_linux_rows() -> list[dict]:
    return [
        row(
            "J1",
            status="controlled_start",
            entries=(
                coverage(
                    "R07",
                    "r07_step1_daemon_health_paired",
                    "r07_step2_ui_pairing_with_wrong_code_retry",
                ),
            ),
            note="Journey pairing (wrong-code retry) and daemon health passed; the clean install/upgrade/recovery lifecycle is real-machine markdown evidence in r06-linux-lifecycle-20260915-161515 (not a machine-readable leg), and clean package installation itself remains open.",
        ),
        row(
            "J2",
            status="controlled_start",
            entries=(coverage("R07", "r07_step2_ui_bindings_discovers_openclaw"),),
            note="The real OpenClaw instance was discovered in the bindings UI; broad and nondefault discovery remains open.",
        ),
        row(
            "J3",
            status="controlled_start",
            classification="native_machine",
            entries=(coverage("R07", "r07_step3_ui_grants_shows_v1_grant"),),
            note="Attachment to the native instance was confirmed through the grants UI with the managed skill installed.",
        ),
        row(
            "J4",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "R07",
                    "r07_step4_sec_issued_for_real_session",
                    "r07_step4_allow_read_with_session_attribution",
                    "r07_step4_call_binding_recomputed",
                    "r07_step4_attribution_correlates_grant_install_sec",
                ),
            ),
            note="Session-level SEC allowed a real host read with verified attribution; the broader tool matrix remains open (OpenClaw lacks trusted single-Skill causal metadata).",
        ),
        row(
            "J5",
            status="controlled_start",
            classification="component_integration",
            entries=(
                coverage(
                    "R07",
                    "r07_step6_hold_lands_in_siq_confirmations",
                    "r07_step6_ui_approval_records_confirmation",
                    "r07_step6_replayed_approval_rejected",
                ),
            ),
            note="HTTP hold creation, UI approval, and replay rejection passed; native consumption is not exercised; the operator is automated Playwright and desktop notification confirmation is covered only by the separate R02 smokes.",
        ),
        row(
            "J6",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage("R07", "r07_step7_update_leg_v1_cancel_confirm_v2_remove"),
                coverage(
                    "R04OC",
                    "up01_import_generates_check_data_only",
                    "comparison_is_read_only",
                    "up02_cancel_and_repeated_requests_keep_v1",
                    "update_replaces_target_bytes",
                    "update_revokes_v1_grant",
                    "removal_revokes_authority_and_removes_target",
                ),
            ),
            note="The full V1→cancel→confirm-update V2→re-authorize→removal journey passed as a nested leg inside the user journey; the source is local, so production hosted source validation remains blocked.",
        ),
        row(
            "J7",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "R07",
                    "r07_step4_call_binding_recomputed",
                    "r07_step4_attribution_correlates_grant_install_sec",
                ),
                coverage(
                    "R04OC",
                    "v1_call_binding_recomputed",
                    "v1_attribution_correlates_grant_install_sec",
                ),
            ),
            note="Call binding and grant/install/SEC correlation are verified at session level (controlled_session); single-Skill causality is not claimable on OpenClaw.",
        ),
        row(
            "J8",
            note="This batch did not block a native required call while the SIQ service was unavailable; R07 step 8 interrupts the service for UI-session recovery, not for a fail-closed native call.",
        ),
        row(
            "J9",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "R07",
                    "r07_step8_interrupt_invalidates_ui_session",
                    "r07_step8_retry_and_keyboard_repair",
                    "r07_step9_receipts_activities_render_after_recovery",
                ),
                coverage(
                    "R04OC",
                    "up08_commit_after_daemon_restart_from_recorded_plan",
                    "up09_old_context_cannot_authorize_new_version",
                ),
            ),
            note="Service interruption with UI-session recovery and post-restart commit with old-context refusal passed; a full native-session restart journey with duplicate-effect checks remains open.",
        ),
        row(
            "J10",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "R04OC",
                    "removal_revokes_authority_and_removes_target",
                    "unknown_user_files_preserved",
                    "host_config_final_state_preserved",
                ),
                coverage("R07", "r07_step11_adapter_uninstall_preserves_host_config"),
            ),
            note="Skill removal and adapter uninstall revoke authority and preserve unrelated host config and user files; full product uninstall remains open.",
        ),
        row(
            "J11",
            status="controlled_start",
            classification="component_integration",
            entries=(
                coverage(
                    "R07",
                    "r07_step10a_raw_content_store_default_disabled",
                    "r07_step10_raw_content_opt_in_ui_and_per_task_gating",
                    "r07_step10_purge_preserves_unexpired_records_and_receipts",
                    "r07_step10_native_capture_opt_in_and_revoke",
                    "r07_step10_default_export_excludes_raw_store",
                ),
            ),
            note="Store default-off, native task opt-in/revocation, unexpired ciphertext preservation and default export exclusion passed; elapsed-time expiry and task-specific export lifecycle remain open.",
        ),
    ]


def unverified_rows() -> list[dict]:
    return [row(item, note="No same-candidate leg was run for this cell in this batch.") for item in REQUIREMENTS]


def main() -> None:
    global LEGS, LEG_REFS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--r04-report", type=Path)
    parser.add_argument("--r07-report", type=Path)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise RuntimeError("refusing to overwrite existing evidence directory")
    if bool(args.r04_report) != bool(args.r07_report):
        raise RuntimeError("both same-candidate reports must be provided")
    if args.r04_report:
        LEGS = tuple((leg_id, platform, os_name, str(path.resolve().relative_to(ROOT)))
                     for (leg_id, platform, os_name, _), path in zip(LEGS, (args.r04_report, args.r07_report)))
        LEG_REFS = {leg_id: ref for leg_id, _, _, ref in LEGS}

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
        {"platform": "hermes", "os": "linux", "rows": unverified_rows()},
        {"platform": "openclaw", "os": "linux", "rows": openclaw_linux_rows()},
        {
            "platform": "workbuddy",
            "os": "linux",
            "rows": [
                blocked(item, "upstream_runtime_unconfirmed", "No Linux WorkBuddy runtime is installed or documented on this host.")
                for item in REQUIREMENTS
            ],
        },
    ]
    for os_name in ("macos", "windows"):
        for platform_name in ("hermes", "openclaw", "workbuddy"):
            cells.append(
                {
                    "platform": platform_name,
                    "os": os_name,
                    "rows": [
                        blocked(item, "environment_unavailable", f"{os_name} native evidence is owned by the external platform track.")
                        for item in REQUIREMENTS
                    ],
                }
            )

    recorded_at = datetime.now(UTC).isoformat()
    matrix = {
        "schema_version": "personal-acceptance-baseline/v2",
        "batch": args.out.name,
        "recorded_at": recorded_at,
        "legs": legs,
        "cells": cells,
        "evidence_sha256": evidence_sha256,
        "notes": [
            f"Both machine-readable legs use candidate {next(iter(binaries))}; earlier candidates are not carried into this matrix.",
            "R06 real-machine lifecycle evidence (docs/evidence/personal-experience/r06-linux-lifecycle-20260915-161515/) is markdown-only and therefore cited in notes, not asserted as validator-checked coverage.",
            "No row is classified complete_acceptance. controlled_start records only the native or component behavior named by its coverage checks.",
            "The browser operator is automated Playwright; desktop notification confirmation and the production hosted skill source remain outside this batch.",
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
        "release_acceptance": False,
        "complete_acceptance_rows": 0,
    }
    report_md = f"""# N09 glm-linux r06/r04/r07 批次逐行证据矩阵

日期：2026-09-15。两条机器可读证据腿（r04-openclaw-native-update {len(reports["R04OC"]["checks"])} 项、
r07-linux-user-journey {len(reports["R07"]["checks"])} 项（另含嵌套更新腿））均使用候选二进制
`{summary['candidate_binary_sha256']}`。矩阵保留 3 平台 × 3 系统 × J1–J11 的完整结构，
只把报告实际执行的检查登记为 coverage，没有任何一行标记为 `complete_acceptance`。

R06 原报告仅为历史材料，其全量生命周期通过声明已由独立复核撤回。
本次 systemd 保留状态重入证据见上级复核报告；不以此宣称正式安装包升级或安装实例串联旅程完成。

Hermes/linux 本批未跑新腿（全部 unverified 并列出 required_evidence）；
WorkBuddy/linux 与 macOS/Windows 各格保持 blocked。J8（服务不可用时的原生必要调用阻断）
本批未覆盖，如实记为 unverified。

校验器通过只说明文件完整性、同一候选约束和声明的逐行 coverage 有效，不能据此宣布 N09 或个人版完成，
也不能提前启动 T01–T06。
"""

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "matrix.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n")
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    (args.out / "report.md").write_text(report_md)
    sums = "".join(
        f"{sha256(args.out / name)}  {name}\n"
        for name in ("matrix.json", "summary.json", "report.md")
    )
    (args.out / "SHA256SUMS").write_text(sums)
    print(json.dumps({"passed": True, "candidate": summary["candidate_binary_sha256"], "legs": len(legs)}))


if __name__ == "__main__":
    main()
