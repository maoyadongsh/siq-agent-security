import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.db import session_scope
from app.models import EdgeAgent, EdgeTask, utcnow
from app.tests.edge_helpers import register_edge
from app.tests.test_capability_heartbeat import capabilities


@pytest.fixture
def measured_device(client, tenant_a):
    identity = "claim-" + uuid.uuid4().hex
    response = client.post("/api/v1/environments", headers=tenant_a, json={"name": identity})
    assert response.status_code == 201
    env = response.json()["id"]
    headers, _ = register_edge(client, tenant_a, env, identity)
    response = client.post(
        "/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": capabilities()}
    )
    assert response.status_code == 200
    yield env, identity, headers
    # Shared test database: close only this fixture's tasks, not other tests'
    # pending work or the production quota guard.
    with session_scope() as session:
        session.execute(update(EdgeTask).where(EdgeTask.environment_id == env).values(status="expired"))


def task(env, connector="hermes", **extra):
    with session_scope() as session:
        row = EdgeTask(
            environment_id=env,
            task_type="scan",
            payload={"connector": connector},
            status="pending",
            expires_at=utcnow() + timedelta(minutes=10),
        )
        for key, value in extra.items():
            setattr(row, key, value)
        session.add(row)
        session.flush()
        return row.id


def fetched(client, headers):
    response = client.get("/edge/v1/tasks", headers=headers)
    assert response.status_code == 200
    return {row["id"] for row in response.json()}


def test_capability_filter_precedes_limit(client, measured_device):
    env, _, headers = measured_device
    unsupported = [task(env, "openclaw") for _ in range(12)]
    compatible = task(env)
    assert fetched(client, headers) == {compatible}
    with session_scope() as session:
        for task_id in unsupported:
            row = session.get(EdgeTask, task_id)
            assert row.lease_owner is None and row.attempt == 0


@pytest.mark.parametrize("scenario", ["empty", "invalid", "missing_heartbeat", "stale", "future"])
def test_unverified_inventory_cannot_claim_scan(client, measured_device, scenario):
    env, identity, headers = measured_device
    task(env)
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        if scenario == "empty":
            edge.capabilities = {**capabilities(), "connectors": [], "connector_versions": {}}
        elif scenario == "invalid":
            edge.capabilities = {**capabilities(), "inventory_schema": "unknown"}
        elif scenario == "missing_heartbeat":
            edge.last_seen_at = None
        elif scenario == "stale":
            edge.last_seen_at = utcnow() - timedelta(days=1)
        else:
            edge.last_seen_at = utcnow() + timedelta(days=1)
    assert fetched(client, headers) == set()


def test_withdrawal_preserves_uploaded_owner_receipt_recovery(client, measured_device, tenant_a):
    env, identity, headers = measured_device
    pending = task(env)
    uploaded = task(env, status="uploaded", lease_owner=identity, leased_at=utcnow())
    empty = {**capabilities(), "connectors": [], "connector_versions": {}, "data_categories": []}
    assert (
        client.post("/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": empty}).status_code
        == 200
    )
    assert fetched(client, headers) == {uploaded}
    other, _ = register_edge(client, tenant_a, env, "claim-other-" + uuid.uuid4().hex)
    assert (
        client.post("/edge/v1/heartbeat", headers=other, json={"version": "0.1.0", "capabilities": empty}).status_code
        == 200
    )
    assert fetched(client, other) == set()
    with session_scope() as session:
        assert session.get(EdgeTask, pending).lease_owner is None


def test_capability_does_not_bypass_environment_or_lease(client, measured_device, tenant_a, tenant_b):
    env, _, headers = measured_device
    foreign_env = client.post(
        "/api/v1/environments", headers=tenant_b, json={"name": "claim-foreign-" + uuid.uuid4().hex}
    ).json()["id"]
    foreign = task(foreign_env)
    owned = task(env)
    assert fetched(client, headers) == {owned}
    other, _ = register_edge(client, tenant_a, env, "claim-other-" + uuid.uuid4().hex)
    assert (
        client.post(
            "/edge/v1/heartbeat", headers=other, json={"version": "0.1.0", "capabilities": capabilities()}
        ).status_code
        == 200
    )
    assert fetched(client, other) == set()
    with session_scope() as session:
        assert session.get(EdgeTask, foreign).lease_owner is None
        session.get(EdgeTask, foreign).status = "expired"
