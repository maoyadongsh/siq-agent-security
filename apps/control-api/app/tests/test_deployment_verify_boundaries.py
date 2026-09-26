"""独立回执验证器边界收口测试（CL-05-RECEIPT-VERIFIER-CLOSEOUT）。

负向为主，复用真实产品函数（端点 → verify_deployment_receipt）与合成部署行：
- 异常 receipt / revision（非对象、null、空串、布尔、数字、数组、对象、超长）
  必须明确拒绝为 no_receipt，且绝不构造/调用后端；
- 读回结构不符合 PolicySnapshot 合同 → fail-closed，不判通过、不崩溃、不泄漏原值；
- 错误目标（读回目标或回执自述 target 与部署目标冲突）即使 revision 相同也绝不 verified；
- verification 列不是对象时不崩溃；
- 审计失败时整体回滚，不留下无审计的"验证通过"。

保留 test_deployment_verify.py 的既有 verified/mismatch/unreachable/no_receipt、
租户隔离、权限与 409 用例不动。
"""

from __future__ import annotations

import uuid

import pytest

from app.adapters.openshell.contracts import AdapterError, PolicySnapshot
from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, DesiredPolicy, Environment, Finding, OutboxEvent


def _make_deployment(
    *,
    receipt=None,
    verification=None,
    status="effective",
    target=None,
    tenant_id="tnt-A",
) -> tuple[str, str]:
    """直接落库一个部署行（关注验证器本身，不走部署路径）；返回 (id, target)。"""
    target = target or f"sandbox-{uuid.uuid4().hex[:8]}"
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
            target=target,
            to_revision="policy-1",
            receipt=receipt,
            verification=verification,
            status=status,
        )
        session.add(dep)
        session.commit()
        return dep.id, target


class _FakeReadBackend:
    """可控独立读回后端：默认回显请求 target（与真实 CLI/HTTP/fake 后端一致）。

    snapshot_target / snapshot / revision 用于模拟异常读回（错目标、结构违约）。
    """

    def __init__(self, *, revision="1", snapshot_target=None, snapshot=None, error=None):
        self.revision = revision
        self.snapshot_target = snapshot_target
        self.snapshot = snapshot
        self.error = error

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        if self.error is not None:
            raise self.error
        if self.snapshot is not None:
            return self.snapshot
        return PolicySnapshot(
            target=self.snapshot_target if self.snapshot_target is not None else target,
            revision=self.revision,
            network=[],
        )


def _patch_backend(monkeypatch, backend: _FakeReadBackend) -> None:
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    monkeypatch.setattr("app.deployment_verify.OpenShellCliBackend", lambda: backend)


def _forbid_backend(monkeypatch) -> None:
    """异常回执不得访问后端：一旦被构造即断言失败。"""
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")

    def _boom():  # pragma: no cover - 触发即为回归
        raise AssertionError("backend must not be constructed for an unusable receipt")

    monkeypatch.setattr("app.deployment_verify.OpenShellCliBackend", _boom)


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
        for row in rows:
            session.expunge(row)
        return rows


_UNUSABLE_RECEIPTS = [
    pytest.param({"backend_revision": "7", "target": []}, id="target-list"),
    pytest.param({"backend_revision": "7", "target": ""}, id="target-empty"),
    pytest.param({"backend_revision": "7", "target": None}, id="target-null"),
    pytest.param("not-an-object", id="receipt-is-string"),
    pytest.param(["backend_revision", "7"], id="receipt-is-list"),
    pytest.param(7, id="receipt-is-number"),
    pytest.param(True, id="receipt-is-bool"),
    pytest.param({}, id="receipt-missing-revision"),
    pytest.param({"backend_revision": None}, id="revision-null"),
    pytest.param({"backend_revision": ""}, id="revision-empty-string"),
    pytest.param({"backend_revision": "   "}, id="revision-blank-string"),
    pytest.param({"backend_revision": True}, id="revision-bool"),
    pytest.param({"backend_revision": 7}, id="revision-number"),
    pytest.param({"backend_revision": ["7"]}, id="revision-list"),
    pytest.param({"backend_revision": {"revision": "7"}}, id="revision-object"),
    pytest.param({"backend_revision": "x" * 200}, id="revision-oversized"),
]


