"""审计与 Outbox 一致性测试（设计文档 §23.1 / §23.2）。

不变量：审计与状态变化同事务；高风险写操作审计缺失即失败关闭。
"""

from __future__ import annotations

from app.db import session_scope
from app.models import AuditEvent, OutboxEvent


def _make_candidate(client, headers, name="audit-agent"):
    env = client.post("/api/v1/environments", json={"name": f"env-{name}"}, headers=headers).json()
    enr = client.post(f"/api/v1/environments/{env['id']}/edge-enrollment", json={}, headers=headers).json()
    reg = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": enr["code"],
            "device_identity": f"edge-{name}",
            "public_key_pem": "PEM",
            "version": "0.1.0",
        },
    ).json()
    eh = {"Authorization": f"Bearer {reg['device_secret']}", "X-Edge-Identity": f"edge-{name}"}
    client.post(
        "/edge/v1/batches",
        json={
            "candidates": [
                {
                    "candidate_id": f"hermes:{name}",
                    "source_type": "hermes_profile",
                    "source_locator": f"hermes://profiles/{name}",
                    "discovered_at": "2026-08-13T12:00:00Z",
                    "name": name,
                    "framework": "hermes",
                    "evidence_ids": [f"ev-{name}"],
                }
            ],
            "evidence": [
                {
                    "evidence_id": f"ev-{name}",
                    "source_type": "manifest",
                    "source_locator": f"profiles/{name}/config.yaml",
                    "observed_at": "2026-08-13T12:00:00Z",
                    "collector_id": f"edge-{name}",
                    "connector_version": "0.1.0",
                    "content_hash": "d" * 64,
                    "signature": "sig",
                }
            ],
        },
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
