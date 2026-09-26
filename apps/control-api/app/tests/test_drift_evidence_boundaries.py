"""漂移巡检异常证据与租户关联边界测试（CL-05-DRIFT-EVIDENCE-CLOSEOUT）。

负向为主，直接复用真实产品函数 `app.drift.check_policy_drift`（必要时经真实端点
`POST /api/v1/permissions/check-drift` 验证事务），不使用复制生产算法的自证测试：

- 非对象 receipt、异常 revision 类型：不得崩溃、不得被 str() 归一后参与比较；
- 读回 target 与本部署 target 不符：即使 revision 相同也不是可信"当前有效规则"；
- ChangeRequest / DesiredPolicy 属于其他租户或缺失：不读取、不回显、不参与比较，
  也不得被解释为"期望没有网络规则"；
- policy.network / snapshot.network 异常容器、非对象行、异常 endpoint：
  不得崩溃，也不得被悄悄过滤成空列表；
- 合法空规则集保持可用（不因加校验被错误拒绝）；
- 混合批次：一条异常部署不得阻断同批其他正常部署的巡检；
- 异常原文不进入结果、响应与持久化（Finding/审计/outbox）；
- 检查阶段不改部署状态、不自行提交事务；审计失败整体回滚；
- 主开发者复核修复：回执显式 target 必须与本部署 target 原值一致（冲突 → 该维度不可用，
  不推导 revision_mismatch）；网络行 effect 显式非法值使该维度不可用（不当 allow、不跳过，
  合法 allow/deny/缺省键语义不变）。

保留 apps/control-api/app/tests/test_rules.py 既有漂移用例（正常/漂移/不可读/一致）语义不动。
"""

from __future__ import annotations

import uuid

import pytest

from app.adapters.openshell.contracts import AdapterError, PolicySnapshot
from app.db import session_scope
from app.models import (
    AuditEvent,
    ChangeRequest,
    Deployment,
    DesiredPolicy,
    Finding,
    OutboxEvent,
    Tenant,
)

# 明确标记的合成"其他租户"规则：出现即视为跨租户回显
_FOREIGN_MARKER = "synth-foreign-endpoint.invalid:443"
_LOCAL_ENDPOINT = "api.example.com:443"

_UNSET = object()

# 读写路径中出现的异常证据原文标记：绝不进入结果/响应/持久化
_SECRET_MARKER = "receipt-secret-marker-should-never-persist"


class _FakeBackend:
    """可控读回后端；默认与真实 CLI/HTTP/fake 后端一致地回显请求 target。"""

    def __init__(self, *, revision="1", snapshot_target=_UNSET, network=_UNSET, error=None):
        self.revision = revision
        self.snapshot_target = snapshot_target
        self.network = network
        self.error = error
        self.calls: list[str] = []

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        self.calls.append(target)
        if self.error is not None:
            raise self.error
        return PolicySnapshot(
            target=target if self.snapshot_target is _UNSET else self.snapshot_target,
            revision=self.revision,
            network=[] if self.network is _UNSET else self.network,
        )


def _patch_backend(monkeypatch, backend) -> None:
    """drift 模块直接构造 CLI 后端：注入零参工厂。"""
    monkeypatch.setattr("app.drift.OpenShellCliBackend", lambda: backend)


def _tenant_id() -> str:
    return f"tnt-drift-{uuid.uuid4().hex[:8]}"


def _ensure_tenant(session, tenant_id: str) -> None:
    if session.query(Tenant).filter(Tenant.id == tenant_id).count() == 0:
        session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))


def _new_policy(session, tenant_id, *, network, name=None) -> DesiredPolicy:
    policy = DesiredPolicy(
        tenant_id=tenant_id,
        name=name or f"pol-{uuid.uuid4().hex[:8]}",
        selector={"agent_ids": ["agt_1"]},
        network=network,
        enforcement_mode="block",
        status="approved",
    )
    session.add(policy)
    session.flush()
    return policy


def _new_change_request(session, tenant_id, policy_id, *, status="effective") -> ChangeRequest:
    cr = ChangeRequest(
        tenant_id=tenant_id,
        policy_id=policy_id,
        proposer_user_id="user-a",
        approver_user_id="user-b",
        status=status,
        idempotency_key=f"ik-{uuid.uuid4().hex}",
    )
    session.add(cr)
    session.flush()
    return cr


