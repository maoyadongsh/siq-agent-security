"""同一部署的漂移风险聚合边界测试（CL-05-DRIFT-FINDING-AGGREGATION）。

只针对 `app.drift.upsert_drift_findings` 的既有落库问题（保留"每部署一个 open Finding"模型），
不涉及检测规则或证据校验（那部分已验收，本文件不改）：

- 输入顺序（真实函数产出的多条结果按不同排列传入）不得改变最终严重级别与代表证据；
- 代表项的 severity/summary/details 必须来自同一条结果，不得拼接不同风险；
- 已有 open Finding 更新后摘要与详情仍同源，且不因本轮级别更低而自动降级；
- created/updated 按本次实际创建/更新的 Finding 数计（同部署同轮只计一次）；
- 重复相同输入不新增 open Finding；空输入不改动任何状态（含审计/outbox）；
- 不同部署、不同租户互不影响；租户限定保持；
- 聚合函数不得原地改写调用方传入的 results（端点响应仍要返回全部结果）；
- 审计失败回滚状态与 outbox。

结果由真实 `check_policy_drift` 在隔离 SQLite + 模拟适配器下产生，再按排列重排输入，
不使用复制生产算法的自证断言。
"""

from __future__ import annotations

import itertools
import json
import uuid
from dataclasses import replace

import pytest

from app.adapters.openshell.contracts import PolicySnapshot
from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, DesiredPolicy, Finding, OutboxEvent, Tenant

_LOCAL_ENDPOINT = "api.example.com:443"
_EXTRA_ENDPOINT = "extra.example.com:443"
_MISSING_ENDPOINT = "missing.example.com:443"

_UNSET = object()


class _FakeBackend:
    """可控读回后端；默认与真实 CLI/HTTP/fake 后端一致地回显请求 target。"""

    def __init__(self, *, revision="1", network=None):
        self.revision = revision
        self.network = [] if network is None else network

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        return PolicySnapshot(target=target, revision=self.revision, network=self.network)


def _patch_backend(monkeypatch, backend) -> None:
    """drift 模块直接构造 CLI 后端：注入零参工厂。"""
    monkeypatch.setattr("app.drift.OpenShellCliBackend", lambda: backend)


def _tenant_id() -> str:
    return f"tnt-driftagg-{uuid.uuid4().hex[:8]}"


def _ensure_tenant(session, tenant_id: str) -> None:
    if session.query(Tenant).filter(Tenant.id == tenant_id).count() == 0:
        session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))


def _new_policy(session, tenant_id, *, network) -> DesiredPolicy:
    policy = DesiredPolicy(
        tenant_id=tenant_id,
        name=f"pol-{uuid.uuid4().hex[:8]}",
        selector={"agent_ids": ["agt_1"]},
        network=network,
        enforcement_mode="block",
        status="approved",
    )
    session.add(policy)
    session.flush()
    return policy


def _new_change_request(session, tenant_id, policy_id) -> ChangeRequest:
    cr = ChangeRequest(
        tenant_id=tenant_id,
        policy_id=policy_id,
        proposer_user_id="user-a",
        approver_user_id="user-b",
        status="effective",
        idempotency_key=f"ik-{uuid.uuid4().hex}",
    )
    session.add(cr)
    session.flush()
    return cr


def _seed(session, tenant_id, *, receipt=_UNSET, receipt_rev="1", policy_network=None) -> Deployment:
    """落库一条 effective 部署（同租户），默认回执 revision=1。"""
    policy = _new_policy(session, tenant_id, network=policy_network)
    cr = _new_change_request(session, tenant_id, policy.id)
    dep = Deployment(
        tenant_id=tenant_id,
        environment_id=f"env-{uuid.uuid4().hex[:8]}",
        change_request_id=cr.id,
        target=f"sandbox-{uuid.uuid4().hex[:8]}",
        to_revision="policy-1",
        receipt={"backend_revision": receipt_rev} if receipt is _UNSET else receipt,
        status="effective",
    )
    session.add(dep)
    session.flush()
    return dep


def _run_check(tenant_id):
    """真实 `check_policy_drift`：产出本轮该租户的全部结果。"""
    from app.drift import check_policy_drift

    with session_scope() as session:
        return check_policy_drift(session, tenant_id)


def _upsert(tenant_id, results):
    """真实 `upsert_drift_findings`（调用方负责事务，与端点和 worker 一致）。"""
    from app.drift import upsert_drift_findings

    with session_scope() as session:
        counts = upsert_drift_findings(session, tenant_id, results)
        session.flush()
        return counts