@pytest.mark.parametrize("receipt", _UNUSABLE_RECEIPTS)
def test_unusable_receipt_is_no_receipt_without_backend(client, tenant_a, monkeypatch, receipt):
    """异常 receipt/revision → no_receipt；不猜值、不访问后端、不落 Finding、不改状态。"""
    dep_id, _ = _make_deployment(receipt=receipt)
    _forbid_backend(monkeypatch)

    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"] == "no_receipt"
    # 异常原值绝不回显为"期望 revision"
    assert body["expected_revision"] is None
    assert body["actual_revision"] is None

    dep = _get_deployment(dep_id)
    assert dep.status == "effective"
    assert dep.verification["independent_attestation"]["result"] == "no_receipt"
    assert _findings(dep_id) == []


def test_blank_revision_never_matches_backend_blank(client, tenant_a, monkeypatch):
    """回执空/空白 revision 不得因后端也回空白而判 verified（不做 normalize）。"""
    dep_id, _ = _make_deployment(receipt={"backend_revision": "   "})
    _patch_backend(monkeypatch, _FakeReadBackend(revision="   "))

    body = _verify(client, tenant_a, dep_id).json()
    assert body["result"] == "no_receipt"
    assert body["expected_revision"] is None


def test_wrong_readback_target_same_revision_never_verified(client, tenant_a, monkeypatch):
    """读回目标与部署目标不一致时，revision 相同也绝不能 verified。"""
    dep_id, _ = _make_deployment(receipt={"backend_revision": "7"})
    _patch_backend(monkeypatch, _FakeReadBackend(revision="7", snapshot_target="another-sandbox"))

    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"] != "verified"
    assert body["result"] == "mismatch"

    dep = _get_deployment(dep_id)
    assert dep.status == "effective"  # 状态不自动翻转
    assert dep.verification["independent_attestation"]["result"] == "mismatch"


def test_receipt_target_conflict_same_revision_never_verified(client, tenant_a, monkeypatch):
    """回执自述 target 与部署目标冲突时，revision 相同也绝不能 verified。"""
    dep_id, _ = _make_deployment(receipt={"backend_revision": "7", "target": "some-other-target"})
    _patch_backend(monkeypatch, _FakeReadBackend(revision="7"))  # 读回回显部署目标

    body = _verify(client, tenant_a, dep_id).json()
    assert body["result"] == "mismatch"
    assert _findings(dep_id) != []  # 走既有 mismatch 处置（Finding）


def test_receipt_target_matching_deployment_still_verified(client, tenant_a, monkeypatch):
    """回执携带 target 且与部署目标一致（含旧回执合法 target）→ 原 verified 行为保持。"""
    target = "sandbox-consistent"
    dep_id, _ = _make_deployment(
        receipt={"backend_revision": "7", "target": target},
        target=target,
    )
    _patch_backend(monkeypatch, _FakeReadBackend(revision="7"))

    body = _verify(client, tenant_a, dep_id).json()
    assert body["result"] == "verified"
    assert body["expected_revision"] == "7"
    assert body["actual_revision"] == "7"


_MALFORMED_SNAPSHOTS = [
    pytest.param(PolicySnapshot(target="t", revision=""), id="revision-empty"),
    pytest.param(PolicySnapshot(target="t", revision="   "), id="revision-blank"),
    pytest.param(PolicySnapshot(target="", revision="7"), id="target-empty"),
    pytest.param(PolicySnapshot(target="t" * 129, revision="7"), id="target-oversized"),
    pytest.param(object(), id="not-a-snapshot"),
    pytest.param(PolicySnapshot(target="t", revision=7), id="revision-is-int"),
    pytest.param(PolicySnapshot(target="t", revision=None), id="revision-is-none"),
    pytest.param(PolicySnapshot(target=7, revision="7"), id="target-is-int"),
    pytest.param(PolicySnapshot(target="t", revision="9" * 200), id="revision-oversized"),
]


