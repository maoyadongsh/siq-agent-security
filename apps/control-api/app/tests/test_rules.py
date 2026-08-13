"""规则引擎与 Worker 测试（设计文档 §13.1）。

覆盖：无主资产、心跳过期、凭据共用、无有效权限、风险接受到期重开、幂等。
"""

from __future__ import annotations

from datetime import timedelta

from app.db import session_scope
from app.models import AgentAsset, Environment, Finding, PermissionFact, Tenant, utcnow
from app.rules import evaluate_all, upsert_findings
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
        assert finding.status == "expired"


def test_edge_cannot_assert_effective_permission(client, tenant_a, env_a):
    """安全不变量：effective 只能来自权威源，Edge 上传标记 effective 的权限事实必须 422。"""
    enr = client.post(
        f"/api/v1/environments/{env_a['id']}/edge-enrollment", json={}, headers=tenant_a
    ).json()
    reg = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": enr["code"],
            "device_identity": "edge-pf-test",
            "public_key_pem": "PEM",
            "version": "0.1.0",
        },
    ).json()
    eh = {"Authorization": f"Bearer {reg['device_secret']}", "X-Edge-Identity": "edge-pf-test"}
    bad = client.post(
        "/edge/v1/batches",
        json={
            "permission_facts": [
                {
                    "subject": {"type": "agent_instance", "id": "inst_x"},
                    "domain": "network",
                    "action": "http.request",
                    "resource": {"type": "endpoint", "value": "api.example.com"},
                    "effect": "allow",
                    "state": "effective",  # 禁止
                    "authority": "edge",
                    "evidence_ids": [],
                }
            ]
        },
        headers=eh,
    )
    assert bad.status_code == 422
    assert "edge_cannot_assert_effective" in bad.json()["detail"]

    good = client.post(
        "/edge/v1/batches",
        json={
            "permission_facts": [
                {
                    "subject": {"type": "agent_instance", "id": "inst_x"},
                    "domain": "network",
                    "action": "http.request",
                    "resource": {"type": "endpoint", "value": "api.example.com"},
                    "effect": "allow",
                    "state": "declared",
                    "authority": "edge-connector",
                    "evidence_ids": [],
                }
            ]
        },
        headers=eh,
    )
    assert good.status_code == 200
    assert good.json()["permission_facts"] == 1


def _make_named_candidate(client, headers, name):
    env = client.post("/api/v1/environments", json={"name": f"env-cls-{name}"}, headers=headers).json()
    enr = client.post(f"/api/v1/environments/{env['id']}/edge-enrollment", json={}, headers=headers).json()
    reg = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": enr["code"],
            "device_identity": f"edge-cls-{name}",
            "public_key_pem": "PEM",
            "version": "0.1.0",
        },
    ).json()
    eh = {"Authorization": f"Bearer {reg['device_secret']}", "X-Edge-Identity": f"edge-cls-{name}"}
    resp = client.post(
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
                    "evidence_ids": [],
                }
            ],
            "evidence": [],
        },
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

    res = client.post(f"/api/v1/findings/{finding['id']}/resolve", json={}, headers=tenant_a)
    assert res.status_code == 200
    assert res.json()["status"] == "resolved"

    # 重复解决：409
    again = client.post(f"/api/v1/findings/{finding['id']}/resolve", json={}, headers=tenant_a)
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
    for i in range(remaining):
        resp = client.post("/api/v1/scans", json={"environment_id": env_a["id"], "scope": {"n": i}}, headers=tenant_a)
        assert resp.status_code == 200, f"quota loop {i}/{remaining}: {resp.text}"
    over = client.post("/api/v1/scans", json={"environment_id": env_a["id"], "scope": {}}, headers=tenant_a)
    assert over.status_code == 429
    assert "scan_quota_exceeded" in over.json()["detail"]


def test_cursor_pagination_agents(client, tenant_a):
    """§18.1 稳定游标分页：limit + cursor 全量无重复。"""
    for i in range(5):
        env = client.post("/api/v1/environments", json={"name": f"env-pg-{i}"}, headers=tenant_a).json()
        enr = client.post(f"/api/v1/environments/{env['id']}/edge-enrollment", json={}, headers=tenant_a).json()
        reg = client.post(
            "/edge/v1/register",
            json={
                "enrollment_code": enr["code"],
                "device_identity": f"edge-pg-{i}",
                "public_key_pem": "PEM",
                "version": "0.1.0",
            },
        ).json()
        eh = {"Authorization": f"Bearer {reg['device_secret']}", "X-Edge-Identity": f"edge-pg-{i}"}
        client.post(
            "/edge/v1/batches",
            json={
                "candidates": [
                    {
                        "candidate_id": f"hermes:pg-{i}",
                        "source_type": "hermes_profile",
                        "source_locator": f"hermes://pg/{i}",
                        "discovered_at": "2026-08-13T12:00:00Z",
                        "name": f"pg-agent-{i}",
                        "framework": "hermes",
                        "evidence_ids": [],
                    }
                ],
                "evidence": [],
            },
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
