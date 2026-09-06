"""审计与 Outbox 一致性测试（设计文档 §23.1 / §23.2）。

不变量：审计与状态变化同事务；高风险写操作审计缺失即失败关闭。
"""

from __future__ import annotations

from app.db import session_scope
from app.models import AuditEvent, OutboxEvent
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


def _make_candidate(client, headers, name="audit-agent"):
    env = client.post("/api/v1/environments", json={"name": f"env-{name}"}, headers=headers).json()
    identity = f"edge-{name}"
    eh, private_key = register_edge(client, headers, env["id"], identity)
    task_id = create_scan_task(client, headers, env["id"])
    evidence = signed_evidence(
        private_key,
        identity,
        f"ev-{name}",
        content_hash="d" * 64,
        source_locator=f"profiles/{name}/config.yaml",
    )
    client.post(
        "/edge/v1/batches",
        json=signed_batch(
            private_key,
            task_id,
            candidates=[candidate(name, [f"ev-{name}"])],
            evidence=[evidence],
        ),
        headers=eh,
    )
    return client.get("/api/v1/candidates", headers=headers).json()[0]


def test_confirm_writes_audit_and_outbox_same_transaction(client, tenant_a):
    candidate = _make_candidate(client, tenant_a)
    resp = client.post(
        f"/api/v1/candidates/{candidate['id']}/confirm",
        json={"role": "financial-review-assistant"},
        headers=tenant_a,
    )
    assert resp.status_code == 200

    with session_scope() as session:
        audits = (
            session.query(AuditEvent)
            .filter(AuditEvent.action == "agent.confirm", AuditEvent.resource_id == candidate["id"])
            .all()
        )
        assert len(audits) == 1
        events = (
            session.query(OutboxEvent)
            .filter(
                OutboxEvent.event_type == "agent.asset.confirmed.v1",
                OutboxEvent.tenant_id == "tnt-A",
            )
            .all()
        )
        assert len(events) == 1
        # 审计 actor 与决策字段完整（§24.2 关联标识的落库部分）
        assert audits[0].actor_id == "user-a"
        assert audits[0].decision == "allow"


def test_audit_summary_contains_no_secret_content(client, tenant_a):
    """审计摘要只允许标识/数量/哈希，禁止敏感模式（§24.2 日志与审计脱敏）。"""
    _make_candidate(client, tenant_a, name="audit-agent-2")
    with session_scope() as session:
        for audit in session.query(AuditEvent).all():
            text = str(audit.summary)
            for pattern in ("Bearer ", "sk-", "api_key", "password", "token=", "secret"):
                assert pattern not in text, f"audit {audit.action} summary 泄露敏感模式: {pattern}"


def test_outbox_payload_is_redacted_envelope(client, tenant_a):
    candidate = _make_candidate(client, tenant_a, name="env-agent")
    client.post(f"/api/v1/candidates/{candidate['id']}/confirm", json={}, headers=tenant_a)
    with session_scope() as session:
        event = (
            session.query(OutboxEvent)
            .filter(
                OutboxEvent.event_type == "agent.asset.confirmed.v1",
                OutboxEvent.tenant_id == "tnt-A",
            )
            .order_by(OutboxEvent.id.desc())
            .first()
        )
        envelope = event.payload
        assert envelope["event_type"] == "agent.asset.confirmed.v1"
        assert envelope["tenant_id"] == "tnt-A"
        assert envelope["schema_version"] == 1
        assert "agent_asset_id" in envelope["payload"]


def test_emit_event_rejects_null_object_refs():
    """DEV11-A / R05：payload 对象引用不得为 null/空。"""
    from unittest.mock import MagicMock

    import pytest

    from app.outbox import emit_event

    session = MagicMock()
    with pytest.raises(ValueError, match="environment_id"):
        emit_event(session, "tnt-A", "environment.created.v1", {"environment_id": None})
    with pytest.raises(ValueError, match="resource_ref"):
        emit_event(
            session,
            "tnt-A",
            "environment.created.v1",
            {"environment_id": "env_x"},
            resource_ref="",
        )
    with pytest.raises(ValueError, match="asset_id"):
        emit_event(
            session,
            "tnt-A",
            "agent.finding.opened.v1",
            {"finding_id": "fnd_x", "asset_id": "   "},
        )


def test_environment_create_outbox_has_non_null_environment_id(client, tenant_a):
    """DEV11-A：创建环境时 outbox payload.environment_id 与 resource_ref 非空且一致。"""
    resp = client.post(
        "/api/v1/environments",
        json={"name": "env-dev11-a-refs"},
        headers=tenant_a,
    )
    assert resp.status_code == 201
    env_id = resp.json()["id"]
    assert env_id and env_id.startswith("env_")

    with session_scope() as session:
        event = (
            session.query(OutboxEvent)
            .filter(
                OutboxEvent.event_type == "environment.created.v1",
                OutboxEvent.tenant_id == "tnt-A",
            )
            .order_by(OutboxEvent.id.desc())
            .all()
        )
        match = next(
            (e for e in event if (e.payload.get("payload") or {}).get("environment_id") == env_id),
            None,
        )
        assert match is not None
        envelope = match.payload
        assert envelope["payload"]["environment_id"] == env_id
        assert envelope["resource_ref"] == env_id
        audits = (
            session.query(AuditEvent)
            .filter(
                AuditEvent.action == "environment.create",
                AuditEvent.resource_id == env_id,
            )
            .all()
        )
        assert len(audits) == 1


def test_change_request_create_outbox_has_non_null_ids(client, tenant_a):
    """DEV11-A：变更请求事件引用同事务非空 ID。"""
    import uuid

    policy = client.post(
        "/api/v1/policies",
        json={
            "name": f"pol-dev11-a-{uuid.uuid4().hex[:8]}",
            "selector": {"agent_ids": ["agt_1"]},
            "enforcement_mode": "audit_only",
        },
        headers=tenant_a,
    )
    assert policy.status_code == 201, policy.text
    policy_id = policy.json()["id"]
    assert policy_id.startswith("pol_")

    cr = client.post(
        "/api/v1/change-requests",
        json={
            "policy_id": policy_id,
            "idempotency_key": f"ik-dev11-{uuid.uuid4().hex}",
            "impact": {"note": "dev11-a"},
        },
        headers=tenant_a,
    )
    assert cr.status_code == 201, cr.text
    cr_id = cr.json()["id"]
    assert cr_id.startswith("cr_")

    with session_scope() as session:
        event = (
            session.query(OutboxEvent)
            .filter(
                OutboxEvent.event_type == "policy.change.requested.v1",
                OutboxEvent.tenant_id == "tnt-A",
            )
            .order_by(OutboxEvent.id.desc())
            .first()
        )
        assert event is not None
        payload = event.payload["payload"]
        assert payload["change_request_id"] == cr_id
        assert payload["policy_id"] == policy_id
        assert event.payload["resource_ref"] == cr_id
        audits = (
            session.query(AuditEvent)
            .filter(
                AuditEvent.action == "change.request.create",
                AuditEvent.resource_id == cr_id,
            )
            .all()
        )
        assert len(audits) == 1
