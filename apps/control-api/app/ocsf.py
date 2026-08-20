"""OCSF v1.1.0 事件映射（纯函数，无 I/O，便于单测）。

导出用途：SIEM 接入、工单联动、取证留存。
- Finding → Detection Finding（class_uid 2004，Findings 类别 2000）
- AuditEvent → API Activity（class_uid 6003，System Activity 类别 1000）

枚举决策（对照 ocsf-schema v1.1.0 源文件 events/findings/finding.json 等）：
- Finding.status_id 官方枚举只有 1 New / 2 In Progress / 3 Suppressed / 4 Resolved：
  open→1，acknowledged→2，risk_accepted→3（已评审并抑制：风险接受），resolved→4。
  注意：Resolved 是 4 而非 3；未知状态 → 99 (Other) + status 原文。
- API Activity.activity_id 枚举面向标准 HTTP/RPC 操作（Read/Create/Update/...），
  与控制面动作（finding.acknowledge、policy.deploy 等）不一一对应 → 一律 99 (Other)
  + activity_name 保留原始 action。
"""

from __future__ import annotations

from datetime import UTC, datetime

OCSF_VERSION = "1.1.0"

_SEVERITY_ID = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}

# Detection Finding status_id：1 New / 2 In Progress / 3 Suppressed / 4 Resolved
_FINDING_STATUS_ID = {
    "open": 1,
    "acknowledged": 2,
    "risk_accepted": 3,
    "resolved": 4,
}
_FINDING_STATUS_CAPTION = {1: "New", 2: "In Progress", 3: "Suppressed", 4: "Resolved"}

# API Activity disposition_id：1 Allowed / 2 Blocked
_DISPOSITION_ID = {"allow": 1, "deny": 2}
_DISPOSITION_CAPTION = {1: "Allowed", 2: "Blocked"}


def _epoch_ms(value: datetime) -> int:
    """数据库存的是 naive UTC（models.utcnow 去 tzinfo）；aware 输入先归一到 UTC。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def _metadata() -> dict:
    return {
        "product": {"name": "SIQ Agent Security", "vendor_name": "SIQ", "version": "0.1.0"},
        "version": OCSF_VERSION,
    }


def _confidence_score(value: float | None) -> int | None:
    """finding.confidence（域为 0.0–1.0）→ OCSF confidence_score（0–100 整数，越界 clamp）。"""
    if value is None:
        return None
    return max(0, min(100, int(round(value * 100))))


def finding_to_ocsf(finding) -> dict:
    """Finding → OCSF Detection Finding（class_uid 2004）。

    activity_id=1 (Create)：导出是当前状态的快照事件，不代表 Finding 生命周期动作。
    """
    activity_id = 1
    class_uid = 2004
    status_id = _FINDING_STATUS_ID.get(finding.status, 99)  # 未知状态 → Other，status 保留原文
    event = {
        "activity_id": activity_id,
        "activity_name": "Create",
        "category_uid": 2000,
        "category_name": "Findings",
        "class_uid": class_uid,
        "class_name": "Detection Finding",
        "type_uid": class_uid * 100 + activity_id,
        "time": _epoch_ms(finding.last_seen_at),
        "severity_id": _SEVERITY_ID.get(finding.severity, 0),  # 未知严重度 → 0 (Unknown)
        "severity": finding.severity,
        "status_id": status_id,
        "status": _FINDING_STATUS_CAPTION.get(status_id, finding.status),
        "finding_info": {
            "uid": finding.id,
            "title": finding.rule_id,
            "types": [finding.domain] if finding.domain else [],
        },
        "metadata": _metadata(),
    }
    confidence = _confidence_score(finding.confidence)
    if confidence is not None:
        event["confidence_score"] = confidence
    if finding.asset_id:
        event["resources"] = [{"uid": finding.asset_id, "type": "agent_asset"}]
    elif finding.resource_ref:
        # 非资产作用域资源（环境/凭据等）：resource_ref 是引用串而非稳定 uid，放 name
        event["resources"] = [{"name": finding.resource_ref}]
    if finding.impact:
        event["impact"] = finding.impact
    if finding.remediation:
        event["remediation"] = {"desc": finding.remediation}
    unmapped = {
        "rule_version": finding.rule_version,
        "evidence_ids": finding.evidence_ids,
        "analyzer_version": finding.analyzer_version,
        "owner_user_id": finding.owner_user_id,
    }
    event["unmapped"] = {k: v for k, v in unmapped.items() if v}
    return event


def audit_to_ocsf(event) -> dict:
    """AuditEvent → OCSF API Activity（class_uid 6003）。

    activity_id=99 (Other)：控制面动作与 OCSF activity 枚举不一一对应，
    原始动作保留在 activity_name / api.operation。
    """
    activity_id = 99
    class_uid = 6003
    disposition_id = _DISPOSITION_ID.get(event.decision, 0)  # 未知 → 0 (Unknown)
    resource = {"type": event.resource_type}
    if event.resource_id:
        resource["uid"] = event.resource_id
    return {
        "activity_id": activity_id,
        "activity_name": event.action,
        "category_uid": 1000,
        "category_name": "System Activity",
        "class_uid": class_uid,
        "class_name": "API Activity",
        "type_uid": class_uid * 100 + activity_id,
        "time": _epoch_ms(event.created_at),
        "actor": {"user": {"uid": event.actor_id, "type": event.actor_type}},
        "api": {"operation": event.action},
        "resources": [resource],
        "disposition_id": disposition_id,
        "disposition": _DISPOSITION_CAPTION.get(disposition_id, "Unknown"),
        "metadata": _metadata(),
        # summary 入库前已脱敏（outbox.audit 约定），导出原样透传，禁止二次加工
        "unmapped": {"summary": event.summary},
    }
