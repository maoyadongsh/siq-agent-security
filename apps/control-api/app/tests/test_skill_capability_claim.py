# Ruff F811: pytest injects the explicitly imported shared fixture by name.
# ruff: noqa: F811
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import EdgeAgent, EdgeTask, utcnow
from app.tests.test_capability_task_claim import fetched, measured_device, task  # noqa: F401


def skill_capabilities():
    return {
        "inventory_schema": "enterprise-installed-capabilities/v2",
        "protocol_version": "connector-protocol.v1",
        "connectors": ["directory"],
        "connector_versions": {"directory": "0.1.0"},
        "data_categories": ["tool_names"],
        "connector_task_types": {"directory": ["scan", "skill_scan"]},
    }


def skill_task(env, identity, **extra):
    return task(
        env,
        task_type="skill_scan",
        payload={
            "connector": "directory",
            "inventory_kind": "skills",
            "target_device_identity": identity,
        },
        **extra,
    )


@pytest.mark.parametrize("scenario", ["legacy", "v1", "scan_only", "stale", "future", "missing", "invalid"])
def test_skill_claim_requires_fresh_explicit_capability(client, measured_device, scenario):
    env, identity, headers = measured_device
    blocked = skill_task(env, identity)
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        value = skill_capabilities()
        if scenario == "legacy":
            value.pop("inventory_schema")
        elif scenario == "v1":
            value["inventory_schema"] = "enterprise-installed-capabilities/v1"
            value.pop("connector_task_types")
        elif scenario == "scan_only":
            value["connector_task_types"]["directory"] = ["scan"]
        elif scenario == "invalid":
            value["connector_task_types"] = {}
        elif scenario == "stale":
            edge.last_seen_at = utcnow() - timedelta(days=1)
        elif scenario == "future":
            edge.last_seen_at = utcnow() + timedelta(days=1)
        else:
            edge.last_seen_at = None
        edge.capabilities = value
    assert fetched(client, headers) == set()
    with session_scope() as session:
        row = session.get(EdgeTask, blocked)
        assert row.attempt == 0 and row.lease_owner is None


def test_skill_target_filter_precedes_limit_and_preserves_recovery(client, measured_device):
    env, identity, headers = measured_device
    response = client.post(
        "/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": skill_capabilities()}
    )
    assert response.status_code == 200
    blocked = [skill_task(env, "other-device") for _ in range(12)]
    blocked += [skill_task(env, None)]
    owned = skill_task(env, identity)
    assert fetched(client, headers) == {owned}
    with session_scope() as session:
        row = session.get(EdgeTask, owned)
        row.status = "uploaded"
        for task_id in blocked:
            assert session.get(EdgeTask, task_id).attempt == 0
    empty = skill_capabilities()
    empty.update(connectors=[], connector_versions={}, connector_task_types={}, data_categories=[])
    assert (
        client.post("/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": empty}).status_code
        == 200
    )
    pending = skill_task(env, identity)
    assert fetched(client, headers) == {owned}
    with session_scope() as session:
        assert session.get(EdgeTask, pending).attempt == 0


@pytest.mark.parametrize(
    "mapping",
    [{}, {"directory": []}, {"directory": ["scan", "scan"]}, {"directory": ["execute"]}, {"hermes": ["skill_scan"]}],
)
def test_invalid_task_capability_heartbeat_rejected(client, measured_device, mapping):
    _, _, headers = measured_device
    value = skill_capabilities()
    value["connector_task_types"] = mapping
    assert (
        client.post("/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": value}).status_code
        == 422
    )


@pytest.mark.parametrize("scenario", ["connector", "kind", "lease", "uploaded_other_owner", "foreign_environment"])
def test_skill_capability_never_bypasses_binding(client, measured_device, tenant_b, scenario):
    env, identity, headers = measured_device
    value = skill_capabilities()
    assert (
        client.post("/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": value}).status_code
        == 200
    )
    blocked = skill_task(env, identity)
    with session_scope() as session:
        row = session.get(EdgeTask, blocked)
        if scenario == "connector":
            row.payload = {**row.payload, "connector": "hermes"}
        elif scenario == "kind":
            row.payload = {**row.payload, "inventory_kind": "agents"}
        elif scenario == "foreign_environment":
            other = client.post("/api/v1/environments", headers=tenant_b, json={"name": "skill-foreign"})
            assert other.status_code == 201
            row.environment_id = other.json()["id"]
        else:
            row.lease_owner = "other-device"
            row.leased_at = utcnow()
            if scenario == "uploaded_other_owner":
                row.status = "uploaded"
                row.leased_at = utcnow() - timedelta(days=1)
    assert fetched(client, headers) == set()
    with session_scope() as session:
        row = session.get(EdgeTask, blocked)
        assert row.attempt == 0
        row.status = "expired"
