"""Periodic scans must preserve active risk dispositions without hiding other risks."""

from datetime import UTC, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, Finding, OutboxEvent, Tenant, utcnow
from app.rules import RuleResult, upsert_findings
from app.tests.test_rules import _ensure_tenant, _seed_asset
from app.worker import once


@pytest.mark.parametrize("status", ["open", "acknowledged", "risk_accepted", "resolved"])
def test_same_scope_retains_active_disposition(client, status):
    tenant = "risk-state-" + uuid4().hex[:12]
    with session_scope() as session:
        session.add(Tenant(id=tenant, name=tenant))
        session.flush()
        acceptance = {"reason": "valid acceptance", "expires_at": (utcnow() + timedelta(hours=1)).isoformat()}
        finding = Finding(
            tenant_id=tenant,
            rule_id="scope-test",
            severity="low",
            status=status,
            owner_user_id="owner",
            risk_acceptance=acceptance,
        )
        session.add(finding)
        session.commit()
        original_id = finding.id
        result = RuleResult("scope-test", "low", "governance", None, None, [], "test", "test")
        counts = upsert_findings(session, tenant, [result])
        session.commit()
        all_findings = list(session.scalars(select(Finding).where(Finding.tenant_id == tenant)))
        active = status != "resolved"
        assert counts == ({"created": 0, "updated": 1} if active else {"created": 1, "updated": 0})
        assert len(all_findings) == (1 if active else 2)
        original = session.get(Finding, original_id)
        assert (original.status, original.owner_user_id, original.risk_acceptance) == (status, "owner", acceptance)
        assert len(list(session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant)))) == (
            0 if active else 1
        )
        assert len(list(session.scalars(select(OutboxEvent).where(OutboxEvent.tenant_id == tenant)))) == (
            0 if active else 1
        )


@pytest.mark.parametrize("different", ["tenant", "rule", "resource"])
def test_accepted_risk_does_not_suppress_other_scope(client, different):
    tenant = "risk-scope-" + uuid4().hex[:12]
    with session_scope() as session:
        session.add_all([Tenant(id=tenant, name=tenant), Tenant(id=tenant + "b", name=tenant + "b")])
        session.flush()
        session.add(
            Finding(
                tenant_id=tenant,
                rule_id="scope-test",
                severity="low",
                status="risk_accepted",
                resource_ref="env-a",
                risk_acceptance={"expires_at": (utcnow().replace(tzinfo=UTC) + timedelta(hours=1)).isoformat()},
            )
        )
        session.commit()
        target_tenant = tenant + "b" if different == "tenant" else tenant
        result = RuleResult(
            "other-rule" if different == "rule" else "scope-test",
            "low",
            "governance",
            None,
            "env-b" if different == "resource" else "env-a",
            [],
            "test",
            "test",
        )
        assert upsert_findings(session, target_tenant, [result]) == {"created": 1, "updated": 0}
        session.commit()


@pytest.mark.parametrize("accept", [False, True])
def test_full_worker_retains_http_disposition(client, tenant_a, monkeypatch, accept):
    monkeypatch.delenv("SIQ_AS_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "none")
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        asset = _seed_asset(session, "tnt-A", name="cycle-" + uuid4().hex, owner="user-a")
        session.commit()
        asset_id = asset.id
    assert client.post("/api/v1/findings/run-rules", headers=tenant_a).status_code == 200
    findings = client.get("/api/v1/findings", params={"asset_id": asset_id}, headers=tenant_a).json()
    fid = next(x["id"] for x in findings if x["rule_id"] == "no-effective-permissions")
    path = "/api/v1/findings/" + fid
    assert client.post(path + "/acknowledge", headers=tenant_a).status_code == 200
    if accept:
        assert (
            client.post(
                path + "/accept-risk",
                headers=tenant_a,
                json={
                    "owner_user_id": "user-a",
                    "reason": "temporary",
                    "expires_at": (utcnow().replace(tzinfo=UTC) + timedelta(hours=1)).isoformat(),
                },
            ).status_code
            == 200
        )
    once()
    after = client.get("/api/v1/findings", params={"asset_id": asset_id}, headers=tenant_a).json()
    assert [(x["id"], x["status"]) for x in after] == [(fid, "risk_accepted" if accept else "acknowledged")]
