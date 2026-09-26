import hashlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, EdgeAgent, EdgeRegistrationRecovery, utcnow
from app.routers.registration_recovery import RecoveryRequest
from app.tests.edge_helpers import edge_private_key, register_edge


def setup_recovery(client, tenant, environment):
    identity = "recovery-" + uuid.uuid4().hex
    headers, key = register_edge(client, tenant, environment, identity)
    secret = "edge-recovery-" + uuid.uuid4().hex + uuid.uuid4().hex
    body = {
        "schema_version": "edge-registration-recovery/v1",
        "device_identity": identity,
        "environment_id": environment,
        "secret_hash": hashlib.sha256(secret.encode()).hexdigest(),
        "signature": "0" * 128,
    }
    body["signature"] = key.sign(RecoveryRequest(**body).signed_bytes()).hex()
    return identity, headers, secret, body, key


def test_recover_and_idempotent_retry(client, tenant_a, env_a):
    identity, old_headers, secret, body, key = setup_recovery(client, tenant_a, env_a["id"])
    response = client.post("/edge/v1/registration-recovery", json=body)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert secret not in response.text and "device_secret" not in response.text
    assert client.post("/edge/v1/heartbeat", json={"version": "0.1.0"}, headers=old_headers).status_code == 401
    new_headers = {"X-Edge-Identity": identity, "Authorization": "Bearer " + secret}
    assert client.post("/edge/v1/heartbeat", json={"version": "0.1.0"}, headers=new_headers).status_code == 200
    assert client.post("/edge/v1/registration-recovery", json=body).json() == response.json()
    changed = dict(body, secret_hash="a" * 64)
    changed["signature"] = key.sign(RecoveryRequest(**changed).signed_bytes()).hex()
    assert client.post("/edge/v1/registration-recovery", json=changed).status_code == 401
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        assert edge.secret_hash == body["secret_hash"]
        assert session.get(EdgeRegistrationRecovery, edge.id) is not None
        audits = session.scalars(select(AuditEvent).where(AuditEvent.resource_id == edge.id)).all()
        assert sum(a.action == "edge.registration.recover" for a in audits) == 1
        edge.revoked_at = utcnow()
    assert client.post("/edge/v1/registration-recovery", json=body).status_code == 401


@pytest.mark.parametrize("reason", ["wrong_key", "environment", "expired", "heartbeat", "revoked", "changed_hash"])
def test_recovery_denial_preserves_credential(client, tenant_a, env_a, env_b, reason):
    identity, headers, _, body, key = setup_recovery(client, tenant_a, env_a["id"])
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        old_hash = edge.secret_hash
        if reason == "expired":
            edge.registered_at = utcnow() - timedelta(minutes=16)
        if reason == "heartbeat":
            edge.last_seen_at = utcnow()
        if reason == "revoked":
            edge.revoked_at = utcnow()
    if reason == "wrong_key":
        body["signature"] = edge_private_key("other").sign(RecoveryRequest(**body).signed_bytes()).hex()
    if reason == "environment":
        body["environment_id"] = env_b["id"]
        body["signature"] = key.sign(RecoveryRequest(**body).signed_bytes()).hex()
    if reason == "changed_hash":
        body["secret_hash"] = "b" * 64
    response = client.post("/edge/v1/registration-recovery", json=body)
    assert response.status_code == 401
    assert response.json()["detail"] == "registration_recovery_denied"
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        assert edge.secret_hash == old_hash
        assert session.get(EdgeRegistrationRecovery, edge.id) is None


def test_recovery_audit_failure_rolls_back(client, tenant_a, env_a, monkeypatch):
    identity, _, _, body, _ = setup_recovery(client, tenant_a, env_a["id"])

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr("app.routers.registration_recovery.audit", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        client.post("/edge/v1/registration-recovery", json=body)
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        assert edge.secret_hash != body["secret_hash"]
        assert session.get(EdgeRegistrationRecovery, edge.id) is None
