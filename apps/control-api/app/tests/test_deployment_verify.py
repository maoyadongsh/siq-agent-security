"""P2 部署回执独立验证（deployment_verify / receipt-verify 端点）测试。

负向为主：mismatch 落 Finding + 事件 + 审计、unreachable fail-closed 不改状态、
no_receipt 不判通过、跨租户 404、无 policy:read 403（先 404 后 403）、非 openshell-cli 409。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.adapters.openshell.contracts import AdapterError, PolicySnapshot
from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, DesiredPolicy, Environment, Finding, OutboxEvent


def _make_deployment(receipt=None, verification=None, status="effective", tenant_id="tnt-A") -> str:
    """直接落库一个部署行（本测试关注验证器本身，不走部署路径）。"""
    with session_scope() as session:
        env = Environment(tenant_id=tenant_id, name=f"env-{uuid.uuid4().hex[:8]}", mode="enforce")
        policy = DesiredPolicy(
            tenant_id=tenant_id,
            name=f"pol-{uuid.uuid4().hex[:8]}",
            selector={"agent_ids": ["agt_1"]},
            enforcement_mode="block",
            status="approved",
        )
        session.add_all([env, policy])
        session.flush()
        cr = ChangeRequest(
            tenant_id=tenant_id,
            policy_id=policy.id,
            proposer_user_id="user-a",
            idempotency_key=f"ik-{uuid.uuid4().hex}",
            status="effective",
        )
        session.add(cr)
        session.flush()
        dep = Deployment(
            tenant_id=tenant_id,
            environment_id=env.id,
            change_request_id=cr.id,
            target=f"sandbox-{uuid.uuid4().hex[:8]}",
            to_revision="policy-1",
            receipt=receipt,
            verification=verification,
            status=status,
        )
        session.add(dep)
        session.commit()
        return dep.id


class _FakeReadBackend:
    """可控的独立读回后端：返回固定 revision 或抛 AdapterError。"""

    def __init__(self, revision: str = "1", error: Exception | None = None):
        self.revision = revision
        self.error = error

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        if self.error is not None:
            raise self.error
        return PolicySnapshot(target=target, revision=self.revision, network=[])


def _patch_verifier_backend(monkeypatch, backend: _FakeReadBackend) -> None:
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    monkeypatch.setattr("app.deployment_verify.OpenShellCliBackend", lambda: backend)


def _verify(client, headers, dep_id: str):
    return client.post(f"/api/v1/deployments/{dep_id}/receipt-verify", headers=headers)


def _get_deployment(dep_id: str) -> Deployment:
    with session_scope() as session:
        dep = session.query(Deployment).filter(Deployment.id == dep_id).one()
        session.expunge(dep)
        return dep


def _findings(dep_id: str) -> list[Finding]:
    with session_scope() as session:
        rows = (
            session.query(Finding)
            .filter(Finding.rule_id == "deployment-receipt-mismatch", Finding.resource_ref == dep_id)
            .all()
        )
        for r in rows:
            session.expunge(r)
        return rows


def test_receipt_verify_verified(client, tenant_a, monkeypatch):
    """读回 revision 与回执一致 → verified，attestation 落库且保留 verification 既有键。"""
    dep_id = _make_deployment(
        receipt={"backend_revision": "7", "snapshot_hash": "abc"},
        verification={"level": "readback_verified", "method": "config_readback"},
    )
    _patch_verifier_backend(monkeypatch, _FakeReadBackend(revision="7"))

    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"] == "verified"
    assert body["verifier"] == "control-plane.independent-readback.v1"
    assert body["expected_revision"] == "7"
    assert body["actual_revision"] == "7"
    assert body["checked_at"]

    dep = _get_deployment(dep_id)
    attestation = dep.verification["independent_attestation"]
    assert attestation["result"] == "verified"
    assert dep.verification["level"] == "readback_verified"  # 既有键保留
    assert dep.status == "effective"  # 验证不改动部署状态
    assert _findings(dep_id) == []
    with session_scope() as session:
        audit_row = (
            session.query(AuditEvent)
            .filter(AuditEvent.action == "deployment.receipt_verify", AuditEvent.resource_id == dep_id)
            .one()
        )
        assert audit_row.summary["result"] == "verified"
        assert audit_row.summary["expected_revision"] == "7"
        assert audit_row.summary["actual_revision"] == "7"


def test_receipt_verify_mismatch_finding_event_audit(client, tenant_a, monkeypatch):
    """revision 不一致 → mismatch：Finding + outbox 事件 + 审计；部署状态不自动翻转。"""
    dep_id = _make_deployment(receipt={"backend_revision": "7"})
    _patch_verifier_backend(monkeypatch, _FakeReadBackend(revision="9"))

    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"] == "mismatch"

    findings = _findings(dep_id)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "high"
    assert f.domain == "drift"
    assert f.status == "open"
    assert f.tenant_id == "tnt-A"

    dep = _get_deployment(dep_id)
    assert dep.status == "effective"  # Finding 驱动处置，状态不自动翻转
    assert dep.verification["independent_attestation"]["result"] == "mismatch"

    with session_scope() as session:
        events = [
            e
            for e in session.query(OutboxEvent)
            .filter(OutboxEvent.event_type == "policy.deployment.receipt_mismatch.v1")
            .all()
            if e.payload.get("resource_ref") == dep_id
        ]
        assert len(events) == 1
        assert events[0].payload["payload"]["expected_revision"] == "7"
        assert events[0].payload["payload"]["actual_revision"] == "9"
        audit_row = (
            session.query(AuditEvent)
            .filter(AuditEvent.action == "deployment.receipt_verify", AuditEvent.resource_id == dep_id)
            .one()
        )
        assert audit_row.summary["result"] == "mismatch"


def test_receipt_verify_mismatch_dedup(client, tenant_a, monkeypatch):
    """重复验证同 deployment：open Finding 不重复建行，只更新 last_seen_at。"""
    dep_id = _make_deployment(receipt={"backend_revision": "7"})
    _patch_verifier_backend(monkeypatch, _FakeReadBackend(revision="9"))

    assert _verify(client, tenant_a, dep_id).json()["result"] == "mismatch"
    with session_scope() as session:
        row = session.query(Finding).filter(Finding.resource_ref == dep_id).one()
        row.last_seen_at = row.last_seen_at - timedelta(days=1)  # 回拨，验证再次调用会更新
        session.commit()

    assert _verify(client, tenant_a, dep_id).json()["result"] == "mismatch"
    findings = _findings(dep_id)
    assert len(findings) == 1  # 不重复建行
    assert findings[0].last_seen_at > findings[0].first_seen_at - timedelta(days=1) + timedelta(hours=23)


def test_receipt_verify_unreachable_fails_closed(client, tenant_a, monkeypatch):
    """后端不可达 → unreachable：无 Finding、状态不变、attestation 如实记录。"""
    dep_id = _make_deployment(receipt={"backend_revision": "7"})
    _patch_verifier_backend(monkeypatch, _FakeReadBackend(error=AdapterError("gateway unreachable")))

    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"] == "unreachable"
    assert resp.json()["actual_revision"] is None

    dep = _get_deployment(dep_id)
    assert dep.status == "effective"  # fail-closed：不改动任何状态
    assert dep.verification["independent_attestation"]["result"] == "unreachable"
    assert _findings(dep_id) == []
    with session_scope() as session:
        audit_row = (
            session.query(AuditEvent)
            .filter(AuditEvent.action == "deployment.receipt_verify", AuditEvent.resource_id == dep_id)
            .one()
        )
        assert audit_row.summary["result"] == "unreachable"
        assert len(audit_row.summary["error_digest"]) == 64  # 错误只落摘要，不落原文
        assert "gateway unreachable" not in str(audit_row.summary)


def test_receipt_verify_no_receipt(client, tenant_a, monkeypatch):
    """receipt 为空/无 backend_revision → no_receipt（无证据可验，不判通过）。"""
    dep_id = _make_deployment(receipt=None)
    _patch_verifier_backend(monkeypatch, _FakeReadBackend(revision="7"))

    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"] == "no_receipt"
    assert body["expected_revision"] is None
    assert _findings(dep_id) == []


def test_receipt_verify_cross_tenant_404(client, tenant_a, tenant_b, monkeypatch):
    """跨租户 deployment：404 隐藏存在性。"""
    dep_id = _make_deployment(receipt={"backend_revision": "7"}, tenant_id="tnt-A")
    _patch_verifier_backend(monkeypatch, _FakeReadBackend(revision="7"))
    resp = _verify(client, tenant_b, dep_id)
    assert resp.status_code == 404


def test_receipt_verify_forbidden_without_policy_read(client, tenant_a, monkeypatch):
    """无 policy:read 权限身份 → 403；且 404 先于 403（跨租户+无权限仍 404）。"""
    dep_id = _make_deployment(receipt={"backend_revision": "7"})
    _patch_verifier_backend(monkeypatch, _FakeReadBackend(revision="7"))
    no_read = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-owner", "X-Dev-Roles": "agent_owner"}
    resp = _verify(client, no_read, dep_id)
    assert resp.status_code == 403

    # 顺序：先租户定位 404，再权限 403 —— 无权限身份访问跨租户对象必须仍得 404
    no_read_b = {"X-Dev-Tenant-Id": "tnt-B", "X-Dev-User-Id": "user-owner-b", "X-Dev-Roles": "agent_owner"}
    resp2 = _verify(client, no_read_b, dep_id)
    assert resp2.status_code == 404


def test_receipt_verify_backend_unsupported_409(client, tenant_a):
    """SIQ_AS_ENFORCEMENT_BACKEND != openshell-cli（默认 fake）→ 409。"""
    dep_id = _make_deployment(receipt={"backend_revision": "7"})
    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "receipt_verify_backend_unsupported"