def _open_findings(tenant_id, dep_id):
    with session_scope() as session:
        return (
            session.query(Finding)
            .filter(
                Finding.tenant_id == tenant_id,
                Finding.rule_id == "policy-drift",
                Finding.resource_ref == f"deployment:{dep_id}",
                Finding.status == "open",
            )
            .all()
        )


def _only_open_finding(tenant_id, dep_id):
    findings = _open_findings(tenant_id, dep_id)
    assert len(findings) == 1, [f.id for f in findings]
    return findings[0]


def _kinds(results):
    return sorted(r.details.get("kind") for r in results)


def _triple(finding):
    """展示三件套：级别 + 摘要 + 详情（三者必须同源；详情序列化为可比对的稳定字符串）。"""
    return (
        finding.severity,
        finding.impact,
        json.dumps(dict(finding.risk_acceptance or {}), sort_keys=True, default=str),
    )


def _seed_high_and_medium(tenant: str):
    """一条部署在本轮同时产出 high revision_mismatch 与 medium undeclared_rules。"""
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()
    results = _run_check(tenant)
    assert _kinds(results) == ["revision_mismatch", "undeclared_rules"], _kinds(results)
    return dep_id, results


# ------------------------------------------------------------------ 顺序与级别


def test_drift_summary_tie_is_order_independent(client, monkeypatch):
    """同级、同 kind、同详情而摘要不同，创建与更新都应选择同一代表。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(session, tenant, policy_network=[])
        dep_id = dep.id
    original = _run_check(tenant)[0]
    rows = [replace(original, summary="B summary"), replace(original, summary="A summary")]
    for ordered in (rows, list(reversed(rows))):
        _upsert(tenant, ordered)
        finding = _only_open_finding(tenant, dep_id)
        assert finding.impact == "A summary"
        assert finding.risk_acceptance == original.details
        assert finding.severity == original.severity


@pytest.mark.parametrize("severity", ["unexpected", ""])
def test_drift_unknown_severity_creation_fails_closed(client, monkeypatch, severity):
    """新建不得持久化未知级别，前序部署的写入必须随调用方事务回滚。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        for _ in range(2):
            _seed(session, tenant, policy_network=[])
    rows = _run_check(tenant)
    assert len(rows) == 2
    rows[1] = replace(rows[1], severity=severity)
    with pytest.raises(ValueError, match="^drift_finding_severity_unavailable$"):
        _upsert(tenant, rows)
    with session_scope() as session:
        for model in (Finding, AuditEvent, OutboxEvent):
            assert session.query(model).filter(model.tenant_id == tenant).count() == 0


@pytest.mark.parametrize("reverse", [False, True], ids=["high-first", "medium-first"])
def test_result_order_does_not_downgrade_severity(client, monkeypatch, reverse):
    """复现主问题：medium 排在 high 之后（或前）都不得把最终级别压成 medium。"""
    tenant = _tenant_id()
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="2",
            network=[
                {"endpoint": _LOCAL_ENDPOINT, "effect": "allow"},
                {"endpoint": _EXTRA_ENDPOINT, "effect": "allow"},
            ],
        ),
    )
    dep_id, results = _seed_high_and_medium(tenant)
    ordered = list(reversed(results)) if reverse else results

    counts = _upsert(tenant, ordered)
    finding = _only_open_finding(tenant, dep_id)
    high = next(r for r in results if r.details.get("kind") == "revision_mismatch")
    # 先断语义（顺序不得改变级别与证据来源），再断计数
    assert finding.severity == "high"
    assert finding.risk_acceptance["kind"] == "revision_mismatch"
    # 三件套同源：摘要与详情必须来自同一条 high 结果
    assert finding.impact == high.summary
    assert finding.risk_acceptance == high.details
    assert counts == {"created": 1, "updated": 0}, counts


