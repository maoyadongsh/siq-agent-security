import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, DesiredPolicy, EdgeAgent, EdgeTask, OutboxEvent
from app.tests.edge_helpers import create_scan_task, register_edge
from app.tests.test_registration_recovery import setup_recovery


@pytest.fixture
def env_a(client, tenant_a):
    # Each lifecycle test owns its enrollment quota; never exhaust the shared fixture's limit.
    response = client.post("/api/v1/environments", headers=tenant_a,
                           json={"name": "device-lifecycle-" + uuid.uuid4().hex})
    assert response.status_code == 201
    return response.json()


def setup(client, tenant, env):
    device = "lifecycle-" + uuid.uuid4().hex
    headers, _ = register_edge(client, tenant, env["id"], device)
    with session_scope() as session:
        edge_id = session.scalar(select(EdgeAgent.id).where(EdgeAgent.device_identity == device))
    path = f"/api/v1/environments/{env['id']}/devices/{edge_id}"
    body = {"schema_version": "enterprise-device-revoke/v1", "confirm_device_id": edge_id}
    return path, body, headers


def counts():
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(model))
                for model in (EdgeAgent, AuditEvent, OutboxEvent)]


def test_revoke_readback_retry_and_online_rejection(client, tenant_a, env_a):
    path, body, headers = setup(client, tenant_a, env_a)
    before = counts()
    active = client.get(path + "/credential-status", headers=tenant_a)
    assert active.status_code == 200
    assert active.json()["status"] == "active"
    assert active.json()["revoked_at"] is None
    assert counts() == before
    assert client.post("/edge/v1/heartbeat", json={"version": "0.1.0"}, headers=headers).status_code == 200
    before = counts()
    revoked = client.post(path + "/revoke", json=body, headers=tenant_a)
    assert revoked.status_code == 200, revoked.text
    assert revoked.headers["cache-control"] == "no-store"
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["revoked_at"] is not None
    assert revoked.json()["runtime_permissions_changed"] is False
    assert set(revoked.json()) == {"schema_version", "environment_id", "device_id", "status",
                                   "revoked_at", "runtime_permissions_changed"}
    assert counts() == [before[0], before[1] + 1, before[2] + 1]
    after = counts()
    assert client.post(path + "/revoke", json=body, headers=tenant_a).json() == revoked.json()
    readback = client.get(path + "/credential-status", headers=tenant_a)
    assert readback.headers["cache-control"] == "no-store"
    assert readback.json() == revoked.json()
    assert counts() == after
    for method, endpoint, payload in [
        ("POST", "/edge/v1/heartbeat", {"version": "0.1.0"}),
        ("GET", "/edge/v1/tasks", None),
        ("POST", "/edge/v1/batches", {}),
        ("POST", "/edge/v1/skill-batches", {}),
        ("POST", "/edge/v1/tasks/test-task/receipt", {"status": "success"}),
    ]:
        response = client.request(method, endpoint, json=payload, headers=headers)
        assert response.status_code == 401, (endpoint, response.text)
        assert response.json()["detail"] == "edge_untrusted"
    assert counts() == after
    with session_scope() as session:
        audit = session.scalar(select(AuditEvent).where(
            AuditEvent.resource_id == body["confirm_device_id"], AuditEvent.action == "edge.device.revoke"))
        assert audit.tenant_id == tenant_a["X-Dev-Tenant-Id"]
        assert audit.actor_id == tenant_a["X-Dev-User-Id"]
        assert audit.summary == {"environment_id": env_a["id"], "device_id": body["confirm_device_id"]}


@pytest.mark.parametrize("case,expected", [("foreign", 404), ("missing", 404),
                                           ("wrong_environment", 404), ("denied", 403)])
def test_object_and_permission_boundary(client, tenant_a, tenant_b, env_a, env_b, case, expected):
    path, body, _ = setup(client, tenant_a, env_a)
    caller = dict(tenant_a, **{"X-Dev-Roles": "viewer"})
    if case == "foreign":
        caller = tenant_b
    elif case == "missing":
        path = path.replace(body["confirm_device_id"], "missing")
    elif case == "wrong_environment":
        path = path.replace(env_a["id"], env_b["id"])
    before = counts()
    assert client.get(path + "/credential-status", headers=caller).status_code == expected
    assert client.post(path + "/revoke", json=body, headers=caller).status_code == expected
    assert counts() == before
    with session_scope() as session:
        assert session.get(EdgeAgent, body["confirm_device_id"]).revoked_at is None


