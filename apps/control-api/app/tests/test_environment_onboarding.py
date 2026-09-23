"""Real database projections for enterprise onboarding; no inferred protection."""

import json
from datetime import timedelta
from pathlib import Path

import jsonschema
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, EdgeAgent, EdgeTask, Environment, Evidence, OutboxEvent, utcnow
from app.tests.test_enrollment_flow import _register_edge

CONTRACTS = Path(__file__).resolve().parents[4] / "packages/contracts"


def test_onboarding_access_and_tenant_boundaries(client, tenant_a, tenant_b, env_a, env_b):
    access = client.get("/api/v1/environments/access", headers=tenant_a)
    assert access.status_code == 200
    assert access.json()["can_enroll"] is True
    jsonschema.validate(
        access.json(), json.loads((CONTRACTS / "environment-onboarding-access.v1.schema.json").read_text())
    )
    readonly = {**tenant_a, "X-Dev-Roles": "security_admin"}
    assert client.get("/api/v1/environments/access", headers=readonly).json()["can_create"] is False
    route = f"/api/v1/environments/{env_a['id']}/onboarding"
    assert client.get(route, headers=tenant_b).status_code == 404
    no_env = {**tenant_a, "X-Dev-Roles": "viewer"}
    assert client.get(route, headers=no_env).status_code == 403
    assert client.get(f"/api/v1/environments/{env_b['id']}/onboarding", headers=no_env).status_code == 404
    assert (
        client.post(f"/api/v1/environments/{env_a['id']}/edge-enrollment", headers=readonly, json={}).status_code == 403
    )


def test_onboarding_real_registration_heartbeat_and_read_only_projection(client, tenant_a, tenant_b):
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": "onboard-states"}).json()
    foreign = client.post("/api/v1/environments", headers=tenant_b, json={"name": "onboard-states"}).json()
    route = f"/api/v1/environments/{env['id']}/onboarding"
    registered = _register_edge(client, env["id"], tenant_a, "onboard-device-1").json()
    secret = registered["device_secret"]
    waiting = client.get(route, headers=tenant_a).json()
    assert waiting["devices"][0]["status"] == "waiting"
    headers = {"X-Edge-Identity": "onboard-device-1", "Authorization": f"Bearer {secret}"}
    assert client.post("/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0"}).status_code == 200
    with session_scope() as session:
        edge = session.get(EdgeAgent, registered["edge_agent_id"])
        edge.capabilities = {
            "connectors": ["hermes", "openclaw", "unknown-private-config"],
            "secret": "PRIVATE-CAPABILITY",
        }
        session.add(
            Evidence(
                tenant_id=tenant_a["X-Dev-Tenant-Id"],
                environment_id=env["id"],
                evidence_id="onboard-evidence",
                source_type="hermes_profile",
                source_locator="PRIVATE-PATH",
                observed_at=utcnow(),
                collector_id="onboard-device-1",
                connector_version="1",
                content_hash="a" * 64,
                signature="sig",
            )
        )
        session.add(
            Evidence(
                tenant_id=tenant_b["X-Dev-Tenant-Id"],
                environment_id=foreign["id"],
                evidence_id="foreign-onboard",
                source_type="hermes_profile",
                source_locator="FOREIGN-PATH",
                observed_at=utcnow(),
                collector_id="foreign",
                connector_version="1",
                content_hash="b" * 64,
                signature="sig",
            )
        )
    with session_scope() as session:
        audit_before = session.scalar(select(func.count(AuditEvent.id)))
    got = client.get(route, headers=tenant_a)
    assert got.status_code == 200
    value = got.json()
    assert value["device_count"] == 1 and value["evidence_count"] == 1
    assert value["devices"][0]["status"] == "online"
    assert value["devices"][0]["connectors"] == ["hermes", "openclaw"]
    assert value["devices"][0]["last_seen_at"].endswith("Z") and value["evaluated_at"].endswith("Z")
    for forbidden in [secret, "secret_hash", "public_key_pem", "PRIVATE", "FOREIGN"]:
        assert forbidden not in got.text
    jsonschema.validate(value, json.loads((CONTRACTS / "environment-onboarding.v1.schema.json").read_text()))
    with session_scope() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == audit_before
        edge = session.get(EdgeAgent, registered["edge_agent_id"])
        edge.last_seen_at = utcnow() - timedelta(days=1)
    assert client.get(route, headers=tenant_a).json()["devices"][0]["status"] == "stale"
    with session_scope() as session:
        session.get(EdgeAgent, registered["edge_agent_id"]).revoked_at = utcnow()
    assert client.get(route, headers=tenant_a).json()["devices"][0]["status"] == "revoked"


def test_onboarding_limits_and_expiry_are_not_mutations(client, tenant_a):
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": "onboard-limits"}).json()
    with session_scope() as session:
        for i in range(101):
            session.add(
                EdgeAgent(
                    environment_id=env["id"],
                    device_identity=f"onboard-limit-{i}",
                    secret_hash="x",
                    public_key_pem="x",
                    version="0.1",
                )
            )
        for i in range(21):
            session.add(
                EdgeTask(
                    id=f"onboard-limit-{i}",
                    environment_id=env["id"],
                    task_type="scan",
                    payload={"connector": "hermes", "scope": {"secret": "PRIVATE"}},
                    expires_at=utcnow() - timedelta(seconds=1),
                )
            )
    value = client.get(f"/api/v1/environments/{env['id']}/onboarding", headers=tenant_a).json()
    assert len(value["devices"]) == 100 and value["device_count"] == 101 and value["devices_truncated"]
    assert len(value["scans"]) == 20 and value["scans_truncated"]
    assert all(s["status"] == "expired" and s["candidate_count"] is None for s in value["scans"])
    assert "PRIVATE" not in str(value)
    with session_scope() as session:
        assert session.get(EdgeTask, "onboard-limit-1").status == "pending"


def test_duplicate_environment_is_conflict_and_rolls_back_audit(client, tenant_a):
    body = {"name": "onboard-duplicate"}
    first = client.post("/api/v1/environments", headers=tenant_a, json=body)
    assert first.status_code == 201
    with session_scope() as session:
        before = [session.scalar(select(func.count(model.id))) for model in (Environment, AuditEvent, OutboxEvent)]
    duplicate = client.post("/api/v1/environments", headers=tenant_a, json=body)
    assert duplicate.status_code == 409
    with session_scope() as session:
        after = [session.scalar(select(func.count(model.id))) for model in (Environment, AuditEvent, OutboxEvent)]
        assert before == after
