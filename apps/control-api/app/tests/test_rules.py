"""规则引擎与 Worker 测试（设计文档 §13.1）。

覆盖：无主资产、心跳过期、凭据共用、无有效权限、风险接受到期重开、幂等。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import session_scope
from app.models import (
    AgentAsset,
    AuditEvent,
    Environment,
    Evidence,
    Finding,
    OutboxEvent,
    PermissionFact,
    Tenant,
    utcnow,
)
from app.rules import evaluate_all, upsert_findings
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence
from app.worker import once


def _seed_asset(session, tenant_id, name="rules-agent", status="confirmed", owner=None):
    asset = AgentAsset(
        tenant_id=tenant_id,
        name=name,
        framework="hermes",
        status=status,
        owner_user_id=owner,
        source_type="siq_hub",
        source_locator=f"hub://{name}",
    )
    session.add(asset)
    session.flush()
    return asset


def _seed_permission(session, tenant_id, subject_id, domain="credential", value="secret:vault-1"):
    session.add(
        PermissionFact(
            tenant_id=tenant_id,
            subject_type="agent_asset",
            subject_id=subject_id,
            domain=domain,
            action="use",
            resource_type="credential_ref",
            resource_value=value,
            effect="allow",
            state="declared",
            authority="edge-connector",
            evidence_ids=[],
        )
    )


def _ensure_tenant(session, tenant_id):
    if session.query(Tenant).filter(Tenant.id == tenant_id).count() == 0:
        session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))
    session.commit()


def test_unowned_confirmed_agent_rule(client, tenant_a):
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        _seed_asset(session, "tnt-A", owner=None)
        session.commit()
        results = evaluate_all(session, "tnt-A")
        assert any(r.rule_id == "unowned-confirmed-agent" and r.severity == "high" for r in results)
        counts = upsert_findings(session, "tnt-A", results)
        assert counts["created"] >= 1
        session.commit()
        # 幂等：再跑一轮不重复创建
        again = upsert_findings(session, "tnt-A", evaluate_all(session, "tnt-A"))
        assert again["created"] == 0


def test_owned_asset_no_rule(client, tenant_a):
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        _seed_asset(session, "tnt-A", name="owned-agent", owner="user-a")
        session.commit()
        results = evaluate_all(session, "tnt-A")
        assert not any(
            r.rule_id == "unowned-confirmed-agent" and r.asset_id and "owned-agent" in r.asset_id for r in results
        )


def test_stale_environment_rule(client, tenant_a):
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        env = Environment(
            tenant_id="tnt-A",
            name="stale-env",
            last_heartbeat_at=utcnow() - timedelta(hours=1),
        )
        session.add(env)
        session.commit()
        results = evaluate_all(session, "tnt-A")
        assert any(r.rule_id == "stale-environment-heartbeat" for r in results)


def test_shared_credential_rule(client, tenant_a):
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        a1 = _seed_asset(session, "tnt-A", name="agent-1")
        a2 = _seed_asset(session, "tnt-A", name="agent-2")
        _seed_permission(session, "tnt-A", a1.id)
        _seed_permission(session, "tnt-A", a2.id)
        session.commit()
        results = evaluate_all(session, "tnt-A")
        assert any(r.rule_id == "shared-credential" and r.severity == "high" for r in results)


def test_no_effective_permissions_rule(client, tenant_a):
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        _seed_asset(session, "tnt-A", name="noeff-agent", owner="user-a")
        session.commit()
        results = evaluate_all(session, "tnt-A")
        assert any(r.rule_id == "no-effective-permissions" and r.severity == "info" for r in results)


def test_run_rules_endpoint_idempotent(client, tenant_a):
    resp1 = client.post("/api/v1/findings/run-rules", json={}, headers=tenant_a)
    assert resp1.status_code == 200
    resp2 = client.post("/api/v1/findings/run-rules", json={}, headers=tenant_a)
    assert resp2.status_code == 200
    assert resp2.json()["created"] == 0


def test_worker_once_reaps_expired_risk_acceptance(client, tenant_a):
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        asset = _seed_asset(session, "tnt-A", name="reap-agent")
        session.commit()
        finding = Finding(
            tenant_id="tnt-A",
            rule_id="manual-test",
            rule_version=1,
            severity="low",
            asset_id=asset.id,
            status="risk_accepted",
            owner_user_id="user-a",
            risk_acceptance={"reason": "test", "expires_at": (utcnow() - timedelta(minutes=1)).isoformat()},
        )
        session.add(finding)
        session.commit()
    summary = once()
    assert summary["reaped"] == 1
    with session_scope() as session:
        finding = session.query(Finding).filter(Finding.rule_id == "manual-test").one()
        assert finding.status == "open"


def test_edge_cannot_assert_effective_permission(client, tenant_a, env_a):
    """安全不变量：effective 只能来自权威源，Edge 上传标记 effective 的权限事实必须 422。"""
    identity = "edge-pf-test"
    eh, private_key = register_edge(client, tenant_a, env_a["id"], identity)
    task_id = create_scan_task(client, tenant_a, env_a["id"])
    evidence = signed_evidence(private_key, identity, "ev-pf-test")
    cand = candidate("pf-test", ["ev-pf-test"])
    permission = {
        "subject": {"type": "agent_asset", "id": "hermes_profile:pf-test"},
        "domain": "network",
        "action": "http.request",
        "resource": {"type": "endpoint", "value": "api.example.com"},
        "effect": "allow",
        "state": "effective",
        "authority": "edge",
        "evidence_ids": ["ev-pf-test"],
    }
    bad = client.post(
        "/edge/v1/batches",
        json=signed_batch(
            private_key,
            task_id,
            candidates=[cand],
            evidence=[evidence],
            permission_facts=[permission],
        ),
        headers=eh,
    )
    assert bad.status_code == 422
    assert "edge_cannot_assert_effective" in bad.json()["detail"]

    permission["state"] = "declared"
    permission["authority"] = "edge-connector"
    permission["subject"]["id"] = "hermes_profile:not-in-batch"
    missing_subject = client.post(
        "/edge/v1/batches",
        json=signed_batch(
            private_key,
            task_id,
            candidates=[cand],
            evidence=[evidence],
            permission_facts=[permission],
        ),
        headers=eh,
    )
    assert missing_subject.status_code == 422
    assert missing_subject.json()["detail"] == "permission_subject_candidate_missing"

    permission["subject"]["id"] = cand["candidate_id"]
    good = client.post(
        "/edge/v1/batches",
        json=signed_batch(
            private_key,
            task_id,
            candidates=[cand],
            evidence=[evidence],
            permission_facts=[permission],
        ),
        headers=eh,
    )
    assert good.status_code == 200
    assert good.json()["permission_facts"] == 1
    asset = next(
        item
        for item in client.get("/api/v1/candidates", headers=tenant_a).json()
        if item["name"] == "pf-test"
    )
    facts = client.get(f"/api/v1/agents/{asset['id']}/permissions", headers=tenant_a).json()
    assert len(facts) == 1
    assert facts[0]["subject_id"] == asset["id"]
    assert facts[0]["environment_id"] == env_a["id"]


def test_edge_evidence_and_permissions_are_bound_to_source_environment(client, tenant_a):
    """两个环境生成相同外部 evidence_id/hash 时，各自观察与权限事实都必须保留。"""
    envs = [
        client.post("/api/v1/environments", json={"name": f"env-binding-{idx}"}, headers=tenant_a).json()
        for idx in range(2)
    ]
    for idx, env in enumerate(envs):
        identity = f"edge-binding-{idx}"
        edge_headers, private_key = register_edge(client, tenant_a, env["id"], identity)
        task_id = create_scan_task(client, tenant_a, env["id"])
        evidence = signed_evidence(
            private_key,
            identity,
            "ev-shared-across-environments",
            content_hash="d" * 64,
        )
        cand = candidate(f"binding-{idx}", [evidence["evidence_id"]])
        permission = {
            "subject": {"type": "agent_asset", "id": cand["candidate_id"]},
            "domain": "network",
            "action": "http.request",
            "resource": {"type": "endpoint", "value": "api.example.com"},
            "effect": "allow",
            "state": "declared",
            "authority": "edge-connector",
            "evidence_ids": [evidence["evidence_id"]],
        }
        response = client.post(
            "/edge/v1/batches",
            json=signed_batch(
                private_key,
                task_id,
                candidates=[cand],
                evidence=[evidence],
                permission_facts=[permission],
            ),
            headers=edge_headers,
        )
        assert response.status_code == 200, response.text

    for env in envs:
        facts = client.get(
            "/api/v1/permissions",
            params={"environment_id": env["id"]},
            headers=tenant_a,
        ).json()
        assert len(facts) == 1
        assert facts[0]["environment_id"] == env["id"]

    with session_scope() as session:
        observations = session.query(Evidence).filter(
            Evidence.tenant_id == "tnt-A",
            Evidence.evidence_id == "ev-shared-across-environments",
        ).all()
        assert {item.environment_id for item in observations} == {env["id"] for env in envs}


def _make_named_candidate(client, headers, name):
    env = client.post("/api/v1/environments", json={"name": f"env-cls-{name}"}, headers=headers).json()
    identity = f"edge-cls-{name}"
    eh, private_key = register_edge(client, headers, env["id"], identity)
    task_id = create_scan_task(client, headers, env["id"])
    evidence_id = f"ev-cls-{name}"
    evidence = signed_evidence(private_key, identity, evidence_id)
    resp = client.post(
        "/edge/v1/batches",
        json=signed_batch(
            private_key,
            task_id,
            candidates=[candidate(name, [evidence_id])],
            evidence=[evidence],
        ),
        headers=eh,
    )
    assert resp.status_code == 200, resp.text
    assets = client.get("/api/v1/candidates", headers=headers).json()
    return next(a for a in assets if a["name"] == name)


def test_baseline_classify_known_role(client, tenant_a):
    """确定性基线：名称含 legal → legal-advisor，高置信不转 needs_review，落 classification_run。"""
    asset = _make_named_candidate(client, tenant_a, "legal-advisor")
    resp = client.post(f"/api/v1/candidates/{asset['id']}/classify", json={}, headers=tenant_a)
    assert resp.status_code == 200
    body = resp.json()
    assert body["classifier"] == "baseline"
    assert body["output"]["is_agent_candidate"] is True
    assert body["output"]["role"]["value"] == "legal-advisor"
    assert body["asset_status"] == "candidate"  # 高置信仍为 candidate，绝不自动纳管
    with session_scope() as session:
        from app.models import ClassificationRun

        run = session.query(ClassificationRun).filter(ClassificationRun.id == body["classification_run_id"]).one()
        assert run.temperature == 0.0
        assert run.seed == 42


def test_baseline_low_confidence_needs_review(client, tenant_a):
    """低置信 → needs_review，进入人工确认（§11.3）。"""
    asset = _make_named_candidate(client, tenant_a, "some-random-name")
    resp = client.post(f"/api/v1/candidates/{asset['id']}/classify", json={}, headers=tenant_a)
    assert resp.status_code == 200
    assert resp.json()["asset_status"] == "needs_review"


def test_classify_never_auto_confirms(client, tenant_a):
    """分类不改变状态机到 confirmed（§11.2 模型禁止任务）。"""
    asset = _make_named_candidate(client, tenant_a, "finance-auditor")
    client.post(f"/api/v1/candidates/{asset['id']}/classify", json={}, headers=tenant_a)
    refreshed = client.get(f"/api/v1/agents/{asset['id']}", headers=tenant_a).json()
    assert refreshed["status"] in ("candidate", "needs_review")


def test_finding_lifecycle_acknowledge_resolve(client, tenant_a):
    """Finding 生命周期：open → acknowledged → resolved（§13.2）。"""
    client.post("/api/v1/findings/run-rules", json={}, headers=tenant_a)
    finding = client.get("/api/v1/findings", headers=tenant_a).json()[0]
    assert finding["status"] == "open"

    ack = client.post(f"/api/v1/findings/{finding['id']}/acknowledge", json={}, headers=tenant_a)
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"

    missing_evidence = client.post(
        f"/api/v1/findings/{finding['id']}/resolve", json={}, headers=tenant_a
    )
    assert missing_evidence.status_code == 422

    res = client.post(
        f"/api/v1/findings/{finding['id']}/resolve",
        json={"evidence_ref": "repair-ticket:SEC-123"},
        headers=tenant_a,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "resolved"
    with session_scope() as session:
        finding_row = session.get(Finding, finding["id"])
        assert finding_row is not None
        assert finding_row.risk_acceptance == {
            "resolved_by": "user-a",
            "evidence_ref": "repair-ticket:SEC-123",
        }
        audit_row = session.query(AuditEvent).filter(AuditEvent.resource_id == finding["id"]).order_by(
            AuditEvent.created_at.desc()
        ).first()
        assert audit_row is not None
        assert audit_row.summary == {"evidence_ref": "repair-ticket:SEC-123"}
        event = next(
            row
            for row in session.query(OutboxEvent)
            .filter(OutboxEvent.event_type == "agent.finding.resolved.v1")
            .all()
            if row.payload.get("resource_ref") == finding["id"]
        )
        assert event.payload["payload"]["finding_id"] == finding["id"]

    # 重复解决：409
    again = client.post(
        f"/api/v1/findings/{finding['id']}/resolve",
        json={"evidence_ref": "repair-ticket:SEC-123"},
        headers=tenant_a,
    )
    assert again.status_code == 409


def test_scan_quota_per_tenant(client, tenant_a, env_a):
    """威胁 T19：每租户 pending 扫描任务上限（默认 50），超限 429。

    共享测试库中其他用例可能遗留 pending 扫描任务，故按"剩余额度"计算。
    """
    from sqlalchemy import select

    from app.config import load_settings
    from app.db import session_scope
    from app.models import EdgeTask, Environment

    quota = load_settings().scan_quota_per_tenant
    with session_scope() as s:
        env_ids = list(s.scalars(select(Environment.id).where(Environment.tenant_id == "tnt-A")))
        pre = s.query(EdgeTask).filter(
            EdgeTask.task_type == "scan",
            EdgeTask.status == "pending",
            EdgeTask.environment_id.in_(env_ids),
        ).count()
    remaining = max(quota - pre, 0)
    created_task_ids = []
    for i in range(remaining):
        resp = client.post("/api/v1/scans", json={"environment_id": env_a["id"], "scope": {"n": i}}, headers=tenant_a)
        assert resp.status_code == 200, f"quota loop {i}/{remaining}: {resp.text}"
        created_task_ids.append(resp.json()["task_id"])
    over = client.post("/api/v1/scans", json={"environment_id": env_a["id"], "scope": {}}, headers=tenant_a)
    assert over.status_code == 429
    assert "scan_quota_exceeded" in over.json()["detail"]
    with session_scope() as s:
        s.query(EdgeTask).filter(EdgeTask.id.in_(created_task_ids)).update(
            {EdgeTask.status: "failed"}, synchronize_session=False
        )
        s.commit()


def test_cursor_pagination_agents(client, tenant_a):
    """§18.1 稳定游标分页：limit + cursor 全量无重复。"""
    for i in range(5):
        env = client.post("/api/v1/environments", json={"name": f"env-pg-{i}"}, headers=tenant_a).json()
        identity = f"edge-pg-{i}"
        eh, private_key = register_edge(client, tenant_a, env["id"], identity)
        task_id = create_scan_task(client, tenant_a, env["id"])
        evidence_id = f"ev-pg-{i}"
        evidence = signed_evidence(private_key, identity, evidence_id)
        client.post(
            "/edge/v1/batches",
            json=signed_batch(
                private_key,
                task_id,
                candidates=[candidate(f"pg-agent-{i}", [evidence_id])],
                evidence=[evidence],
            ),
            headers=eh,
        )
    seen: list[str] = []
    cursor = None
    while True:
        page = client.get("/api/v1/candidates", params={"limit": 2, "cursor": cursor}, headers=tenant_a).json()
        if not page:
            break
        seen.extend(a["id"] for a in page)
        last = page[-1]
        cursor = f"{last['updated_at']}|{last['id']}"
    assert len(seen) == len(set(seen)), "游标分页出现重复"
    assert len(seen) >= 5


def test_worker_reopens_expired_dismissal(client, tenant_a):
    """§10.4：dismissed 有效期到期自动重开为 candidate。"""
    from datetime import timedelta

    from app.db import session_scope as ss
    from app.models import AgentAsset
    from app.models import utcnow as now_fn

    with ss() as s:
        _ensure_tenant(s, "tnt-A")
        asset = AgentAsset(
            tenant_id="tnt-A",
            name="dismiss-me",
            framework="hermes",
            status="dismissed",
            dismissed_reason="误判",
            dismissed_expires_at=now_fn() - timedelta(minutes=1),
            source_type="siq_hub",
            source_locator="hub://dismiss-me",
        )
        s.add(asset)
        s.commit()
    summary = once()
    assert summary["dismissals"] == 1
    with ss() as s:
        a = s.query(AgentAsset).filter(AgentAsset.name == "dismiss-me").one()
        assert a.status == "candidate"
        assert a.dismissed_expires_at is None


def test_sync_openshell_writes_effective_facts(client, tenant_a, env_a, monkeypatch):
    """真实 OpenShell 域 Resolver：有效策略 → PermissionFact(state=effective, authority=openshell)。"""
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.tests.test_openshell_cli_backend import GATEWAY_INFO, REAL_POLICY_GET_FULL

    class FakeCliBackend(OpenShellCliBackend):
        def __init__(self):
            super().__init__(
                runner=self._fake_runner,
                env_script="/nonexistent",
                docker_runner=lambda args: (0, "openshell-demo-sandbox-8515c645-1682-4814-965d-e6b330e2af2e\n", ""),
            )

        def _fake_runner(self, args):
            if tuple(args[:2]) == ("sandbox", "list"):
                return 1, "", "protobuf decode error"
            if tuple(args[:2]) == ("policy", "get") and "--full" in args:
                return 0, REAL_POLICY_GET_FULL, ""
            if tuple(args[:2]) == ("gateway", "info"):
                return 0, GATEWAY_INFO, ""
            return 1, "", f"unexpected: {args}"

    monkeypatch.setattr("app.openshell_sync.OpenShellCliBackend", FakeCliBackend)
    with session_scope() as session:
        _seed_effective_deployment(
            session,
            "tnt-A",
            environment_id=env_a["id"],
            target="demo-sandbox",
        )
        session.commit()
    resp = client.post(
        "/api/v1/permissions/sync-openshell",
        params={"environment_id": env_a["id"]},
        json={},
        headers=tenant_a,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["targets"] == 1
    assert body["facts"] >= 10  # 7 只读路径 + 3 可写路径 + 进程身份

    with session_scope() as session:
        from app.models import PermissionFact

        facts = session.query(PermissionFact).filter(
            PermissionFact.authority == "openshell",
            PermissionFact.environment_id == env_a["id"],
        ).all()
        assert all(f.state == "effective" for f in facts)
        assert any(f.domain == "filesystem" and f.resource_value == "/usr" for f in facts)
        assert any(f.domain == "process" and f.resource_value == "sandbox:sandbox" for f in facts)


def test_sync_openshell_unreachable_fails_closed(client, tenant_a, env_a, monkeypatch):
    """网关不可达 → 502，绝不产出空权限冒充安全状态（§23.2）。"""
    from app.adapters.openshell.contracts import AdapterError

    class DeadBackend:
        def list_targets(self):
            raise AdapterError("gateway down")

    monkeypatch.setattr("app.openshell_sync.OpenShellCliBackend", DeadBackend)
    resp = client.post(
        "/api/v1/permissions/sync-openshell",
        params={"environment_id": env_a["id"]},
        json={},
        headers=tenant_a,
    )
    assert resp.status_code == 502
    assert "openshell_unreachable" in resp.json()["detail"]


def test_permissions_list_tenant_isolation_and_filters(client, tenant_a, tenant_b):
    """权限列表：权威源/域/状态过滤 + 跨租户不可见。"""
    from app.db import session_scope as ss
    from app.models import PermissionFact

    with ss() as s:
        s.add(
            PermissionFact(
                tenant_id="tnt-A",
                subject_type="openshell_sandbox",
                subject_id="sandbox:a",
                domain="network",
                action="http.request",
                resource_type="endpoint",
                resource_value="api.example.com:443",
                effect="allow",
                state="effective",
                authority="openshell",
                authority_revision="2",
                evidence_ids=[],
            )
        )
        s.commit()

    resp = client.get(
        "/api/v1/permissions", params={"authority": "openshell", "state": "effective"}, headers=tenant_a
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["resource_value"] == "api.example.com:443" for r in rows)

    # 跨租户不可见
    resp_b = client.get("/api/v1/permissions", params={"authority": "openshell"}, headers=tenant_b)
    assert all(r["resource_value"] != "api.example.com:443" for r in resp_b.json())


def _seed_effective_deployment(
    session,
    tenant_id,
    target="sandbox:t1",
    receipt_rev="1",
    environment_id="env-x",
):
    from app.models import ChangeRequest, Deployment, DesiredPolicy

    policy = DesiredPolicy(
        tenant_id=tenant_id,
        name=f"drift-policy-{target}",
        selector={"agent_ids": ["a"]},
        network=[{"endpoint": "api.example.com:443", "effect": "allow"}],
        enforcement_mode="block",
        status="approved",
    )
    session.add(policy)
    session.flush()
    cr = ChangeRequest(
        tenant_id=tenant_id,
        policy_id=policy.id,
        proposer_user_id="u1",
        approver_user_id="u2",
        status="effective",
        idempotency_key=f"drift-ik-{target}",
    )
    session.add(cr)
    session.flush()
    dep = Deployment(
        tenant_id=tenant_id,
        environment_id=environment_id,
        change_request_id=cr.id,
        target=target,
        to_revision="policy-1",
        status="effective",
        receipt={"backend_revision": receipt_rev},
    )
    session.add(dep)
    session.flush()
    return dep


def test_drift_revision_mismatch_creates_high_finding(client, tenant_a, monkeypatch):
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.contracts import PolicySnapshot

    class Fake(OpenShellCliBackend):
        def __init__(self):
            super().__init__(runner=lambda a: (1, "", "unused"), env_script="/n")

        def read_effective_policy(self, target):
            return PolicySnapshot(
                target=target,
                revision="2",  # 与回执 1 不一致（带外变更）
                network=[{"endpoint": "api.example.com:443", "effect": "allow"}],
            )

    monkeypatch.setattr("app.drift.OpenShellCliBackend", Fake)
    with session_scope() as s:
        _ensure_tenant(s, "tnt-A")
        _seed_effective_deployment(s, "tnt-A")
        s.commit()
        from app.drift import check_policy_drift, upsert_drift_findings

        results = check_policy_drift(s, "tnt-A")
        assert any(r.kind if hasattr(r, "kind") else r.details.get("kind") == "revision_mismatch" for r in results)
        counts = upsert_drift_findings(s, "tnt-A", results)
        assert counts["created"] >= 1
        s.commit()
        from app.models import Finding

        f = s.query(Finding).filter(Finding.rule_id == "policy-drift", Finding.severity == "high").first()
        assert f is not None and f.severity == "high"


def test_drift_missing_rules_detected(client, tenant_a, monkeypatch):
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.contracts import PolicySnapshot

    class Fake(OpenShellCliBackend):
        def __init__(self):
            super().__init__(runner=lambda a: (1, "", "unused"), env_script="/n")

        def read_effective_policy(self, target):
            return PolicySnapshot(target=target, revision="1", network=[])  # 期望规则缺失

    monkeypatch.setattr("app.drift.OpenShellCliBackend", Fake)
    with session_scope() as s:
        _ensure_tenant(s, "tnt-A")
        _seed_effective_deployment(s, "tnt-A", target="sandbox:t2")
        s.commit()
        from app.drift import check_policy_drift

        results = check_policy_drift(s, "tnt-A")
        kinds = [r.details.get("kind") for r in results]
        assert "missing_rules" in kinds


def test_drift_unreadable_target_fails_closed(client, tenant_a, monkeypatch):
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.contracts import AdapterError

    class Fake(OpenShellCliBackend):
        def __init__(self):
            super().__init__(runner=lambda a: (1, "", "unused"), env_script="/n")

        def read_effective_policy(self, target):
            raise AdapterError("no policy revision; token=should-never-persist")

    monkeypatch.setattr("app.drift.OpenShellCliBackend", Fake)
    with session_scope() as s:
        _ensure_tenant(s, "tnt-A")
        _seed_effective_deployment(s, "tnt-A", target="sandbox:gone")
        s.commit()
        from app.drift import check_policy_drift

        results = check_policy_drift(s, "tnt-A")
        unreadable = next(r for r in results if r.details.get("kind") == "unreadable")
        assert "should-never-persist" not in str(unreadable)
        assert len(unreadable.details["error_digest"]) == 64


def test_drift_consistent_no_findings(client, tenant_a, monkeypatch):
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.contracts import PolicySnapshot

    class Fake(OpenShellCliBackend):
        def __init__(self):
            super().__init__(runner=lambda a: (1, "", "unused"), env_script="/n")

        def read_effective_policy(self, target):
            return PolicySnapshot(
                target=target, revision="1", network=[{"endpoint": "api.example.com:443", "effect": "allow"}]
            )

    monkeypatch.setattr("app.drift.OpenShellCliBackend", Fake)
    with session_scope() as s:
        _ensure_tenant(s, "tnt-A")
        dep = _seed_effective_deployment(s, "tnt-A", target="sandbox:t4")
        s.commit()
        from app.drift import check_policy_drift

        results = check_policy_drift(s, "tnt-A")
        # 共享库中其他用例的旧部署可能漂移；只断言本部署无漂移
        assert not any(r.deployment_id == dep.id for r in results)


def test_permissions_diff_declared_vs_effective(client, tenant_a):
    """§12.4 Diff：声明与有效按 (domain, action, resource) 对比。"""
    from app.db import session_scope as ss
    from app.models import PermissionFact

    with ss() as s:
        for state, value in [
            ("declared", "api.example.com:443"),  # 声明了但无有效
            ("effective", "other.example.com:443"),  # 生效但未声明
            ("declared", "common.example.com:443"),
            ("effective", "common.example.com:443"),
        ]:
            s.add(
                PermissionFact(
                    tenant_id="tnt-A",
                    subject_type="agent_instance",
                    subject_id="inst-diff",
                    domain="network",
                    action="http.request",
                    resource_type="endpoint",
                    resource_value=value,
                    effect="allow",
                    state=state,
                    authority="edge-connector" if state == "declared" else "openshell",
                    evidence_ids=[],
                )
            )
        s.commit()

    resp = client.get(
        "/api/v1/permissions/diff", params={"subject_id": "inst-diff"}, headers=tenant_a
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(r["resource"] == "api.example.com:443" for r in body["declared_not_effective"])
    assert any(r["resource"] == "other.example.com:443" for r in body["effective_not_declared"])
    assert any(r["resource"] == "common.example.com:443" for r in body["consistent"])


def _provider_ok_response(content: dict) -> object:
    import json as _j

    return {"choices": [{"message": {"content": _j.dumps(content)}}]}


def test_provider_classify_happy_path(monkeypatch):
    """§11.4 provider 模式：OpenAI 兼容端点 + 严格输出解析。"""
    import httpx

    from app.classification import provider_classify
    from app.models import AgentAsset

    monkeypatch.setenv("SIQ_AS_CLASSIFIER_ENDPOINT", "https://model.example.com/v1")
    monkeypatch.setenv("SIQ_AS_CLASSIFIER_API_KEY", "test-key")
    output = {
        "is_agent_candidate": True,
        "role": {"value": "legal-advisor", "confidence": 0.94, "evidence_ids": []},
        "system_candidates": [],
        "capability_hints": ["document.read"],
        "unresolved_questions": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        import json as _j

        assert _j.loads(request.content)["temperature"] == 0  # 可追溯重跑（§11.3）
        return httpx.Response(200, json=_provider_ok_response(output))

    result = provider_classify(
        AgentAsset(tenant_id="t", name="legal-advisor", framework="hermes"),
        transport=httpx.MockTransport(handler),
    )
    assert result["is_agent_candidate"] is True
    assert result["role"]["value"] == "legal-advisor"


def test_provider_classify_invalid_output_fails_closed(monkeypatch):
    """输出缺字段/role 结构非法 → RuntimeError（绝不静默回退）。"""
    import httpx

    from app.classification import provider_classify
    from app.models import AgentAsset

    monkeypatch.setenv("SIQ_AS_CLASSIFIER_ENDPOINT", "https://model.example.com/v1")
    bad = {"is_agent_candidate": True}  # 缺 role 等字段

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_provider_ok_response(bad))

    with pytest.raises(RuntimeError, match="缺字段"):
        provider_classify(
            AgentAsset(tenant_id="t", name="x", framework="hermes"),
            transport=httpx.MockTransport(handler),
        )


def test_provider_unreachable_fails_closed(monkeypatch):
    """Provider 不可达 → RuntimeError（分类端点如实 502/记录失败，不静默降级）。"""
    import httpx

    from app.classification import provider_classify
    from app.models import AgentAsset

    monkeypatch.setenv("SIQ_AS_CLASSIFIER_ENDPOINT", "https://model.example.com/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(RuntimeError, match="不可达"):
        provider_classify(
            AgentAsset(tenant_id="t", name="x", framework="hermes"),
            transport=httpx.MockTransport(handler),
        )


def test_provider_failure_persistence_contains_only_error_reference(monkeypatch):
    from app.classification import classify_asset

    monkeypatch.setenv("SIQ_AS_CLASSIFIER", "provider")

    def fail_provider(asset):
        raise RuntimeError("Authorization: Bearer should-never-persist")

    monkeypatch.setattr("app.classification.provider_classify", fail_provider)
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        asset = _seed_asset(session, "tnt-A", name="provider-failure", status="candidate")
        session.flush()
        run = classify_asset(session, "tnt-A", asset)
        session.commit()
        assert "should-never-persist" not in str(run.output)
        assert "RuntimeError:" in run.output["unresolved_questions"][0]


def test_get_scan_task_status(client, tenant_a, tenant_b, env_a):
    """§18.2 首批 API：GET /api/v1/scans/{id} 任务状态 + 跨租户 404。"""
    from sqlalchemy import select

    from app.config import load_settings
    from app.models import EdgeTask, Environment

    quota = load_settings().scan_quota_per_tenant
    with session_scope() as s:
        env_ids = list(s.scalars(select(Environment.id).where(Environment.tenant_id == "tnt-A")))
        pre = s.query(EdgeTask).filter(
            EdgeTask.task_type == "scan", EdgeTask.status == "pending", EdgeTask.environment_id.in_(env_ids)
        ).count()
    if pre >= quota:
        pytest.skip("共享库扫描配额已满（quota 测试占用）")
    created = client.post(
        "/api/v1/scans", json={"environment_id": env_a["id"], "scope": {"connector": "hermes"}}, headers=tenant_a
    ).json()
    resp = client.get(f"/api/v1/scans/{created['task_id']}", headers=tenant_a)
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_type"] == "scan"
    assert body["status"] == "pending"
    assert "signature" not in body  # 签名不回传（仅 Edge 消费）

    cross = client.get(f"/api/v1/scans/{created['task_id']}", headers=tenant_b)
    assert cross.status_code == 404


def test_agent_policies_and_enforcement_status(client, tenant_a, env_a, monkeypatch):
    """agent→policy/enforcement 绑定（诚实边界 §6.5）：未部署=declared_only，effective 部署=enforced。"""
    # 造一个 confirmed 资产
    agent = _make_named_candidate(client, tenant_a, "bind-agent")
    client.post(f"/api/v1/candidates/{agent['id']}/confirm", json={}, headers=tenant_a)

    # 初始：无策略 → declared_only
    enf = client.get(f"/api/v1/agents/{agent['id']}/enforcement", headers=tenant_a).json()
    assert enf["enforce_status"] == "declared_only"
    assert enf["policy_count"] == 0

    # 建策略并部署（fake 后端闭环）
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.contracts import (
        BackendCapabilities,
        DeploymentReceipt,
        PolicySnapshot,
        VerificationReport,
    )

    class FakeCli(OpenShellCliBackend):
        def __init__(self):
            super().__init__(runner=lambda a: (1, "", "unused"), env_script="/n")

        def probe(self):
            return BackendCapabilities(backend="openshell", schema_version="v1", dynamic_network_update=True)

        def read_effective_policy(self, target):
            return PolicySnapshot(target=target, revision="1", network=[])

        def plan_change(self, target, compiled):
            from app.adapters.openshell.contracts import ChangePlan

            return ChangePlan(
                target=target, kind="dynamic", expected_revision="1", artifact_hash=compiled.artifact_hash
            )

        def apply_dynamic(self, target, plan, expected_revision):
            return DeploymentReceipt(backend_revision="2", evidence={"snapshot_hash": "h"})

        def verify(self, target, checks, receipt):
            return VerificationReport(
                passed=True,
                allow_checks=[{"endpoint": e, "result": "allow"} for e in checks.get("expect_allow", [])],
                deny_checks=[{"endpoint": e, "result": "deny"} for e in checks.get("expect_deny", [])],
            )

    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: FakeCli())

    import uuid as _uuid

    pol = client.post(
        "/api/v1/policies",
        json={
            "name": f"bind-policy-{_uuid.uuid4().hex[:8]}",
            "selector": {"agent_ids": [agent["id"]]},
            "network": [{"endpoint": "bind.example.com:443", "effect": "allow"}],
            "enforcement_mode": "block",
        },
        headers=tenant_a,
    ).json()
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": pol["id"], "idempotency_key": f"ik-{_uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    # P0-1：部署必须经登记的 RuntimeBinding（instance 挂在被 selector 选中的资产下）
    from app.models import AgentInstance

    with session_scope() as s:
        inst = AgentInstance(
            tenant_id="tnt-A", asset_id=agent["id"], environment_id=env_a["id"], runtime="hermes"
        )
        s.add(inst)
        s.flush()
        inst_id = inst.id
        s.commit()
    binding = client.post(
        "/api/v1/runtime-bindings",
        json={
            "agent_instance_id": inst_id,
            "environment_id": env_a["id"],
            "backend": "openshell-cli",
            "backend_target_id": "bind-sandbox",
        },
        headers=tenant_a,
    )
    assert binding.status_code == 201, binding.text
    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding.json()["id"]},
        headers=tenant_a,
    ).json()
    assert dep["status"] == "effective"

    policies = client.get(f"/api/v1/agents/{agent['id']}/policies", headers=tenant_a).json()
    assert any(p["id"] == pol["id"] for p in policies)
    enf2 = client.get(f"/api/v1/agents/{agent['id']}/enforcement", headers=tenant_a).json()
    assert enf2["enforce_status"] == "enforced"
    assert any(d["target"] == "bind-sandbox" for d in enf2["effective_deployments"])


def test_rescan_idempotent_versions_evidence(client, tenant_a):
    """相同内容幂等；内容变化新增不可变 observation，不覆盖历史。"""
    env = client.post("/api/v1/environments", json={"name": "env-rescan"}, headers=tenant_a).json()
    identity = "edge-rescan"
    eh, private_key = register_edge(client, tenant_a, env["id"], identity)

    def batch(content_hash, task_id):
        evidence = signed_evidence(private_key, identity, "ev:rescan", content_hash=content_hash)
        return signed_batch(
            private_key,
            task_id,
            candidates=[candidate("rescan-agent", ["ev:rescan"])],
            evidence=[evidence],
        )

    first_task = create_scan_task(client, tenant_a, env["id"])
    first_batch = batch("a" * 64, first_task)
    r1 = client.post("/edge/v1/batches", json=first_batch, headers=eh)
    assert r1.status_code == 200
    r2 = client.post("/edge/v1/batches", json=first_batch, headers=eh)  # 同一 HTTP body 网络重试幂等
    assert r2.status_code == 200, r2.text

    from app.db import session_scope as ss
    from app.models import Evidence

    with ss() as s:
        rows = s.query(Evidence).filter(Evidence.evidence_id == "ev:rescan").all()
        assert len(rows) == 1, "重扫不得产生重复证据行"

    # 内容变化 → 新 observation，旧哈希保留
    second_task = create_scan_task(client, tenant_a, env["id"])
    r3 = client.post("/edge/v1/batches", json=batch("b" * 64, second_task), headers=eh)
    assert r3.status_code == 200
    with ss() as s:
        rows = s.query(Evidence).filter(Evidence.evidence_id == "ev:rescan").all()
        assert {row.content_hash for row in rows} == {"a" * 64, "b" * 64}


def test_smart_scan_creates_standard_tasks(client, tenant_a, env_a):
    """智能扫描：一次下发 hermes/openclaw/docker 三个标准任务；配额超限 429。"""
    from sqlalchemy import select

    from app.config import load_settings
    from app.models import EdgeTask, Environment

    quota = load_settings().scan_quota_per_tenant
    with session_scope() as s:
        env_ids = list(s.scalars(select(Environment.id).where(Environment.tenant_id == "tnt-A")))
        pre = s.query(EdgeTask).filter(
            EdgeTask.task_type == "scan", EdgeTask.status == "pending", EdgeTask.environment_id.in_(env_ids)
        ).count()
    remaining = quota - pre
    if remaining < 3:
        pytest.skip("配额不足，无法测试智能扫描")

    resp = client.post(
        "/api/v1/scans/smart", params={"environment_id": env_a["id"]}, headers=tenant_a
    )
    assert resp.status_code == 200, resp.text
    tasks = resp.json()["tasks"]
    assert [t["connector"] for t in tasks] == ["hermes", "openclaw", "docker"]
    # 任务 payload 带 connector（Edge 选择对应二进制）
    with session_scope() as s:
        from app.models import EdgeTask as _T

        row = s.query(_T).filter(_T.id == tasks[0]["task_id"]).one()
        assert row.payload["connector"] == "hermes"
