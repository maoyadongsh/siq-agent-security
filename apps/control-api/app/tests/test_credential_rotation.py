import hashlib
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, EdgeAgent, EdgeCredentialRotation, OutboxEvent
from app.routers.credential_rotation import RotateCredential
from app.routers.registration_recovery import RecoveryRequest
from app.security import mint_edge_device_secret
from app.tests.edge_helpers import edge_private_key, register_edge


@pytest.fixture
def rotation(client, tenant_a):
    env = client.post('/api/v1/environments', headers=tenant_a,
                      json={'name': 'rotation-' + uuid.uuid4().hex}).json()['id']
    identity = 'rotation-' + uuid.uuid4().hex
    headers, key = register_edge(client, tenant_a, env, identity)
    old_secret = headers['Authorization'].removeprefix('Bearer ')
    new_secret = mint_edge_device_secret()
    body = {'schema_version': 'edge-credential-rotation/v1', 'device_identity': identity,
            'environment_id': env, 'rotation_id': str(uuid.uuid4()),
            'expected_secret_hash': hashlib.sha256(old_secret.encode()).hexdigest(),
            'new_secret_hash': hashlib.sha256(new_secret.encode()).hexdigest(), 'signature': '0' * 128}
    sign(body, key)
    return headers, {**headers, 'Authorization': 'Bearer ' + new_secret}, body, key


def sign(body, key):
    body['signature'] = key.sign(RotateCredential(**body).signed_bytes()).hex()


def post(client, headers, body):
    return client.post('/edge/v1/credential-rotation', headers=headers, json=body)


def counts():
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(model))
                for model in (EdgeCredentialRotation, AuditEvent, OutboxEvent)]


def test_success_lost_response_retry_and_no_secret_disclosure(client, rotation):
    old, new, body, _ = rotation
    before = counts()
    response = post(client, old, body)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['runtime_permissions_changed'] is False
    assert counts() == [value + 1 for value in before]
    after = counts()
    assert post(client, old, body).status_code == 401
    assert post(client, new, body).json() == response.json()
    assert counts() == after
    assert client.post('/edge/v1/heartbeat', headers=old, json={'version': '0.1'}).status_code == 401
    assert client.post('/edge/v1/heartbeat', headers=new, json={'version': '0.1'}).status_code == 200
    with session_scope() as session:
        audit = session.scalar(select(AuditEvent).where(AuditEvent.resource_id == response.json()['edge_agent_id'],
                                                       AuditEvent.action == 'edge.credential.rotate'))
        assert audit.actor_id == body['device_identity']
        assert audit.request_id == response.headers['X-Request-ID']
        emitted = session.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == 'edge.credential.rotated.v1')).all()
        envelope = next(row.payload for row in emitted if row.payload['resource_ref'] == audit.resource_id)
        combined = response.text + json.dumps(audit.summary) + json.dumps(envelope)
        for secret in [old['Authorization'][7:], new['Authorization'][7:], body['signature'],
                       body['expected_secret_hash'], body['new_secret_hash']]:
            assert secret not in combined


@pytest.mark.parametrize('case', [
    'signature', 'device', 'environment', 'baseline', 'same_hash', 'revoked', 'no_bearer',
])
def test_invalid_rotation_preserves_state(client, rotation, case):
    old, _, original, key = rotation
    body = dict(original)
    if case == 'device':
        body['device_identity'] = 'different-device'
    if case == 'environment':
        body['environment_id'] = 'different-env'
    if case == 'baseline':
        body['expected_secret_hash'] = 'a' * 64
    if case == 'same_hash':
        body['new_secret_hash'] = body['expected_secret_hash']
    sign(body, edge_private_key('wrong-key') if case == 'signature' else key)
    if case == 'revoked':
        from app.models import utcnow
        with session_scope() as session:
            edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == body['device_identity']))
            edge.revoked_at = utcnow()
    before = counts()
    result = post(client, {} if case == 'no_bearer' else old, body)
    assert result.status_code == (409 if case in ('baseline', 'same_hash') else 401)
    assert counts() == before
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == original['device_identity']))
        assert edge.secret_hash == original['expected_secret_hash']


def test_old_hash_reuse_and_superseded_request_denied(client, rotation):
    old, new, body, key = rotation
    assert post(client, old, body).status_code == 200
    second_secret = mint_edge_device_secret()
    second = dict(body, rotation_id=str(uuid.uuid4()), expected_secret_hash=body['new_secret_hash'],
                  new_secret_hash=hashlib.sha256(second_secret.encode()).hexdigest())
    sign(second, key)
    assert post(client, new, second).status_code == 200
    latest = {**new, 'Authorization': 'Bearer ' + second_secret}
    before = counts()
    assert post(client, latest, body).status_code == 409
    for reused in (body['expected_secret_hash'], body['new_secret_hash']):
        attempt = dict(second, rotation_id=str(uuid.uuid4()), expected_secret_hash=second['new_secret_hash'],
                       new_secret_hash=reused)
        sign(attempt, key)
        assert post(client, latest, attempt).status_code == 409
    changed = dict(second, new_secret_hash='b' * 64)
    sign(changed, key)
    assert post(client, latest, changed).status_code == 409
    assert counts() == before


@pytest.mark.parametrize('operation', ['audit', 'emit_event', 'commit'])
def test_transaction_failure_rolls_back(client, rotation, monkeypatch, operation):
    from sqlalchemy.orm import Session
    old, _, body, _ = rotation
    before = counts()

    def fail(*args, **kwargs):
        raise RuntimeError('synthetic private failure')

    with monkeypatch.context() as patch:
        if operation == 'commit':
            patch.setattr(Session, 'commit', fail)
        else:
            patch.setattr('app.routers.credential_rotation.' + operation, fail)
        response = post(client, old, body)
    assert response.status_code == 503
    assert 'private' not in response.text
    assert counts() == before
    assert client.post('/edge/v1/heartbeat', headers=old, json={'version': '0.1'}).status_code == 200
    assert post(client, old, body).status_code == 200


def test_initial_registration_recovery_cannot_bypass_rotation(client, rotation):
    old, _, body, key = rotation
    assert post(client, old, body).status_code == 200
    recovery = {'schema_version': 'edge-registration-recovery/v1', 'device_identity': body['device_identity'],
                'environment_id': body['environment_id'], 'secret_hash': body['expected_secret_hash'],
                'signature': '0' * 128}
    recovery['signature'] = key.sign(RecoveryRequest(**recovery).signed_bytes()).hex()
    before = counts()
    assert client.post('/edge/v1/registration-recovery', json=recovery).status_code == 401
    assert counts() == before


@pytest.mark.parametrize('patch', [{'tenant_id': 'foreign'}, {'schema_version': 'v0'},
                                  {'rotation_id': 'invalid'}, {'new_secret_hash': 'short'}])
def test_extra_or_malformed_fields_rejected(client, rotation, patch):
    old, _, body, _ = rotation
    before = counts()
    assert post(client, old, body | patch).status_code == 422
    assert counts() == before


def test_management_identity_headers_cannot_override_device_tenant(client, rotation, tenant_b):
    old, _, body, _ = rotation
    response = post(client, {**tenant_b, **old}, body)
    assert response.status_code == 200
    with session_scope() as session:
        event = session.scalar(select(AuditEvent).where(
            AuditEvent.resource_id == response.json()['edge_agent_id'],
            AuditEvent.action == 'edge.credential.rotate'))
        assert event.tenant_id == 'tnt-A'
        assert event.actor_type == 'edge' and event.actor_id == body['device_identity']