def _new_deployment(session, tenant_id, *, target, change_request_id, receipt, status="effective") -> Deployment:
    dep = Deployment(
        tenant_id=tenant_id,
        environment_id=f"env-{uuid.uuid4().hex[:8]}",
        change_request_id=change_request_id,
        target=target,
        to_revision="policy-1",
        receipt=receipt,
        status=status,
    )
    session.add(dep)
    session.flush()
    return dep


def _seed(
    session,
    tenant_id,
    *,
    target=None,
    receipt=_UNSET,
    receipt_rev="1",
    policy_network=None,
    policy_tenant_id=None,
    change_request_id=None,
    policy_id=None,
):
    """落库一条 effective 部署；默认同租户、回执 revision=1、无网络声明。"""
    target = target or f"sandbox-{uuid.uuid4().hex[:8]}"
    policy = _new_policy(session, policy_tenant_id or tenant_id, network=policy_network)
    cr = _new_change_request(session, tenant_id, policy.id)
    dep = _new_deployment(
        session,
        tenant_id,
        target=target,
        change_request_id=change_request_id if change_request_id is not None else cr.id,
        receipt={"backend_revision": receipt_rev} if receipt is _UNSET else receipt,
    )
    if policy_id is not None:
        cr.policy_id = policy_id
        session.flush()
    return dep, policy, cr


def _results_for(results, dep_id):
    return [r for r in results if r.deployment_id == dep_id]


def _kinds(results, dep_id):
    return [r.details.get("kind") for r in _results_for(results, dep_id)]


def _run(tenant_id):
    from app.drift import check_policy_drift

    with session_scope() as session:
        return check_policy_drift(session, tenant_id)


def _run_and_persist(tenant_id):
    from app.drift import check_policy_drift, upsert_drift_findings

    with session_scope() as session:
        results = check_policy_drift(session, tenant_id)
        counts = upsert_drift_findings(session, tenant_id, results)
        session.flush()
        return results, counts


# --------------------------------------------------------------- 既有正常行为


def test_consistent_deployment_yields_no_result(client, monkeypatch):
    tenant = _tenant_id()
    backend = _FakeBackend(revision="1", network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}])
    _patch_backend(monkeypatch, backend)
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == []


def test_legal_empty_rule_sets_are_not_rejected(client, monkeypatch):
    """合法空列表：期望空 + 后端空 → 无漂移；不得因加校验被误判为不可读。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_network=[])
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == []


def test_legal_null_desired_network_is_not_invalid_evidence(client, monkeypatch):
    """`DesiredPolicy.network` 合同为 list|None：null 表示未声明，不是异常证据。

    沿用既有比较模型（无期望 allow 规则），既不得崩溃也不得被当不可读；
    后端存在规则时按既有语义报额外规则，而不是静默无漂移。
    """
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_network=None)
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == []

    tenant_with_rules = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant_with_rules)
        dep, _, _ = _seed(session, tenant_with_rules, policy_network=None)
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant_with_rules), dep_id) == ["undeclared_rules"]


def test_unexpected_backend_error_is_not_swallowed(client, monkeypatch):
    """非预期异常（编程/数据库错误）不得被吞成 unreadable 或"无漂移"（仅 AdapterError 被处理）。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(error=RuntimeError("synthetic backend bug")))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        _seed(session, tenant, policy_network=[])
        session.commit()
    with pytest.raises(RuntimeError, match="synthetic backend bug"):
        _run(tenant)


def test_revision_mismatch_and_rule_drift_preserved(client, monkeypatch):
    """合法 revision 不一致与规则缺失/额外仍按原语义检测。"""
    tenant = _tenant_id()
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="2",
            network=[
                {"endpoint": _LOCAL_ENDPOINT, "effect": "allow"},
                {"endpoint": "extra.example.com:443", "effect": "allow"},
            ],
        ),
    )
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": "missing.example.com:443", "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()
    kinds = _kinds(_run(tenant), dep_id)
    assert "revision_mismatch" in kinds
    assert "missing_rules" in kinds
    assert "undeclared_rules" in kinds