@pytest.mark.parametrize("patch", [{"confirm_device_id": "wrong"}, {"confirm_device_id": ""},
                                    {"tenant_id": "other"}, {"schema_version": "v0"}])
def test_invalid_confirmation_never_changes_device(client, tenant_a, env_a, patch):
    path, body, _ = setup(client, tenant_a, env_a)
    before = counts()
    assert client.post(path + "/revoke", json=body | patch, headers=tenant_a).status_code == 422
    assert counts() == before
    with session_scope() as session:
        assert session.get(EdgeAgent, body["confirm_device_id"]).revoked_at is None


@pytest.mark.parametrize("operation", ["audit", "emit_event"])
def test_transaction_failure_preserves_credential(client, tenant_a, env_a, monkeypatch, operation):
    path, body, headers = setup(client, tenant_a, env_a)
    before = counts()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic private failure")

    monkeypatch.setattr(f"app.routers.device_lifecycle.{operation}", fail)
    response = client.post(path + "/revoke", json=body, headers=tenant_a)
    assert response.status_code == 503
    assert response.json()["detail"] == "device_revocation_unavailable"
    assert counts() == before
    with session_scope() as session:
        assert session.get(EdgeAgent, body["confirm_device_id"]).revoked_at is None
    assert client.post("/edge/v1/heartbeat", json={"version": "0.1.0"}, headers=headers).status_code == 200


def test_recovery_cannot_resurrect_revoked_device(client, tenant_a, env_a):
    identity, _, _, recovery_body, _ = setup_recovery(client, tenant_a, env_a["id"])
    with session_scope() as session:
        edge_id = session.scalar(select(EdgeAgent.id).where(EdgeAgent.device_identity == identity))
    response = client.post(f"/api/v1/environments/{env_a['id']}/devices/{edge_id}/revoke",
                           json={"schema_version": "enterprise-device-revoke/v1", "confirm_device_id": edge_id},
                           headers=tenant_a)
    assert response.status_code == 200
    response = client.post("/edge/v1/registration-recovery", json=recovery_body)
    assert response.status_code == 401
    assert response.json()["detail"] == "registration_recovery_denied"


def test_revocation_preserves_tasks_policy_and_other_devices(client, tenant_a, env_a):
    path, body, _ = setup(client, tenant_a, env_a)
    _, _, other_headers = setup(client, tenant_a, env_a)
    task_id = create_scan_task(client, tenant_a, env_a["id"])
    policy = client.post("/api/v1/policies", headers=tenant_a, json={
        "name": "preserved-" + uuid.uuid4().hex, "selector": {"agent_ids": ["synthetic-role"]},
        "enforcement_mode": "block",
    })
    assert policy.status_code == 201, policy.text
    policy_id = policy.json()["id"]

    def snapshot():
        with session_scope() as session:
            return [dict(session.execute(select(model.__table__).where(model.id == identity)).one()._mapping)
                    for model, identity in [(DesiredPolicy, policy_id), (EdgeTask, task_id)]]

    before = snapshot()
    assert client.post(path + "/revoke", json=body, headers=tenant_a).status_code == 200
    assert snapshot() == before
    assert client.post("/edge/v1/heartbeat", json={"version": "0.1.0"}, headers=other_headers).status_code == 200
    result = client.get(f"/api/v1/environments/{env_a['id']}/onboarding", headers=tenant_a)
    assert result.status_code == 200
    row = next(row for row in result.json()["devices"] if row["id"] == body["confirm_device_id"])
    assert row["status"] == "revoked"


def test_environment_read_does_not_grant_revocation(client, tenant_a, env_a):
    path, body, _ = setup(client, tenant_a, env_a)
    reader = dict(tenant_a, **{"X-Dev-Roles": "tenant_admin"})
    assert client.get(path + "/credential-status", headers=reader).status_code == 200
    assert client.post(path + "/revoke", json=body, headers=reader).status_code == 403


