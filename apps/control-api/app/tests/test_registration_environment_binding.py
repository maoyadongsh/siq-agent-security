import uuid

from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, EdgeAgent, EnrollmentToken
from app.security import hash_secret
from app.tests.edge_helpers import edge_public_key_pem


def test_wrong_environment_does_not_consume_code(client, tenant_a, env_a, env_b):
    identity = "bound-" + uuid.uuid4().hex
    code = client.post(f"/api/v1/environments/{env_a['id']}/edge-enrollment", json={}, headers=tenant_a).json()["code"]
    body = {
        "enrollment_code": code,
        "device_identity": identity,
        "public_key_pem": edge_public_key_pem(identity),
        "version": "0.1.0",
        "expected_environment_id": env_b["id"],
    }
    wrong = client.post("/edge/v1/register", json=body)
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "enrollment_invalid"
    with session_scope() as session:
        token = session.scalar(select(EnrollmentToken).where(EnrollmentToken.code_hash == hash_secret(code)))
        assert token.used_at is None
        assert session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity)) is None
        assert session.scalar(select(AuditEvent).where(AuditEvent.actor_id == identity)) is None
    body["expected_environment_id"] = env_a["id"]
    correct = client.post("/edge/v1/register", json=body)
    assert correct.status_code == 200
    assert correct.json()["environment_id"] == env_a["id"]
    assert client.post("/edge/v1/register", json=body).status_code == 401


def test_empty_expected_environment_rejected(client, tenant_a, env_a):
    identity = "bound-" + uuid.uuid4().hex
    code = client.post(f"/api/v1/environments/{env_a['id']}/edge-enrollment", json={}, headers=tenant_a).json()["code"]
    body = {
        "enrollment_code": code,
        "device_identity": identity,
        "public_key_pem": edge_public_key_pem(identity),
        "version": "0.1.0",
        "expected_environment_id": "",
    }
    assert client.post("/edge/v1/register", json=body).status_code == 422
    del body["expected_environment_id"]
    assert client.post("/edge/v1/register", json=body).status_code == 200