def test_string_zero_revision_is_usable(client, monkeypatch):
    """fake 后端使用字符串 "0"（上一轮修正）：不得新增正整数/纯数字限制。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="0", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, receipt_rev="0", policy_network=[])
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == []


def test_revision_compared_without_normalization(client, monkeypatch):
    """原值比较：不 trim、不 lowercase、不截断。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision=" 7", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, receipt_rev="7", policy_network=[])
        dep_id = dep.id
        session.commit()
    assert "revision_mismatch" in _kinds(_run(tenant), dep_id)

    tenant_case = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="7A", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant_case)
        dep, _, _ = _seed(session, tenant_case, receipt_rev="7a", policy_network=[])
        dep_id = dep.id
        session.commit()
    assert "revision_mismatch" in _kinds(_run(tenant_case), dep_id)


# ------------------------------------------------------ 异常回执与异常 revision

_NON_OBJECT_RECEIPTS = [
    pytest.param(["backend_revision", "1"], id="receipt-is-list"),
    pytest.param("not-an-object", id="receipt-is-string"),
    pytest.param(7, id="receipt-is-number"),
    pytest.param(True, id="receipt-is-bool"),
]

_UNUSABLE_RECEIPT_REVISIONS = [
    pytest.param({}, id="missing-key"),
    pytest.param({"backend_revision": None}, id="revision-null"),
    pytest.param({"backend_revision": ""}, id="revision-empty"),
    pytest.param({"backend_revision": "   "}, id="revision-blank"),
    pytest.param({"backend_revision": 7}, id="revision-number"),
    pytest.param({"backend_revision": True}, id="revision-bool"),
    pytest.param({"backend_revision": {"revision": "1"}}, id="revision-object"),
    pytest.param({"backend_revision": ["1"]}, id="revision-list"),
    pytest.param({"backend_revision": "x" * 200}, id="revision-oversized"),
    pytest.param({"backend_revision": "1", "target": []}, id="explicit-target-list"),
]


@pytest.mark.parametrize("receipt", _NON_OBJECT_RECEIPTS + _UNUSABLE_RECEIPT_REVISIONS)
def test_unusable_receipt_is_isolated_and_reported(client, monkeypatch, receipt):
    """非对象/不可用回执：不得崩溃，不得被当作无漂移，按既有 unreadable 语义如实报告。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, receipt=receipt, policy_network=[])
        dep_id = dep.id
        session.commit()

    results = _run(tenant)
    kinds = _kinds(results, dep_id)
    assert kinds == ["unreadable"], kinds
    assert not {"revision_mismatch", "missing_rules", "undeclared_rules"} & set(kinds)


def test_unusable_revision_is_never_stringified_into_mismatch(client, monkeypatch):
    """revision=7 不得与后端 "7" 比对成一致，也不得伪造 mismatch。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="7", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, receipt={"backend_revision": 7}, policy_network=[])
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["unreadable"]


def test_receipt_absent_keeps_other_dimensions_checked(client, monkeypatch):
    """既有语义：无回执（NULL）时 network 维度仍可检查，不因缺少回执整体作废。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            receipt=None,
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["missing_rules"]


# ---------------------------------------------------------------- 错误读回目标


def test_wrong_readback_target_is_not_trusted_evidence(client, monkeypatch):
    """读回 target 与本部署 target 不符：即使 revision 相同也绝不当作无漂移。"""
    tenant = _tenant_id()
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="1",
            snapshot_target="sandbox-other-tenant",
            network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        ),
    )
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["unreadable"]


def test_wrong_readback_target_does_not_produce_rule_verdict(client, monkeypatch):
    """错误目标的读回不得参与规则比对（既不报缺失也不报额外）。"""
    tenant = _tenant_id()
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="1",
            snapshot_target="sandbox-other",
            network=[{"endpoint": _FOREIGN_MARKER, "effect": "allow"}],
        ),
    )
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()
    results = _run(tenant)
    assert _kinds(results, dep_id) == ["unreadable"]
    assert _FOREIGN_MARKER not in str(results)


_RUINED_READBACKS = [
    pytest.param(7, id="revision-number"),
    pytest.param("", id="revision-empty"),
    pytest.param("   ", id="revision-blank"),
    pytest.param("x" * 200, id="revision-oversized"),
]


@pytest.mark.parametrize("revision", _RUINED_READBACKS)
def test_ruined_readback_structure_is_unreadable(client, monkeypatch, revision):
    """读回结构不符合 PolicySnapshot 合同 → fail-closed，不判无漂移、不崩溃。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision=revision, network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, receipt_rev="1", policy_network=[])
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["unreadable"]