def test_commit_failure_rolls_back_and_original_request_can_retry(client, tenant_a, env_a, monkeypatch):
    from sqlalchemy.orm import Session

    path, body, _ = setup(client, tenant_a, env_a)
    before = counts()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail)
        assert client.post(path + "/revoke", json=body, headers=tenant_a).status_code == 503
    assert counts() == before
    with session_scope() as session:
        assert session.get(EdgeAgent, body["confirm_device_id"]).revoked_at is None
    assert client.post(path + "/revoke", json=body, headers=tenant_a).status_code == 200
    assert counts() == [before[0], before[1] + 1, before[2] + 1]


def test_export_device_lifecycle_wire(client, tenant_a, env_a, tmp_path):
    import json
    import os
    from pathlib import Path

    path, body, _ = setup(client, tenant_a, env_a)
    active = client.get(path + "/credential-status", headers=tenant_a)
    revoked = client.post(path + "/revoke", json=body, headers=tenant_a)
    before = counts()
    recovered = client.get(path + "/credential-status", headers=tenant_a)
    assert active.status_code == revoked.status_code == recovered.status_code == 200
    assert recovered.json() == revoked.json()
    assert counts() == before
    wire = {"scope": "isolated-testclient-sqlite-development-identities",
            "environment_id": env_a["id"], "device_id": body["confirm_device_id"],
            "active": active.json(), "revoked": revoked.json(), "recovered": recovered.json()}
    output = Path(os.environ.get("SIQ_DEVICE_WIRE_OUTPUT", str(tmp_path / "device-wire.json")))
    with output.open("x") as stream:
        json.dump(wire, stream)
    assert json.loads(output.read_text()) == wire


@pytest.mark.parametrize("supplied", [None, "device-correlation-123456", "invalid\ncorrelation"])
def test_revocation_trace_query_matches_normalized_request(client, tenant_a, tenant_b, env_a, supplied):
    path, body, _ = setup(client, tenant_a, env_a)
    headers = dict(tenant_a)
    if supplied is not None:
        headers["X-Request-ID"] = supplied
    response = client.post(path + "/revoke", json=body, headers=headers)
    assert response.status_code == 200
    correlation = response.headers["X-Request-ID"]
    if supplied == "device-correlation-123456":
        assert correlation == supplied
    else:
        assert correlation.startswith("req-") and "\n" not in correlation
    query = {"request_id": correlation, "resource_id": body["confirm_device_id"],
             "resource_type": "edge_agent", "action": "edge.device.revoke", "include_total": "true"}
    reader = dict(tenant_a, **{"X-Dev-Roles": "auditor"})
    before = counts()
    result = client.get("/api/v1/audit-events", params=query, headers=reader)
    assert result.status_code == 200
    assert len(result.json()) == 1
    event = result.json()[0]
    assert event["request_id"] == correlation
    assert event["actor_id"] == tenant_a["X-Dev-User-Id"]
    assert event["id"].startswith("aud_") and event["id"] != correlation
    assert event["summary"] == {"environment_id": env_a["id"], "device_id": body["confirm_device_id"]}
    assert client.get("/api/v1/audit-events", params=query, headers=tenant_b).json() == []
    assert counts() == before
    with session_scope() as session:
        events = list(session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "edge.device.revoked.v1")))
        emitted = next(event for event in events if event.payload["resource_ref"] == body["confirm_device_id"])
        assert emitted.payload["request_id"] == correlation
        assert emitted.payload["tenant_id"] == tenant_a["X-Dev-Tenant-Id"]
    retry_correlation = "device-retry-" + uuid.uuid4().hex
    retried = client.post(path + "/revoke", json=body, headers={**tenant_a, "X-Request-ID": retry_correlation})
    assert retried.status_code == 200 and retried.json() == response.json()
    assert counts() == before
    query["request_id"] = retry_correlation
    assert client.get("/api/v1/audit-events", params=query, headers=reader).json() == []
    # Correlation never creates a second transition event for an idempotent retry.
