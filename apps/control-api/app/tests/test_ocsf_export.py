"""OCSF 导出测试：映射纯函数单测 + 端点（租户隔离/权限/过滤/审计断言）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, Finding, Tenant
from app.ocsf import audit_to_ocsf, finding_to_ocsf

T0 = datetime(2024, 1, 1, 0, 0, 0)  # naive UTC → 1704067200000
T1 = datetime(2024, 6, 1, 12, 0, 0)
T2 = datetime(2025, 1, 1, 0, 0, 0)

AUDITOR_A = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "auditor-a", "X-Dev-Roles": "auditor"}
AUDITOR_B = {"X-Dev-Tenant-Id": "tnt-B", "X-Dev-User-Id": "auditor-b", "X-Dev-Roles": "auditor"}


def _finding(**overrides) -> Finding:
    """纯内存 Finding（不落库），显式给时间字段（default 只在 flush 时生效）。"""
    base = {
        "id": "fnd_unit",
        "tenant_id": "tnt-unit",
        "rule_id": "rule-x",
        "rule_version": 2,
        "severity": "high",
        "domain": "threat",
        "asset_id": "agt_1",
        "resource_ref": None,
        "evidence_ids": ["ev-1"],
        "impact": "may exfiltrate",
        "remediation": "rotate key",
        "status": "open",
        "owner_user_id": "user-x",
        "analyzer_version": "threat/0.1.0",
        "confidence": 0.85,
        "first_seen_at": T0,
        "last_seen_at": T1,
    }
    return Finding(**{**base, **overrides})


def _event(**overrides) -> AuditEvent:
    base = {
        "id": "aud_unit",
        "tenant_id": "tnt-unit",
        "actor_type": "user",
        "actor_id": "user-x",
        "action": "finding.acknowledge",
        "resource_type": "finding",
        "resource_id": "fnd_1",
        "decision": "allow",
        "request_id": "req-1",
        "summary": {"finding_id": "fnd_1"},
        "created_at": T1,
    }
    return AuditEvent(**{**base, **overrides})


# ---- 映射纯函数 ----


def test_finding_severity_mapping():
    expected = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
    for severity, severity_id in expected.items():
        event = finding_to_ocsf(_finding(severity=severity))
        assert event["severity_id"] == severity_id
        assert event["severity"] == severity


def test_finding_status_mapping():
    # OCSF v1.1.0 Finding.status_id：1 New / 2 In Progress / 3 Suppressed / 4 Resolved
    expected = {"open": 1, "acknowledged": 2, "risk_accepted": 3, "resolved": 4}
    for status, status_id in expected.items():
        assert finding_to_ocsf(_finding(status=status))["status_id"] == status_id
    # 未知状态 → 99 (Other)，status 保留原文
    unknown = finding_to_ocsf(_finding(status="weird_state"))
    assert unknown["status_id"] == 99
    assert unknown["status"] == "weird_state"


def test_finding_time_is_epoch_ms():
    event = finding_to_ocsf(_finding(last_seen_at=T0))
    assert event["time"] == 1704067200000
    aware = finding_to_ocsf(_finding(last_seen_at=datetime(2024, 1, 1, tzinfo=UTC)))
    assert aware["time"] == 1704067200000


def test_finding_confidence_score():
    assert finding_to_ocsf(_finding(confidence=0.85))["confidence_score"] == 85
    assert finding_to_ocsf(_finding(confidence=0.0))["confidence_score"] == 0
    assert finding_to_ocsf(_finding(confidence=1.5))["confidence_score"] == 100  # clamp
    assert "confidence_score" not in finding_to_ocsf(_finding(confidence=None))


def test_finding_structure_and_metadata():
    event = finding_to_ocsf(_finding())
    assert event["class_uid"] == 2004
    assert event["class_name"] == "Detection Finding"
    assert event["category_uid"] == 2000
    assert event["category_name"] == "Findings"
    assert event["activity_id"] == 1  # 导出快照语义
    assert event["type_uid"] == 200401
    assert event["finding_info"] == {"uid": "fnd_unit", "title": "rule-x", "types": ["threat"]}
    assert event["resources"] == [{"uid": "agt_1", "type": "agent_asset"}]
    assert event["impact"] == "may exfiltrate"
    assert event["remediation"] == {"desc": "rotate key"}
    assert event["metadata"] == {
        "product": {"name": "SIQ Agent Security", "vendor_name": "SIQ", "version": "0.1.0"},
        "version": "1.1.0",
    }
    assert event["unmapped"]["evidence_ids"] == ["ev-1"]
    assert event["unmapped"]["analyzer_version"] == "threat/0.1.0"
    assert event["unmapped"]["rule_version"] == 2


def test_finding_resource_fallback():
    # 无 asset：resource_ref 放 name 而非 uid
    event = finding_to_ocsf(_finding(asset_id=None, resource_ref="env:prod"))
    assert event["resources"] == [{"name": "env:prod"}]
    # 两者皆无：省略 resources
    assert "resources" not in finding_to_ocsf(_finding(asset_id=None, resource_ref=None))


def test_audit_event_mapping():
    event = audit_to_ocsf(_event())
    assert event["class_uid"] == 6003
    assert event["class_name"] == "API Activity"
    assert event["category_uid"] == 1000
    assert event["category_name"] == "System Activity"
    assert event["activity_id"] == 99  # 控制面动作与 OCSF activity 枚举不一一对应
    assert event["activity_name"] == "finding.acknowledge"
    assert event["type_uid"] == 600399
    assert event["time"] == int(T1.replace(tzinfo=UTC).timestamp() * 1000)
    assert event["actor"] == {"user": {"uid": "user-x", "type": "user"}}
    assert event["api"] == {"operation": "finding.acknowledge"}
    assert event["resources"] == [{"type": "finding", "uid": "fnd_1"}]
    assert event["disposition_id"] == 1
    assert event["disposition"] == "Allowed"
    assert event["metadata"]["version"] == "1.1.0"
    # summary 已脱敏，原样透传
    assert event["unmapped"] == {"summary": {"finding_id": "fnd_1"}}


def test_audit_disposition_deny():
    event = audit_to_ocsf(_event(decision="deny"))
    assert event["disposition_id"] == 2
    assert event["disposition"] == "Blocked"


# ---- 端点 ----


def _ensure_tenant(session, tenant_id: str) -> None:
    if session.get(Tenant, tenant_id) is None:
        session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))


def _seed_finding(tenant_id: str, rule_id: str, *, last_seen_at: datetime, **overrides) -> str:
    with session_scope() as session:
        _ensure_tenant(session, tenant_id)
        params = {
            "tenant_id": tenant_id,
            "rule_id": rule_id,
            "rule_version": 1,
            "severity": "medium",
            "status": "open",
            "first_seen_at": last_seen_at,
            "last_seen_at": last_seen_at,
            **overrides,
        }
        finding = Finding(**params)
        session.add(finding)
        session.commit()
        return finding.id


def _seed_audit_event(tenant_id: str, action: str, *, created_at: datetime) -> str:
    with session_scope() as session:
        _ensure_tenant(session, tenant_id)
        event = AuditEvent(
            tenant_id=tenant_id,
            actor_type="user",
            actor_id="user-seed",
            action=action,
            resource_type="finding",
            resource_id="fnd_seed",
            decision="allow",
            summary={"k": "v"},
            created_at=created_at,
        )
        session.add(event)
        session.commit()
        return event.id


def _ndjson(resp) -> list[dict]:
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_export_detection_findings_ndjson(client):
    fid = _seed_finding("tnt-A", "ocsf-export-a1", last_seen_at=T1, severity="critical")
    resp = client.get("/api/v1/export/ocsf?class=detection_finding", headers=AUDITOR_A)
    assert resp.status_code == 200, resp.text
    events = _ndjson(resp)
    assert events, "导出为空"
    assert all(e["class_uid"] == 2004 for e in events)  # 每行可解析且类正确
    times = [e["time"] for e in events]
    assert times == sorted(times)  # 时间正序
    ours = next(e for e in events if e["finding_info"]["uid"] == fid)
    assert ours["severity_id"] == 5
    assert ours["finding_info"]["title"] == "ocsf-export-a1"


def test_export_api_activity_ndjson(client):
    eid = _seed_audit_event("tnt-A", "ocsf.seed.action", created_at=T1)
    resp = client.get("/api/v1/export/ocsf?class=api_activity", headers=AUDITOR_A)
    assert resp.status_code == 200, resp.text
    events = _ndjson(resp)
    assert all(e["class_uid"] == 6003 for e in events)
    ours = next(e for e in events if e["activity_name"] == "ocsf.seed.action")
    assert ours["resources"] == [{"type": "finding", "uid": "fnd_seed"}]
    assert ours["disposition_id"] == 1
    assert eid  # seeded


def test_export_tenant_isolation(client):
    fid_a = _seed_finding("tnt-A", "ocsf-iso-a", last_seen_at=T1)
    fid_b = _seed_finding("tnt-B", "ocsf-iso-b", last_seen_at=T1)
    resp_b = client.get("/api/v1/export/ocsf?class=detection_finding", headers=AUDITOR_B)
    uids_b = {e["finding_info"]["uid"] for e in _ndjson(resp_b)}
    assert fid_b in uids_b
    assert fid_a not in uids_b  # B 看不到 A 的 Finding
    resp_a_audit = client.get("/api/v1/export/ocsf?class=api_activity", headers=AUDITOR_B)
    actors_b = {e["actor"]["user"]["uid"] for e in _ndjson(resp_a_audit)}
    assert "auditor-a" not in actors_b


def test_export_requires_audit_read(client, tenant_a):
    # tenant_a 角色不含 auditor → 无 audit:read → 403
    resp = client.get("/api/v1/export/ocsf?class=detection_finding", headers=tenant_a)
    assert resp.status_code == 403


def test_export_invalid_class_422(client):
    resp = client.get("/api/v1/export/ocsf?class=nope", headers=AUDITOR_A)
    assert resp.status_code == 422
    resp2 = client.get("/api/v1/export/ocsf", headers=AUDITOR_A)
    assert resp2.status_code == 422


def test_export_since_filter(client):
    old_id = _seed_finding("tnt-A", "ocsf-since-old", last_seen_at=T0)
    new_id = _seed_finding("tnt-A", "ocsf-since-new", last_seen_at=T2)
    resp = client.get(
        "/api/v1/export/ocsf?class=detection_finding&since=2024-06-01T00:00:00Z",
        headers=AUDITOR_A,
    )
    uids = {e["finding_info"]["uid"] for e in _ndjson(resp)}
    assert new_id in uids
    assert old_id not in uids
    # 非法 since → 422
    resp_bad = client.get(
        "/api/v1/export/ocsf?class=detection_finding&since=not-a-date", headers=AUDITOR_A
    )
    assert resp_bad.status_code == 422


def test_export_limit(client):
    for i in range(3):
        _seed_audit_event("tnt-B", f"ocsf.limit.{i}", created_at=datetime(2024, 3, 1, i))
    resp = client.get("/api/v1/export/ocsf?class=api_activity&limit=2", headers=AUDITOR_B)
    assert resp.status_code == 200
    assert len(_ndjson(resp)) == 2
    # 超过上限 2000 → 422
    resp_over = client.get("/api/v1/export/ocsf?class=api_activity&limit=2001", headers=AUDITOR_B)
    assert resp_over.status_code == 422


def test_export_writes_audit(client):
    _seed_finding("tnt-A", "ocsf-audit-trail", last_seen_at=T1)
    resp = client.get(
        "/api/v1/export/ocsf?class=detection_finding&since=2024-01-01T00:00:00Z",
        headers=AUDITOR_A,
    )
    assert resp.status_code == 200
    with session_scope() as session:
        events = list(
            session.scalars(
                # 查最近一条 tnt-A 的 export.ocsf 审计
                select(AuditEvent)
                .where(AuditEvent.tenant_id == "tnt-A", AuditEvent.action == "export.ocsf")
                .order_by(AuditEvent.created_at.desc())
                .limit(1)
            )
        )
    assert events, "导出审计未落库"
    summary = events[0].summary
    assert summary["class"] == "detection_finding"
    assert summary["since"] == "2024-01-01T00:00:00Z"
    assert isinstance(summary["count"], int)
    assert set(summary) == {"class", "count", "since"}  # 审计摘要不得含导出内容