# ------------------------------------------------------------ 租户关联与缺失


def test_foreign_tenant_policy_is_never_read(client, monkeypatch):
    """部署关联的策略属于其他租户：不读取正文、不参与比较、不回显其规则。"""
    tenant, other = _tenant_id(), _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        _ensure_tenant(session, other)
        foreign_policy = _new_policy(session, other, network=[{"endpoint": _FOREIGN_MARKER, "effect": "allow"}])
        dep, _, cr = _seed(session, tenant, policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}])
        cr.policy_id = foreign_policy.id
        dep_id = dep.id
        session.commit()

    results = _run(tenant)
    assert _kinds(results, dep_id) == ["unreadable"]
    assert _FOREIGN_MARKER not in str(results)


def test_foreign_tenant_change_request_is_never_read(client, monkeypatch):
    """部署关联的 ChangeRequest 属于其他租户：按不可用证据处理。"""
    tenant, other = _tenant_id(), _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _FOREIGN_MARKER, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        _ensure_tenant(session, other)
        foreign_policy = _new_policy(session, other, network=[{"endpoint": _FOREIGN_MARKER, "effect": "allow"}])
        foreign_cr = _new_change_request(session, other, foreign_policy.id)
        dep, _, _ = _seed(session, tenant, change_request_id=foreign_cr.id)
        dep_id = dep.id
        session.commit()

    results = _run(tenant)
    assert _kinds(results, dep_id) == ["unreadable"]
    assert _FOREIGN_MARKER not in str(results)


def test_missing_change_request_is_not_treated_as_no_rules(client, monkeypatch):
    """关联缺失：不读作"期望没有网络规则"，也不报告无漂移。"""
    tenant = _tenant_id()
    backend_network = [{"endpoint": "undeclared.example.com:443", "effect": "allow"}]
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=backend_network))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, change_request_id=f"cr-missing-{uuid.uuid4().hex[:8]}")
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["unreadable"]


def test_missing_policy_is_not_treated_as_no_rules(client, monkeypatch):
    tenant = _tenant_id()
    backend_network = [{"endpoint": "undeclared.example.com:443", "effect": "allow"}]
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=backend_network))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_id=f"pol-missing-{uuid.uuid4().hex[:8]}")
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["unreadable"]


# ------------------------------------------------------- 异常网络容器与规则行

_BAD_DESIRED_NETWORKS = [
    pytest.param({}, id="container-dict"),
    pytest.param("allow-all", id="container-string"),
    pytest.param(7, id="container-number"),
    pytest.param([None], id="row-null"),
    pytest.param(["api.example.com:443"], id="row-string"),
    pytest.param([{}], id="row-missing-endpoint"),
    pytest.param([{"endpoint": None, "effect": "allow"}], id="endpoint-null"),
    pytest.param([{"endpoint": 443, "effect": "allow"}], id="endpoint-number"),
    pytest.param([{"endpoint": ["api.example.com", 443], "effect": "allow"}], id="endpoint-unhashable"),
    pytest.param([{"endpoint": _LOCAL_ENDPOINT, "effect": {"kind": "allow"}}], id="effect-object"),
]

_BAD_READBACK_NETWORKS = [
    pytest.param("allow-all", id="container-string"),
    pytest.param({"siq_as_rule_0": {}}, id="container-dict"),
    pytest.param(None, id="container-null"),
    pytest.param([None], id="row-null"),
    pytest.param([{"effect": "allow"}], id="row-missing-endpoint"),
    pytest.param([{"endpoint": None, "effect": "allow"}], id="endpoint-null"),
    pytest.param([{"endpoint": 443, "effect": "allow"}], id="endpoint-number"),
]