def test_all_permutations_of_three_results_persist_identically(client, monkeypatch):
    """同一组三条结果（unreadable/missing_rules/undeclared_rules）任意排列结果一致。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _EXTRA_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        for _ in range(6):
            _seed(
                session,
                tenant,
                receipt={"backend_revision": 7},  # 回执不可核对 → unreadable(medium)
                policy_network=[{"endpoint": _MISSING_ENDPOINT, "effect": "allow"}],
            )
        dep_ids = [dep.id for dep in session.query(Deployment).filter(Deployment.tenant_id == tenant).all()]
        session.commit()
    assert len(dep_ids) == 6

    results = _run_check(tenant)
    # 6 条部署 × (unreadable + missing_rules + undeclared_rules)
    assert _kinds(results) == sorted(
        ["unreadable", "missing_rules", "undeclared_rules"] * 6
    ), _kinds(results)
    by_deployment = {}
    for r in results:
        by_deployment.setdefault(r.deployment_id, []).append(r)
    assert len(by_deployment) == 6

    triples = set()
    orders = list(itertools.permutations(range(3)))
    for dep_id, order in zip(dep_ids, orders, strict=True):
        group = by_deployment[dep_id]
        _upsert(tenant, [group[i] for i in order])
        triples.add(_triple(_only_open_finding(tenant, dep_id)))

    assert len(triples) == 1, triples
    severity, impact, details_json = triples.pop()
    assert severity == "high"  # missing_rules 是唯一 high
    assert json.loads(details_json)["kind"] == "missing_rules"
    assert impact == next(r for r in results if r.details.get("kind") == "missing_rules").summary


@pytest.mark.parametrize("reverse", [False, True], ids=["missing-first", "revision-first"])
def test_same_level_representative_is_stable(client, monkeypatch, reverse):
    """同级不同 kind（missing_rules 与 revision_mismatch 都 high）：代表项选择与顺序无关。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _MISSING_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    results = _run_check(tenant)
    assert _kinds(results) == ["missing_rules", "revision_mismatch"], _kinds(results)
    ordered = list(reversed(results)) if reverse else results
    _upsert(tenant, ordered)

    finding = _only_open_finding(tenant, dep_id)
    # 稳定规则：级别最高者中按 kind 升序取第一条（missing_rules < revision_mismatch）
    representative = next(r for r in results if r.details.get("kind") == "missing_rules")
    assert finding.severity == "high"
    assert finding.risk_acceptance["kind"] == "missing_rules"
    assert finding.impact == representative.summary
    assert finding.risk_acceptance == representative.details


# -------------------------------------------------------------- 既有 Finding 更新


def test_lower_level_round_keeps_retained_evidence_and_level(client, monkeypatch):
    """历史 high + 本轮只有 medium：不降级，且保留的三件套仍同源（摘要不指向别的风险）。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    high_round = _run_check(tenant)
    assert _kinds(high_round) == ["revision_mismatch"], _kinds(high_round)
    assert _upsert(tenant, high_round) == {"created": 1, "updated": 0}
    first = _only_open_finding(tenant, dep_id)
    first_triple, first_id, first_seen = _triple(first), first.id, first.first_seen_at
    high_summary = next(r for r in high_round if r.details.get("kind") == "revision_mismatch").summary

    # 第二轮：回执与后端 revision 一致、后端多出未登记规则 → 只有 medium
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="1",
            network=[
                {"endpoint": _LOCAL_ENDPOINT, "effect": "allow"},
                {"endpoint": _EXTRA_ENDPOINT, "effect": "allow"},
            ],
        ),
    )
    medium_round = _run_check(tenant)
    assert _kinds(medium_round) == ["undeclared_rules"], _kinds(medium_round)
    counts = _upsert(tenant, medium_round)
    assert counts == {"created": 0, "updated": 1}, counts

    after = _only_open_finding(tenant, dep_id)
    assert after.id == first_id
    assert after.first_seen_at == first_seen
    assert after.status == "open"
    assert after.last_seen_at > first.last_seen_at
    assert _triple(after) == first_triple, "降级轮不得改写保留的级别/摘要/详情"
    assert after.severity == "high"
    assert after.impact == high_summary
    assert after.risk_acceptance["kind"] == "revision_mismatch"


def test_higher_level_round_updates_all_three_from_one_result(client, monkeypatch):
    """本轮级别更高时：severity/summary/details 一起换成同一条结果，不留旧摘要。"""
    tenant = _tenant_id()
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="1",
            network=[
                {"endpoint": _LOCAL_ENDPOINT, "effect": "allow"},
                {"endpoint": _EXTRA_ENDPOINT, "effect": "allow"},
            ],
        ),
    )
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    medium_round = _run_check(tenant)
    assert _kinds(medium_round) == ["undeclared_rules"], _kinds(medium_round)
    _upsert(tenant, medium_round)
    assert _only_open_finding(tenant, dep_id).severity == "medium"

    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    high_round = _run_check(tenant)
    assert _kinds(high_round) == ["missing_rules"], _kinds(high_round)
    assert _upsert(tenant, high_round) == {"created": 0, "updated": 1}

    finding = _only_open_finding(tenant, dep_id)
    representative = next(r for r in high_round if r.details.get("kind") == "missing_rules")
    assert finding.severity == "high"
    assert finding.impact == representative.summary
    assert finding.risk_acceptance == representative.details
    assert finding.risk_acceptance["kind"] == "missing_rules"


def test_out_of_band_higher_existing_level_is_not_overwritten(client, monkeypatch):
    """既有 open Finding 级别高于本轮（含带外写入的 critical）：保守保留，不改三件套。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _EXTRA_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    _upsert(tenant, _run_check(tenant))
    with session_scope() as session:
        finding = (
            session.query(Finding)
            .filter(Finding.resource_ref == f"deployment:{dep_id}", Finding.status == "open")
            .one()
        )
        finding.severity = "critical"
        session.commit()
        retained = _triple(finding)

    assert _upsert(tenant, _run_check(tenant)) == {"created": 0, "updated": 1}
    assert _triple(_only_open_finding(tenant, dep_id)) == retained


