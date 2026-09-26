import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AgentAsset, AuditEvent, EdgeAgent, Environment, Evidence
from app.tests.edge_helpers import register_edge


@pytest.mark.parametrize("scope,expected", [("legacy", "legacy_unresolved"), ("missing-edge", "source_unavailable")])
def test_unresolved_origin_not_guessed_and_read_only(client, tenant_a, tenant_b, scope, expected):
    with session_scope() as session:
        asset = AgentAsset(
            tenant_id=tenant_a["X-Dev-Tenant-Id"],
            name="origin-fixture",
            framework="hermes",
            discovery_scope=scope,
            attributes={"device_identity": "forged", "environment": "forged"},
        )
        session.add(asset)
        session.flush()
        asset_id = asset.id
        audit_count = session.scalar(select(func.count(AuditEvent.id)))
    route = f"/api/v1/agents/{asset_id}/discovery-origin"
    assert client.get(route, headers=tenant_b).status_code == 404
    assert client.get(route, headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403
    value = client.get(route, headers=tenant_a).json()
    assert value["status"] == expected
    assert value["environment"] is None and value["device"] is None and value["observations"] == []
    assert "forged" not in str(value)
    with session_scope() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == audit_count
        assert session.get(AgentAsset, asset_id).status == "candidate"


def test_corrupted_foreign_scope_does_not_expose_device(client, tenant_a, tenant_b):
    identity = "foreign-origin-" + uuid.uuid4().hex
    response = client.post("/api/v1/environments", headers=tenant_b, json={"name": identity})
    env = response.json()["id"]
    register_edge(client, tenant_b, env, identity)
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        assert session.get(Environment, edge.environment_id).tenant_id == tenant_b["X-Dev-Tenant-Id"]
        asset = AgentAsset(tenant_id=tenant_a["X-Dev-Tenant-Id"], name="fault-injected-origin", discovery_scope=edge.id)
        session.add(asset)
        session.flush()
        asset_id = asset.id
    response = client.get(f"/api/v1/agents/{asset_id}/discovery-origin", headers=tenant_a)
    assert response.status_code == 200
    assert response.json()["status"] == "source_unavailable"
    assert response.json()["device"] is None
    assert identity not in response.text and env not in response.text


def test_origin_bounded_history_preserves_revoked_source(client, tenant_a):
    identity = "bounded-origin-" + uuid.uuid4().hex
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": identity}).json()["id"]
    register_edge(client, tenant_a, env, identity)
    now = datetime(2026, 9, 25)
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        edge.revoked_at = now
        asset = AgentAsset(tenant_id=tenant_a["X-Dev-Tenant-Id"], name=identity, discovery_scope=edge.id)
        session.add(asset)
        session.flush()
        asset_id = asset.id
        for index in range(201):
            session.add(
                Evidence(
                    tenant_id=asset.tenant_id,
                    environment_id=env,
                    subject_ref=asset_id,
                    evidence_id=f"observation-{index}",
                    collector_id=identity,
                    source_type="fixture",
                    source_locator="private-location",
                    observed_at=now + timedelta(seconds=index),
                    connector_version="0.1.0",
                    content_hash="a" * 64,
                    signature="private-signature",
                    payload_ref="private-payload",
                )
            )
    response = client.get(f"/api/v1/agents/{asset_id}/discovery-origin", headers=tenant_a)
    assert response.status_code == 200
    value = response.json()
    assert value["device"]["revoked"] is True and value["status"] == "device_bound"
    assert value["observations_truncated"] is True and len(value["observations"]) == 200
    assert value["observations"][0]["evidence_id"] == "observation-200"
    assert value["observations"][-1]["evidence_id"] == "observation-1"
    assert "private-" not in response.text