@pytest.mark.parametrize("network", _BAD_DESIRED_NETWORKS)
def test_malformed_desired_network_does_not_crash_or_fabricate(client, monkeypatch, network):
    """期望策略网络容器/行异常：不得崩溃，也不得被悄悄当作空列表。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _FOREIGN_MARKER, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, receipt_rev="1", policy_network=network)
        dep_id = dep.id
        session.commit()

    results = _run(tenant)
    kinds = _kinds(results, dep_id)
    assert kinds == ["unreadable"], kinds
    # 异常行不得被静默过滤成空期望集合 → 不得据此报"额外规则"
    assert "undeclared_rules" not in kinds


@pytest.mark.parametrize("network", _BAD_READBACK_NETWORKS)
def test_malformed_readback_network_does_not_crash_or_fabricate(client, monkeypatch, network):
    """后端读回网络容器/行异常：不得崩溃、不得报缺失规则。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=network))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    results = _run(tenant)
    kinds = _kinds(results, dep_id)
    assert kinds == ["unreadable"], kinds
    assert "missing_rules" not in kinds


def test_deny_rules_still_excluded_from_comparison(client, monkeypatch):
    """allow/deny 既有比较模型不变：deny 行不参与 endpoint 集合比对。"""
    tenant = _tenant_id()
    deny_rule = [{"endpoint": "deny.example.com:443", "effect": "deny"}]
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=deny_rule))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": "deny.example.com:443", "effect": "deny"}],
        )
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == []


# -------------------------------------------------------------- 混合批次处理


def test_mixed_batch_keeps_checking_healthy_deployments(client, monkeypatch):
    """一条异常部署不得阻断同批其他正常部署：异常可见 + 正常漂移仍被发现。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        bad, _, _ = _seed(
            session,
            tenant,
            receipt=["maybe", "a", "list"],
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        healthy, _, _ = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[
                {"endpoint": _LOCAL_ENDPOINT, "effect": "allow"},
                {"endpoint": "gone.example.com:443", "effect": "allow"},
            ],
        )
        bad_id, healthy_id = bad.id, healthy.id
        session.commit()

    results = _run(tenant)
    # 异常记录：unreadable 可见且排在前面；不可核对的是回执证据，只作废 revision 维度，
    # 网络维度仍按各自可信证据比对（可独立验证的事实不丢弃）
    assert _kinds(results, bad_id) == ["unreadable", "missing_rules"]
    healthy_kinds = _kinds(results, healthy_id)
    assert "revision_mismatch" in healthy_kinds
    assert "missing_rules" in healthy_kinds


# ------------------------------------------------- 持久化、脱敏与事务边界


@pytest.mark.parametrize(
    "receipt",
    [
        pytest.param(["backend_revision", _SECRET_MARKER], id="list-with-marker"),
        pytest.param({"backend_revision": _SECRET_MARKER + "x" * 200}, id="oversized-with-marker"),
    ],
)
def test_anomalous_evidence_never_persisted_raw(client, monkeypatch, receipt):
    """异常回执原文不进入结果、Finding、审计与 outbox。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, receipt=receipt, policy_network=[])
        dep_id = dep.id
        session.commit()

    results, _ = _run_and_persist(tenant)
    assert _kinds(results, dep_id) == ["unreadable"]
    assert _SECRET_MARKER not in str(results)

    with session_scope() as session:
        findings = session.query(Finding).filter(Finding.resource_ref == f"deployment:{dep_id}").all()
        assert findings, "unreadable 结果应经既有路径落 Finding"
        for finding in findings:
            assert _SECRET_MARKER not in str(finding.impact)
            assert _SECRET_MARKER not in str(finding.risk_acceptance)
        audits = session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant).all()
        events = session.query(OutboxEvent).filter(OutboxEvent.tenant_id == tenant).all()
        assert audits and events
        for row in [*audits, *events]:
            assert _SECRET_MARKER not in str(getattr(row, "summary", "")) + str(getattr(row, "payload", ""))