@pytest.mark.parametrize("snapshot", _MALFORMED_SNAPSHOTS)
def test_malformed_readback_fails_closed(client, tenant_a, monkeypatch, snapshot):
    """读回结构违反 PolicySnapshot 合同 → 不可信读回，fail-closed，不判通过、不泄漏原值。"""
    dep_id, _ = _make_deployment(receipt={"backend_revision": "7"})
    _patch_backend(monkeypatch, _FakeReadBackend(snapshot=snapshot))

    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"] == "unreachable"
    assert body["actual_revision"] is None
    assert _findings(dep_id) == []


def test_malformed_readback_does_not_fabricate_verified(client, tenant_a, monkeypatch):
    """后端抛出非 AdapterError 的协议异常不得被吞掉后伪装 verified。"""
    dep_id, _ = _make_deployment(receipt={"backend_revision": "7"})
    _patch_backend(monkeypatch, _FakeReadBackend(error=ValueError("protocol junk")))

    with pytest.raises(ValueError, match="protocol junk"):
        _verify(client, tenant_a, dep_id)
    # 异常未被吞掉、未提交：不留下"验证通过"
    dep = _get_deployment(dep_id)
    assert dep.verification is None or "independent_attestation" not in dep.verification


def test_restricted_backend_adapter_error_still_unreachable(client, tenant_a, monkeypatch):
    """AdapterError → 原 unreachable 语义保持（fail-closed，无 Finding，状态不变）。"""
    dep_id, _ = _make_deployment(receipt={"backend_revision": "7"})
    _patch_backend(monkeypatch, _FakeReadBackend(error=AdapterError("gateway unreachable")))

    body = _verify(client, tenant_a, dep_id).json()
    assert body["result"] == "unreachable"
    assert body["actual_revision"] is None
    assert _findings(dep_id) == []


@pytest.mark.parametrize(
    "verification",
    [pytest.param("junk", id="string"), pytest.param(["level", "x"], id="list"), pytest.param(42, id="number")],
)
def test_non_dict_verification_does_not_crash(client, tenant_a, monkeypatch, verification):
    """verification 列不是对象 → 不崩溃、不泄漏原值；证据本身合法时仍按合同判定。"""
    dep_id, _ = _make_deployment(receipt={"backend_revision": "7"}, verification=verification)
    _patch_backend(monkeypatch, _FakeReadBackend(revision="7"))

    resp = _verify(client, tenant_a, dep_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"] == "verified"

    dep = _get_deployment(dep_id)
    assert dep.verification["independent_attestation"]["result"] == "verified"


@pytest.mark.parametrize("revision", ["7", "9"])
def test_audit_failure_leaves_no_attestation(client, tenant_a, monkeypatch, revision):
    """审计失败 → 事务整体回滚，不留下无审计的"验证通过"。"""
    dep_id, _ = _make_deployment(receipt={"backend_revision": "7"})
    _patch_backend(monkeypatch, _FakeReadBackend(revision=revision))
    with session_scope() as session:
        before = tuple(session.query(model).count() for model in (Finding, AuditEvent, OutboxEvent))

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr("app.deployment_verify.audit", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        _verify(client, tenant_a, dep_id)

    dep = _get_deployment(dep_id)
    assert dep.verification is None or "independent_attestation" not in dep.verification
    with session_scope() as session:
        assert tuple(session.query(model).count() for model in (Finding, AuditEvent, OutboxEvent)) == before


def test_target_conflict_finding_does_not_copy_target(client, tenant_a, monkeypatch):
    target = "synthetic-private-target-marker"
    dep_id, _ = _make_deployment(receipt={"backend_revision": "7", "target": "other"}, target=target)
    _patch_backend(monkeypatch, _FakeReadBackend(revision="7"))
    assert _verify(client, tenant_a, dep_id).json()["result"] == "mismatch"
    assert all(target not in finding.impact for finding in _findings(dep_id))