def test_unreadable_only_round_still_creates_medium_finding(client, monkeypatch):
    """既有语义保持：只有 unreadable 时仍落一条 medium Finding（不因此新增/删除枚举）。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(session, tenant, receipt={"backend_revision": 7}, policy_network=[])
        dep_id = dep.id
        session.commit()

    results = _run_check(tenant)
    assert _kinds(results) == ["unreadable"], _kinds(results)
    assert _upsert(tenant, results) == {"created": 1, "updated": 0}
    finding = _only_open_finding(tenant, dep_id)
    assert finding.severity == "medium"
    assert finding.risk_acceptance == results[0].details


# ------------------------------------------------------------ 计数与幂等


def test_multi_result_deployment_counts_once(client, monkeypatch):
    """同部署三条结果只计一次 created；重复相同输入只计一次 updated 且不新增 open Finding。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _EXTRA_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt={"backend_revision": 7},
            policy_network=[{"endpoint": _MISSING_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    results = _run_check(tenant)
    assert len(results) == 3, _kinds(results)
    assert _upsert(tenant, results) == {"created": 1, "updated": 0}
    assert _upsert(tenant, results) == {"created": 0, "updated": 1}
    assert len(_open_findings(tenant, dep_id)) == 1


def test_two_deployments_count_per_finding(client, monkeypatch):
    """不同部署各自计一次：2 条部署 × 每条 2 结果 → created=2，不是 4。"""
    tenant = _tenant_id()
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="2",
            network=[
                {"endpoint": _LOCAL_ENDPOINT, "effect": "allow"},
                {"endpoint": _EXTRA_ENDPOINT, "effect": "allow"},
            ],
        ),
    )
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        first = _seed(
            session, tenant, receipt_rev="1", policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}]
        )
        second = _seed(
            session, tenant, receipt_rev="1", policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}]
        )
        first_id, second_id = first.id, second.id
        session.commit()

    results = _run_check(tenant)
    assert len(results) == 4, _kinds(results)
    assert _upsert(tenant, results) == {"created": 2, "updated": 0}
    for dep_id in (first_id, second_id):
        assert _only_open_finding(tenant, dep_id).severity == "high"


