import json

import pytest
from fastapi import HTTPException

from app.business_navigation import _origin
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence

EVENT = "sev_" + "a" * 64


def test_linked_signed_event_and_tenant_boundary(client, tenant_a, tenant_b, monkeypatch):
    monkeypatch.setenv("SIQ_AS_BUSINESS_WEB_ORIGINS", json.dumps({"tnt-A": "https://research.example.com"}))
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": "navigation"}).json()["id"]
    edge, key = register_edge(client, tenant_a, env, "edge-navigation")
    task = create_scan_task(client, tenant_a, env)
    evidence = signed_evidence(key, "edge-navigation", "ev-navigation", source_type="gateway",
        source_locator="siq://business-security-event/" + EVENT)
    upload = client.post("/edge/v1/batches", headers=edge, json=signed_batch(key, task,
        candidates=[candidate("navigation", ["ev-navigation"])], evidence=[evidence]))
    assert upload.status_code == 200, upload.text
    asset = next(a for a in client.get("/api/v1/candidates", headers=tenant_a).json() if a["name"] == "navigation")
    url = f"/api/v1/agents/{asset['id']}/business-navigation"
    response = client.get(url, headers=tenant_a)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["items"] == [dict(evidence_id="ev-navigation", event_id=EVENT,
        href=f"https://research.example.com/analysis/security-event?event_id={EVENT}")]
    assert client.get(url, headers=tenant_b).status_code == 404
    monkeypatch.delenv("SIQ_AS_BUSINESS_WEB_ORIGINS")
    assert client.get(url, headers=tenant_a).json() == dict(schema_version="siq.business-event-navigation/v1",
        configured=False, items=[])
    monkeypatch.setenv("SIQ_AS_BUSINESS_WEB_ORIGINS", '{"tnt-A":"javascript:alert(1)"}')
    assert client.get(url, headers=tenant_a).status_code == 503


@pytest.mark.parametrize("origin", ["javascript:alert(1)", "http://example.com", "//example.com", "https://u:p@example.com",
    "https://example.com/other", "https://example.com?q=x", "https://example.com#x", "https://example.com\\evil",
    "https://example.com\n", "https://example.com:0", "https://example.com:99999", "https://example.com%2fother"])
def test_untrusted_origins_refused(monkeypatch, origin):
    monkeypatch.setenv("SIQ_AS_BUSINESS_WEB_ORIGINS", json.dumps({"t": origin}))
    with pytest.raises(HTTPException) as error:
        _origin("t")
    assert error.value.status_code == 503


@pytest.mark.parametrize("origin", ["https://research.example.com", "http://127.0.0.1:15173", "http://[::1]:15173"])
def test_configured_origins(monkeypatch, origin):
    monkeypatch.setenv("SIQ_AS_BUSINESS_WEB_ORIGINS", json.dumps({"t": origin}))
    assert _origin("t") == origin and _origin("foreign") is None


def test_duplicate_tenant_rejected(monkeypatch):
    monkeypatch.setenv("SIQ_AS_BUSINESS_WEB_ORIGINS", '{"t":"https://first.example","t":"https://second.example"}')
    with pytest.raises(HTTPException):
        _origin("t")
