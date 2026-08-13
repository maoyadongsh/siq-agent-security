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
