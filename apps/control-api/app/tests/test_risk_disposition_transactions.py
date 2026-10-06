"""Preserve tenant, terminal and atomic audit semantics of locked dispositions."""

import pytest

from app.tests.test_risk_acceptance_boundaries import seed, snapshot


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
@pytest.mark.parametrize("scope,expected", [("own", 403), ("foreign", 404), ("missing", 404)])
def test_locked_disposition_object_scope(client, tenant_a, action, scope, expected):
    fid = seed()
    before = snapshot(fid)
    headers = {**tenant_a, "X-Dev-Roles": ""}
    if scope == "foreign":
        headers["X-Dev-Tenant-Id"] = "tnt-B"
    target = "missing-risk" if scope == "missing" else fid
    payload = {"evidence_ref": "ticket:fixture"} if action == "resolve" else None
    response = client.post("/api/v1/findings/" + target + "/" + action, headers=headers, json=payload)
    assert response.status_code == expected
    assert snapshot(fid) == before


@pytest.mark.parametrize(
    "action,status",
    [
        ("acknowledge", "acknowledged"),
        ("acknowledge", "risk_accepted"),
        ("acknowledge", "resolved"),
        ("resolve", "risk_accepted"),
        ("resolve", "resolved"),
    ],
)
def test_locked_disposition_terminal_refusal(client, tenant_a, action, status):
    fid = seed(status)
    before = snapshot(fid)
    response = client.post(
        "/api/v1/findings/" + fid + "/" + action, headers=tenant_a, json={"evidence_ref": "ticket:fixture"}
    )
    assert response.status_code == 409
    assert snapshot(fid) == before


@pytest.mark.parametrize("action,fault", [("acknowledge", "audit"), ("resolve", "audit"), ("resolve", "emit_event")])
def test_locked_disposition_audit_failure_rolls_back(client, tenant_a, monkeypatch, action, fault):
    fid = seed()
    before = snapshot(fid)

    def fail(*args, **kwargs):
        raise RuntimeError("owned fault fixture")

    monkeypatch.setattr("app.routers.findings." + fault, fail)
    with pytest.raises(RuntimeError, match="owned fault fixture"):
        client.post("/api/v1/findings/" + fid + "/" + action, headers=tenant_a, json={"evidence_ref": "ticket:fixture"})
    assert snapshot(fid) == before