def test_cross_tenant_evidence_never_persisted_or_echoed(client, tenant_a, monkeypatch):
    """跨租户策略规则标记不得出现在结果、响应、Finding/审计/outbox 中。"""
    tenant, other = _tenant_id(), _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        _ensure_tenant(session, other)
        foreign_policy = _new_policy(session, other, network=[{"endpoint": _FOREIGN_MARKER, "effect": "allow"}])
        dep, _, cr = _seed(session, tenant, policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}])
        cr.policy_id = foreign_policy.id
        dep_id = dep.id
        session.commit()

    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant}
    resp = client.post("/api/v1/permissions/check-drift", headers=headers)
    assert resp.status_code == 200, resp.text
    assert _FOREIGN_MARKER not in resp.text
    body = resp.json()
    entry = next(r for r in body["drift_results"] if r["deployment_id"] == dep_id)
    assert entry["kind"] == "unreadable"

    with session_scope() as session:
        for finding in session.query(Finding).filter(Finding.resource_ref == f"deployment:{dep_id}").all():
            assert _FOREIGN_MARKER not in str(finding.impact)
            assert _FOREIGN_MARKER not in str(finding.risk_acceptance)
        for row in session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant).all():
            assert _FOREIGN_MARKER not in str(row.summary)
        for row in session.query(OutboxEvent).filter(OutboxEvent.tenant_id == tenant).all():
            assert _FOREIGN_MARKER not in str(row.payload)


def test_check_stage_does_not_change_state_or_publish(client, monkeypatch):
    """检查阶段不改部署状态、不改策略状态、不发布策略、不自行提交。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, policy, cr = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id, policy_id, cr_id = dep.id, policy.id, cr.id
        session.commit()

    from app.drift import check_policy_drift

    with session_scope() as session:
        results = check_policy_drift(session, tenant)
        assert _kinds(results, dep_id)  # 有漂移结论
        session.commit()

    with session_scope() as session:
        dep = session.get(Deployment, dep_id)
        assert dep.status == "effective"
        assert dep.receipt == {"backend_revision": "1"}
        assert dep.verification is None
        assert session.get(DesiredPolicy, policy_id).status == "approved"
        assert session.get(ChangeRequest, cr_id).status == "effective"


def test_audit_failure_rolls_back_whole_persist(client, tenant_a, monkeypatch):
    """经既有持久化路径保存 unreadable 结果时，审计失败整体回滚，不留孤立 Finding/outbox。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, receipt={"backend_revision": "1", "target": []}, policy_network=[])
        dep_id = dep.id
        session.commit()
    with session_scope() as session:
        before = tuple(
            session.query(model).filter(model.tenant_id == tenant).count()
            for model in (Finding, AuditEvent, OutboxEvent)
        )

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic drift audit failure")

    monkeypatch.setattr("app.drift.audit", fail)
    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant}
    with pytest.raises(RuntimeError, match="synthetic drift audit failure"):
        client.post("/api/v1/permissions/check-drift", headers=headers)

    with session_scope() as session:
        after = tuple(
            session.query(model).filter(model.tenant_id == tenant).count()
            for model in (Finding, AuditEvent, OutboxEvent)
        )
        assert after == before
        assert session.query(Finding).filter(Finding.resource_ref == f"deployment:{dep_id}").count() == 0


def test_endpoint_reports_unreadable_without_raw_values(client, tenant_a, monkeypatch):
    """真实端点：不可核对部署以既有 unreadable 语义返回，不回显异常原文。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(error=AdapterError("backend down; token=" + _SECRET_MARKER)))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_network=[])
        dep_id = dep.id
        session.commit()

    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant}
    resp = client.post("/api/v1/permissions/check-drift", headers=headers)
    assert resp.status_code == 200, resp.text
    assert _SECRET_MARKER not in resp.text
    entry = next(r for r in resp.json()["drift_results"] if r["deployment_id"] == dep_id)
    assert entry["kind"] == "unreadable"


# -------------------------- 主开发者复核问题修复（CL-05-DRIFT-EVIDENCE-REVIEW-FIX）
#
# 问题 1：回执自述 target 与部署 target 冲突未检查——别的目标的回执被当作本部署的
# revision 证据（revision 恰好相同就报"无漂移"，甚至返回空结果列表）。
# 问题 2：网络规则行 effect 只校验"是字符串"，未知/空/大小写变体被当作允许规则参与比对。
# 合同依据：packages/contracts/openshell-policy-safety.v2.md §Network compilation
# "Network compilation accepts only `effect=allow`"；读回侧生产者
# `gateway_network_to_rules` 恒产出 `effect=allow`。


def test_conflicting_receipt_target_is_not_silent_no_drift(client, monkeypatch):
    """复现问题 1：错目标回执 + revision 相同 + 网络一致 → 不得返回空结果列表。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            target="target-A",
            receipt={"backend_revision": "1", "target": "target-B"},
            policy_network=[],
        )
        dep_id = dep.id
        session.commit()

    results = _run(tenant)
    kinds = _kinds(results, dep_id)
    assert kinds, "错目标回执不得产出空结果（假象：检查完整且无漂移）"
    assert kinds == ["unreadable"], kinds


