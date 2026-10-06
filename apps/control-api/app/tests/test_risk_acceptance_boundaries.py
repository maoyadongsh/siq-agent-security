"""Direct HTTP risk acceptance must preserve input, object and terminal boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, Finding, OutboxEvent, Tenant


def seed(status="open"):
    fid = "risk-boundary-" + uuid4().hex
    with session_scope() as session:
        if session.get(Tenant, "tnt-A") is None:
            session.add(Tenant(id="tnt-A", name="Boundary fixture"))
            session.flush()
        session.add(
            Finding(
                id=fid,
                tenant_id="tnt-A",
                rule_id="boundary-fixture",
                severity="info",
                status=status,
                owner_user_id="previous-owner",
                risk_acceptance={"evidence_ref": "ticket:existing"},
            )
        )
    return fid


def body():
    return {
        "owner_user_id": "risk-owner",
        "reason": "temporary acceptance",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }


def snapshot(fid):
    with session_scope() as session:
        f = session.get(Finding, fid)
        audits = [(x.id, x.action) for x in session.scalars(select(AuditEvent).where(AuditEvent.resource_id == fid))]
        events = [
            (x.id, x.event_type)
            for x in session.scalars(select(OutboxEvent).where(OutboxEvent.tenant_id == "tnt-A"))
            if x.payload.get("resource_ref") == fid
        ]
        return (f.status, f.owner_user_id, f.risk_acceptance, sorted(audits), sorted(events))


@pytest.mark.parametrize(
    "change",
    [
        {"owner_user_id": ""},
        {"owner_user_id": "   "},
        {"owner_user_id": "x" * 65},
        {"owner_user_id": "user\nother"},
        {"reason": "   "},
        {"reason": "\t\n"},
        {"expires_at": "9999-12-31T23:59:59-14:00"},
        {"expires_at": "0001-01-01T00:00:00+14:00"},
    ],
)
def test_invalid_acceptance_is_atomic(client, tenant_a, change):
    fid = seed()
    before = snapshot(fid)
    response = client.post(f"/api/v1/findings/{fid}/accept-risk", headers=tenant_a, json={**body(), **change})
    assert response.status_code == 422, response.text
    assert snapshot(fid) == before


@pytest.mark.parametrize("scope,expected", [("own", 403), ("foreign", 404), ("missing", 404)])
def test_object_location_precedes_permission(client, tenant_a, scope, expected):
    fid = seed()
    before = snapshot(fid)
    headers = {**tenant_a, "X-Dev-Roles": ""}
    if scope == "foreign":
        headers["X-Dev-Tenant-Id"] = "tnt-B"
    target = "nonexistent-finding" if scope == "missing" else fid
    response = client.post(f"/api/v1/findings/{target}/accept-risk", headers=headers, json=body())
    assert response.status_code == expected, response.text
    assert snapshot(fid) == before


@pytest.mark.parametrize("status", ["risk_accepted", "resolved"])
def test_terminal_risk_cannot_be_overwritten(client, tenant_a, status):
    fid = seed(status)
    before = snapshot(fid)
    response = client.post(f"/api/v1/findings/{fid}/accept-risk", headers=tenant_a, json=body())
    assert response.status_code == 409, response.text
    assert snapshot(fid) == before


@pytest.mark.parametrize("status", ["open", "acknowledged"])
def test_live_risk_acceptance_remains_usable_and_audited(client, tenant_a, status):
    fid = seed(status)
    response = client.post(f"/api/v1/findings/{fid}/accept-risk", headers=tenant_a, json=body())
    assert response.status_code == 200, response.text
    state = snapshot(fid)
    assert state[0:2] == ("risk_accepted", "risk-owner")
    assert state[2]["reason"] == "temporary acceptance"
    assert len(state[3]) == len(state[4]) == 1
    assert state[3][0][1] == "finding.accept_risk"
    assert state[4][0][1] == "agent.finding.resolved.v1"