def test_empty_results_do_not_touch_any_state(client, monkeypatch):
    """空输入：不改状态、不写审计/outbox、计数为 0。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _EXTRA_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    _upsert(tenant, _run_check(tenant))
    before = _triple(_only_open_finding(tenant, dep_id))
    with session_scope() as session:
        counts_before = (
            session.query(Finding).filter(Finding.tenant_id == tenant).count(),
            session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant).count(),
            session.query(OutboxEvent).filter(OutboxEvent.tenant_id == tenant).count(),
        )

    assert _upsert(tenant, []) == {"created": 0, "updated": 0}

    with session_scope() as session:
        counts_after = (
            session.query(Finding).filter(Finding.tenant_id == tenant).count(),
            session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant).count(),
            session.query(OutboxEvent).filter(OutboxEvent.tenant_id == tenant).count(),
        )
    assert counts_after == counts_before
    assert _triple(_only_open_finding(tenant, dep_id)) == before


# ------------------------------------------------------------ 租户与输入不变性


def test_other_tenant_same_resource_ref_is_not_touched(client, monkeypatch):
    """tenant 限定保持：同名 resource_ref 的其他租户 open Finding 不被读取或更新。"""
    tenant, other = _tenant_id(), _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="1", network=[{"endpoint": _EXTRA_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        _ensure_tenant(session, other)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        foreign = Finding(
            id=f"fnd_{uuid.uuid4().hex[:20]}",
            tenant_id=other,
            rule_id="policy-drift",
            rule_version=1,
            severity="high",
            domain="policy",
            resource_ref=f"deployment:{dep_id}",
            impact="其他租户的既有风险",
            status="open",
            risk_acceptance={"kind": "revision_mismatch", "backend": "9", "receipt": "8"},
        )
        session.add(foreign)
        session.commit()
        foreign_id, foreign_triple, foreign_last_seen = foreign.id, _triple(foreign), foreign.last_seen_at

    results = _run_check(tenant)
    assert _upsert(tenant, results) == {"created": 1, "updated": 0}

    with session_scope() as session:
        untouched = session.get(Finding, foreign_id)
        assert _triple(untouched) == foreign_triple
        assert untouched.last_seen_at == foreign_last_seen  # 未被当作"本轮已见过"
    assert len(_open_findings(tenant, dep_id)) == 1


def test_upsert_does_not_mutate_caller_results(client, monkeypatch):
    """聚合不得原地改写/重排调用方列表（端点响应仍要逐条返回全部结果）。"""
    tenant = _tenant_id()
    _patch_backend(monkeypatch, _FakeBackend(revision="2", network=[{"endpoint": _EXTRA_ENDPOINT, "effect": "allow"}]))
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _MISSING_ENDPOINT, "effect": "allow"}],
        )
        session.commit()

    results = _run_check(tenant)
    assert len(results) >= 3
    snapshot = [(id(r), r.deployment_id, r.severity, r.summary, dict(r.details)) for r in results]

    _upsert(tenant, results)

    assert [(id(r), r.deployment_id, r.severity, r.summary, dict(r.details)) for r in results] == snapshot


# ------------------------------------------------------------ 端点与事务边界


def test_endpoint_reports_all_results_but_persists_one_representative(client, tenant_a, monkeypatch):
    """真实端点：响应保留全部 drift_results，Finding 只落一条最高级别代表项。"""
    tenant = _tenant_id()
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="2",
            network=[
                {"endpoint": _LOCAL_ENDPOINT, "effect": "allow"},
                {"endpoint": _EXTRA_ENDPOINT, "effect": "allow"},
            ],
        ),
    )
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()

    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant}
    resp = client.post("/api/v1/permissions/check-drift", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {row["kind"] for row in body["drift_results"]} == {"revision_mismatch", "undeclared_rules"}
    assert body["created"] == 1
    assert body["updated"] == 0

    finding = _only_open_finding(tenant, dep_id)
    assert finding.severity == "high"
    assert finding.risk_acceptance["kind"] == "revision_mismatch"
    assert "revision" in finding.impact


def test_audit_failure_rolls_back_aggregated_write(client, tenant_a, monkeypatch):
    """审计失败：聚合写入整体回滚，不留孤立 Finding 与 outbox。"""
    tenant = _tenant_id()
    _patch_backend(
        monkeypatch,
        _FakeBackend(
            revision="2",
            network=[
                {"endpoint": _LOCAL_ENDPOINT, "effect": "allow"},
                {"endpoint": _EXTRA_ENDPOINT, "effect": "allow"},
            ],
        ),
    )
    with session_scope() as session:
        _ensure_tenant(session, tenant)
        dep = _seed(
            session,
            tenant,
            receipt_rev="1",
            policy_network=[{"endpoint": _LOCAL_ENDPOINT, "effect": "allow"}],
        )
        dep_id = dep.id
        session.commit()
    with session_scope() as session:
        before = tuple(
            session.query(model).filter(model.tenant_id == tenant).count()
            for model in (Finding, AuditEvent, OutboxEvent)
        )

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic drift aggregation audit failure")

    monkeypatch.setattr("app.drift.audit", fail)
    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant}
    with pytest.raises(RuntimeError, match="synthetic drift aggregation audit failure"):
        client.post("/api/v1/permissions/check-drift", headers=headers)

    with session_scope() as session:
        after = tuple(
            session.query(model).filter(model.tenant_id == tenant).count()
            for model in (Finding, AuditEvent, OutboxEvent)
        )
        assert after == before
        assert _open_findings(tenant, dep_id) == []