def test_receipt_target_conflict_never_derives_revision_mismatch(client, monkeypatch):
    """错目标回执不是本部署证据：即使后端 revision 不同，也不得据此报 revision_mismatch。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            target="target-A",
            receipt={"backend_revision": "1", "target": "target-B"},
            policy_network=[],
        )
        dep_id = dep.id
        session.commit()

    kinds = _kinds(_run(tenant), dep_id)
    assert kinds == ["unreadable"], kinds
    assert "revision_mismatch" not in kinds


def test_receipt_target_conflict_keeps_independent_network_dimension(client, monkeypatch):
    """回执证据作废只影响 revision 维度：可独立验证的网络缺失仍按既有语义报出。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            target="target-A",
            receipt={"backend_revision": "1", "target": "target-B"},
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    assert _kinds(_run(tenant), dep_id) == ["unreadable", "missing_rules"]


def test_receipt_explicit_matching_target_keeps_legacy_comparison(client, monkeypatch):
    """回执显式 target 与本部署一致 → 沿用既有 revision 比对语义；缺 target 键仍兼容。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            target="target-A",
            receipt={"backend_revision": "1", "target": "target-A"},
            policy_network=[],
        )
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["revision_mismatch"]

    tenant_legacy = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant_legacy)
        dep, _, _ = _seed(session, tenant_legacy, target="target-A", receipt_rev="1", policy_network=[])
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant_legacy), dep_id) == []


_NEAR_MATCH_RECEIPT_TARGETS = [
    pytest.param("target-A ", id="trailing-space"),
    pytest.param(" target-A", id="leading-space"),
    pytest.param("target-a", id="lowercase"),
    pytest.param("TARGET-A", id="uppercase"),
    pytest.param("target-B", id="other-target"),
]


@pytest.mark.parametrize("target", _NEAR_MATCH_RECEIPT_TARGETS)
def test_receipt_target_is_compared_verbatim(client, monkeypatch, target):
    """原值比较：不 trim、不 lowercase、不重定向到本部署目标。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            target="target-A",
            receipt={"backend_revision": "1", "target": target},
            policy_network=[],
        )
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["unreadable"]


_ILLEGAL_RECEIPT_TARGETS = [
    pytest.param("", id="empty"),
    pytest.param("   ", id="blank"),
    pytest.param(7, id="number"),
    pytest.param(["target-A"], id="list"),
    pytest.param("x" * 200, id="oversized"),
]


@pytest.mark.parametrize("target", _ILLEGAL_RECEIPT_TARGETS)
def test_malformed_receipt_target_is_unusable(client, monkeypatch, target):
    """回执 target 显式出现但不是可用标识 → 该回执不是可核对证据。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            target="target-A",
            receipt={"backend_revision": "1", "target": target},
            policy_network=[],
        )
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == ["unreadable"]


# 显式非法 effect：未知字符串/空串/大小写变体/非字符串。合法 allow、合法 deny 与
# 缺省键（既有模型按"非 deny 即 allow"处理）不在此列表内。
_ILLEGAL_EFFECTS = [
    pytest.param("unexpected", id="unknown-string"),
    pytest.param("", id="empty-string"),
    pytest.param("ALLOW", id="uppercase-allow"),
    pytest.param("Allow", id="titlecase-allow"),
    pytest.param("DENY", id="uppercase-deny"),
    pytest.param("allow ", id="allow-trailing-space"),
    pytest.param(7, id="number"),
    pytest.param(True, id="bool"),
    pytest.param(None, id="null"),
    pytest.param(["allow"], id="list"),
    pytest.param({"kind": "allow"}, id="object"),
]


@pytest.mark.parametrize("effect", _ILLEGAL_EFFECTS)
def test_illegal_desired_effect_is_unusable_evidence(client, monkeypatch, effect):
    """复现问题 2：非法 effect 行不得被当作允许规则参与比对（判该维度不可用）。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": effect}])
        dep_id = dep.id
        session.commit()

    kinds = _kinds(_run(tenant), dep_id)
    assert kinds == ["unreadable"], kinds
    assert "missing_rules" not in kinds


