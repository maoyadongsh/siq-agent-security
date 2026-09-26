import uuid

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, EdgeAgent, utcnow
from app.tests.test_enrollment_flow import _register_edge


def capabilities():
    return {
        "inventory_schema": "enterprise-installed-capabilities/v1",
        "protocol_version": "connector-protocol.v1",
        "connectors": ["hermes"],
        "connector_versions": {"hermes": "0.1.0"},
        "data_categories": ["config_names"],
    }


def device(client, tenant, env, identity="heartbeat-inventory"):
    identity += "-" + uuid.uuid4().hex
    registered = _register_edge(client, env["id"], tenant, identity).json()
    return registered["edge_agent_id"], {
        "X-Edge-Identity": identity,
        "Authorization": "Bearer " + registered["device_secret"],
    }


def test_replace_clear_legacy_and_audit(client, tenant_a, env_a):
    edge_id, headers = device(client, tenant_a, env_a)
    value = capabilities()

    def beat(payload):
        return client.post("/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", **payload})

    assert beat({"capabilities": value}).status_code == 200
    assert beat({"capabilities": value}).status_code == 200
    assert beat({}).status_code == 200
    assert beat({"capabilities": None}).status_code == 200
    with session_scope() as session:
        edge = session.get(EdgeAgent, edge_id)
        assert edge.capabilities == value
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "edge.capabilities.update", AuditEvent.resource_id == edge_id)
        ).all()
        assert len(events) == 1
        assert events[0].tenant_id == tenant_a["X-Dev-Tenant-Id"]
    value.update(connectors=[], connector_versions={}, data_categories=[])
    assert beat({"capabilities": value}).status_code == 200
    with session_scope() as session:
        assert session.get(EdgeAgent, edge_id).capabilities == value
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "edge.capabilities.update", AuditEvent.resource_id == edge_id
                    )
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize(
    "change",
    [
        {"connectors": ["hermes", "hermes"]},
        {"connector_versions": {}},
        {"connectors": ["unknown"]},
        {"connector_versions": {"hermes": "bad\nversion"}},
        {"data_categories": ["private\ntext"]},
        {"data_categories": ["config_names", "config_names"]},
        {"data_categories": ["x"] * 65},
        {"environment_id": "foreign"},
        {"protocol_version": "v2"},
        {"inventory_schema": "v2"},
    ],
)
def test_invalid_capabilities_do_not_mutate(client, tenant_a, env_a, change):
    edge_id, headers = device(client, tenant_a, env_a)
    with session_scope() as session:
        before = session.get(EdgeAgent, edge_id).capabilities
    result = client.post(
        "/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": {**capabilities(), **change}}
    )
    assert result.status_code == 422
    with session_scope() as session:
        edge = session.get(EdgeAgent, edge_id)
        assert edge.capabilities == before
        assert edge.last_seen_at is None


def test_credentials_cannot_change_other_device_or_revoked_device(client, tenant_a, tenant_b, env_a, env_b):
    a_id, a = device(client, tenant_a, env_a, "inventory-device-a")
    b_id, b = device(client, tenant_b, env_b, "inventory-device-b")
    body = {"version": "0.1.0", "capabilities": capabilities()}
    assert (
        client.post("/edge/v1/heartbeat", headers={**a, "X-Edge-Identity": b["X-Edge-Identity"]}, json=body).status_code
        == 401
    )
    with session_scope() as session:
        session.get(EdgeAgent, a_id).revoked_at = utcnow()
    assert client.post("/edge/v1/heartbeat", headers=a, json=body).status_code == 401
    with session_scope() as session:
        assert session.get(EdgeAgent, b_id).last_seen_at is None
        assert session.get(EdgeAgent, a_id).last_seen_at is None


def test_audit_failure_rolls_back_capabilities_and_heartbeat(client, tenant_a, env_a, monkeypatch):
    edge_id, headers = device(client, tenant_a, env_a)

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("app.routers.environments.audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        client.post("/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": capabilities()})
    with session_scope() as session:
        edge = session.get(EdgeAgent, edge_id)
        assert edge.last_seen_at is None
        assert edge.capabilities != capabilities()
