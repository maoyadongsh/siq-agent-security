#!/usr/bin/env python3
"""Build the honest N09 matrix for one locally validated SIQ candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "docs/evidence/personal-experience/n09-current-candidate-20260915"

LEGS = (
    (
        "HC_SEC",
        "hermes",
        "linux",
        "docs/evidence/personal-experience/r01-sec-hermes-native-20260914/report.json",
    ),
    (
        "HC_RETRY",
        "hermes",
        "linux",
        "docs/evidence/personal-experience/r02-hermes-approved-retry-20260914/report.json",
    ),
    (
        "HC_UPDATE",
        "hermes",
        "linux",
        "docs/evidence/personal-experience/r04e-hermes-native-update-20260914/report.json",
    ),
    (
        "OC_SEC",
        "openclaw",
        "linux",
        "docs/evidence/personal-experience/r01-sec-openclaw-native-20260914/report.json",
    ),
    (
        "OC_RETRY",
        "openclaw",
        "linux",
        "docs/evidence/personal-experience/r02f-openclaw-approved-retry-20260915/report.json",
    ),
    (
        "OC_NOTIFY",
        "openclaw",
        "linux",
        "docs/evidence/personal-experience/r02g-linux-desktop-notify-20260915/report.json",
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


def hermes_linux_rows() -> list[dict]:
    return [
        row("J1", note="No clean product package installation was run in this batch."),
        row(
            "J2",
            entries=(coverage("HC_SEC", "two_skills_installed_for_same_agent"),),
            note="Two managed Skills were present in an isolated native profile; broad discovery remains open.",
        ),
        row(
            "J3",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "HC_UPDATE",
                    "v1_installed_activated_and_loaded_in_native_prompt",
                    "host_settings_and_other_profile_preserved",
                ),
            ),
            note="The selected Hermes profile loaded the managed Skill while unrelated settings were preserved.",
        ),
        row(
            "J4",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "HC_SEC",
                    "native_allowed_read_executes",
                    "native_write_denied_before_side_effect",
                    "new_native_task_cannot_copy_sec",
                ),
            ),
            note="A native read was allowed and a write was denied before effect; the broader tool matrix remains open.",
        ),
        row(
            "J5",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "HC_RETRY",
                    "hold_blocks_before_execution",
                    "approved_retry_reserved_before_native_execution",
                    "approved_native_side_effect_exactly_once",
                    "denied_retry_blocked_without_execution",
                    "reservation_and_observation_linked",
                ),
            ),
            note="Native approved and denied retries are linked to signed reservations; human and visual notification evidence remains open.",
        ),
        row(
            "J6",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "HC_UPDATE",
                    "pending_candidate_comparison_is_read_only",
                    "cancel_before_confirmation_preserves_v1_files_and_authority",
                    "explicit_update_replaces_bytes_and_revokes_v1_grant",
                    "explicit_v2_removal_revokes_authority_and_removes_target",
                ),
            ),
            note="The native local-source V1-to-V2 journey passed; production hosted source validation is blocked.",
        ),
        row(
            "J7",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "HC_SEC",
                    "verified_attribution_on_allow_and_deny",
                    "receipt_call_binding_recomputed",
                    "other_skill_cannot_borrow_runtime_identity",
                ),
            ),
            note="Hermes task-level host context binds the selected Skill to allow and deny receipts.",
        ),
        row("J8", note="This same-candidate Hermes batch did not stop the daemon during a native required call."),
        row("J9", note="No same-candidate Hermes daemon and native-session restart journey was run."),
        row(
            "J10",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "HC_UPDATE",
                    "explicit_v2_removal_revokes_authority_and_removes_target",
                    "host_settings_and_other_profile_preserved",
                    "test_observer_disabled_and_files_removed",
                ),
            ),
            note="The tested Skill and observer were removed safely; full product uninstall remains open.",
        ),
        row("J11", note="The complete raw-content and export lifecycle was not run in this native batch."),
    ]


def openclaw_linux_rows() -> list[dict]:
    return [
        row("J1", note="No clean product package installation was run in this batch."),
        row(
            "J2",
            entries=(
                coverage(
                    "OC_SEC",
                    "product_skill_import_install_and_activation",
                    "installed_skill_present_in_native_catalog",
                ),
            ),
            note="One managed Skill appeared in the native catalog; broad and nondefault discovery remains open.",
        ),
        row(
            "J3",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "OC_SEC",
                    "managed_adapter_uses_installation_bound_identity",
                    "native_session_enrolled_without_manual_intent",
                ),
            ),
            note="The managed adapter enrolled and controlled the selected native OpenClaw session.",
        ),
        row(
            "J4",
            status="controlled_start",
            classification="native_machine",
            entries=(
                coverage(
                    "OC_SEC",
                    "missing_sec_denied_before_file_read",
                    "native_read_allowed_with_verified_attribution",
                    "revoked_sec_denied_in_same_native_session",
                ),
            ),
            note="Session-level SEC allowed and denied native reads; OpenClaw lacks trusted single-Skill causal metadata.",
        ),
        row(
            "J5",
            status="controlled_start",
            classification="component_integration",
            entries=(
                coverage(
                    "OC_RETRY",
                    "approved_execution_has_one_reservation_and_observation",
                    "denial_missing_approval_and_offline_paths_fail_closed",
                    "revoked_authority_blocks_after_platform_approval",
                    "checkpoint_faults_and_parameter_changes_fail_closed",
                    "reservation_response_loss_stays_uncertain",
                ),
                coverage(
                    "OC_NOTIFY",
                    "notify_method_reached_real_session_bus",
                    "tool_action_receipt_and_params_not_exposed",
                ),
            ),
            note="Signed retry and Linux notification transport passed; the host patch, executor, and operator remain test fixtures.",
        ),
        row("J6", note="No same-candidate native OpenClaw Skill update/removal journey used a production source."),
        row(
            "J7",
            entries=(
                coverage(
                    "OC_SEC",
                    "native_read_allowed_with_verified_attribution",
                    "controlled_session_call_binding_recomputed",
                ),
            ),
            note="Session attribution is verified, but OpenClaw does not provide trusted single-Skill causality.",
        ),
        row(
            "J8",
            status="controlled_start",
            classification="component_integration",
            entries=(
                coverage(
                    "OC_RETRY",
                    "stock_host_refuses_unsupported_hold",
                    "denial_missing_approval_and_offline_paths_fail_closed",
                ),
            ),
            note="Unsupported and offline approval paths fail closed before the synthetic executor is called.",
        ),
        row("J9", note="Uncertain response handling passed, but a full service and native-session restart journey did not."),
        row("J10", note="No full product and native adapter uninstall journey was run on this candidate."),
        row("J11", note="The complete raw-content and export lifecycle was not run in this native batch."),
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
        "batch": "n09-current-candidate-20260915",
        "recorded_at": recorded_at,
        "legs": legs,
        "cells": cells,
        "evidence_sha256": evidence_sha256,
        "notes": [
            "All six legs use one locally built candidate binary; historical fe03e7e0 evidence is not carried forward.",
            "No row is classified complete_acceptance. controlled_start records only the native or component behavior named by its coverage checks.",
            "OpenClaw retry uses the real gateway and a pinned temporary checkpoint host, but the executor and operator are deterministic fixtures and the checkpoint is not upstream.",
            "Linux WorkBuddy, real hosted Git, macOS, Windows, visual notification confirmation, and clean package installation remain blocked or unverified.",
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
    report_md = f"""# N09 当前候选逐行证据矩阵

日期：2026-09-15。六条 Linux/Hermes、Linux/OpenClaw 证据腿均使用候选二进制
`{summary['candidate_binary_sha256']}`。矩阵保留 3 平台 × 3 系统 × J1–J11 的完整结构，
只把报告实际执行的检查登记为 coverage，没有任何一行标记为 `complete_acceptance`。

候选从 `apps/agentshield` 以 `go build -trimpath -o <temporary-output> ./cmd/agentshield`
构建；同一源码复建得到相同 SHA256。各旧 runner 只记录完成时间，因此矩阵保守地将该时间同时登记为
leg 起止时间，不据此推导执行时长。

Linux/Hermes 已形成可信 Skill 归属、批准后签名预留执行及本地来源 V1→V2 更新的原生阶段证据。
Linux/OpenClaw 已形成会话级 SEC、配套检查点下的签名预留和真实桌面会话总线通知证据；
OpenClaw 检查点、执行器和操作者的限制仍保留。WorkBuddy、生产公网 Git、完整产品安装/卸载、
通知视觉确认及 Windows/macOS 实机均未由本批覆盖。

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