def test_illegal_desired_effect_does_not_fabricate_extra_rules(client, monkeypatch):
    """非法 effect 行不得被静默丢弃（否则会伪造"后端存在未登记规则"）。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "unexpected"}])
        dep_id = dep.id
        session.commit()

    kinds = _kinds(_run(tenant), dep_id)
    assert kinds == ["unreadable"], kinds
    assert "undeclared_rules" not in kinds


@pytest.mark.parametrize("effect", _ILLEGAL_EFFECTS)
def test_illegal_readback_effect_is_unusable_evidence(client, monkeypatch, effect):
    """读回侧非法 effect：不得当成允许、也不得静默跳过（跳过会伪造缺失规则）。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _LOCAL_ENDPOINT, "effect": effect}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}])
        dep_id = dep.id
        session.commit()

    kinds = _kinds(_run(tenant), dep_id)
    assert kinds == ["unreadable"], kinds
    assert "missing_rules" not in kinds


def test_legal_effects_and_missing_key_keep_legacy_model(client, monkeypatch):
    """显式 allow / 显式 deny / 缺省键语义不变（不因加校验误拒合法记录）。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_network=[{"endpoint": _LOCAL_ENDPOINT}])
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant), dep_id) == []

    tenant_default_rule = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant_default_rule)
        dep, _, _ = _seed(session, tenant_default_rule, policy_network=[{"endpoint": _LOCAL_ENDPOINT}])
        dep_id = dep.id
        session.commit()
    assert _kinds(_run(tenant_default_rule), dep_id) == ["missing_rules"]


def test_conflicting_receipt_target_never_echoed(client, tenant_a, monkeypatch):
    """错配回执 target 原文不进入响应、Finding、审计与 outbox。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(
            session,
            tenant,
            target="target-A",
            receipt={"backend_revision": "1", "target": _SECRET_MARKER},
            policy_network=[],
        )
        dep_id = dep.id
        session.commit()

    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant}
    resp = client.post("/api/v1/permissions/check-drift", headers=headers)
    assert resp.status_code == 200, resp.text
    assert _SECRET_MARKER not in resp.text
    entry = next(r for r in resp.json()["drift_results"] if r["deployment_id"] == dep_id)
    assert entry["kind"] == "unreadable"

    with session_scope() as session:
        for finding in session.query(Finding).filter(Finding.resource_ref == f"deployment:{dep_id}").all():
            assert _SECRET_MARKER not in str(finding.impact)
            assert _SECRET_MARKER not in str(finding.risk_acceptance)
        for row in session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant).all():
            assert _SECRET_MARKER not in str(row.summary)
        for row in session.query(OutboxEvent).filter(OutboxEvent.tenant_id == tenant).all():
            assert _SECRET_MARKER not in str(row.payload)


def test_illegal_effect_value_never_echoed(client, monkeypatch):
    """非法 effect 原文不进入结果、Finding、审计与 outbox。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep, _, _ = _seed(session, tenant, policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": _SECRET_MARKER}])
        dep_id = dep.id
        session.commit()

    results, _ = _run_and_persist(tenant)
    assert _kinds(results, dep_id) == ["unreadable"]
    assert _SECRET_MARKER not in str(results)

    with session_scope() as session:
        findings = session.query(Finding).filter(Finding.resource_ref == f"deployment:{dep_id}").all()
        assert findings, "unreadable 结果应经既有路径落 Finding"
        for finding in findings:
            assert _SECRET_MARKER not in str(finding.impact)
            assert _SECRET_MARKER not in str(finding.risk_acceptance)
        audits = session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant).all()
        events = session.query(OutboxEvent).filter(OutboxEvent.tenant_id == tenant).all()
        assert audits and events
        for row in [*audits, *events]:
            text = str(getattr(row, "summary", "")) + str(getattr(row, "payload", ""))
            assert _SECRET_MARKER not in text
