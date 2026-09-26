import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, DesiredPolicy, EdgeTask, OutboxEvent
from app.tests.test_policy_flow import _create_policy


def setup(client, headers):
    policy = _create_policy(client, headers, enforcement_mode="block")
    baseline = client.get(f"/api/v1/policies/{policy['id']}/network-revoke-baseline", headers=headers)
    assert baseline.status_code == 200, baseline.text
    return policy, {"schema_version": "enterprise-network-revoke-proposal/v1",
                    "baseline_digest": baseline.json()["baseline_digest"], "request_key": str(uuid.uuid4()),
                    "selections": [{"endpoint": "api.example.com:443", "binary_path": "/usr/bin/curl"}]}


def counts():
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(model)) for model in
                (DesiredPolicy, ChangeRequest, AuditEvent, OutboxEvent, Deployment, EdgeTask)]


def post(client, headers, policy, body):
    return client.post(f"/api/v1/policies/{policy['id']}/network-revoke-proposals", headers=headers, json=body)


def test_new_version_proposed_audited_not_approved_or_executed(client, tenant_a):
    source, body = setup(client, tenant_a)
    before = counts()
    response = post(client, tenant_a, source, body)
    assert response.status_code == 201, response.text
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['executed'] is False
    assert data['requires_independent_approval'] is True
    assert [new - old for new, old in zip(counts(), before, strict=True)] == [1, 1, 2, 1, 0, 0]
    with session_scope() as session:
        policy = session.get(DesiredPolicy, data['policy_id'])
        original = session.get(DesiredPolicy, source['id'])
        change = session.get(ChangeRequest, data['change_request_id'])
        assert policy.version == original.version + 1
        assert policy.network == [] and original.network
        assert policy.selector == original.selector and policy.enforcement_mode == 'block'
        assert change.status == 'proposed' and change.approver_user_id is None
    saved = counts()
    assert post(client, tenant_a, source, body).json() == data
    assert counts() == saved
    denied = client.post(f"/api/v1/change-requests/{data['change_request_id']}/approve", headers=tenant_a, json={})
    assert denied.status_code == 409
    assert denied.json()['detail'] == 'segregation_of_duties'


@pytest.mark.parametrize('case', ['tenant', 'permission', 'baseline', 'stale', 'extra'])
def test_invalid_request_no_state_change(client, tenant_a, tenant_b, case):
    policy, body = setup(client, tenant_a)
    headers, expected = tenant_a, 422
    if case == 'tenant':
        headers, expected = tenant_b, 404
    elif case == 'permission':
        headers, expected = {**tenant_a, 'X-Dev-Roles': 'viewer'}, 403
    elif case == 'baseline':
        body['baseline_digest'], expected = '0' * 64, 409
    elif case == 'stale':
        body['selections'][0]['endpoint'] = 'different.example:443'
    else:
        body['tenant_id'] = 'injected'
    before = counts()
    response = post(client, headers, policy, body)
    assert response.status_code == expected, response.text
    assert counts() == before


@pytest.mark.parametrize('case', ['actor', 'selection'])
def test_same_key_different_request_denied(client, tenant_a, case):
    policy, body = setup(client, tenant_a)
    assert post(client, tenant_a, policy, body).status_code == 201
    headers = tenant_a
    if case == 'actor':
        headers = {**tenant_a, 'X-Dev-User-Id': 'someone-else'}
    else:
        body['selections'][0]['binary_path'] = '/bin/other'
    before = counts()
    response = post(client, headers, policy, body)
    assert response.status_code == 409
    assert response.json()['detail'] == 'network_revoke_request_conflict'
    assert counts() == before


def test_audit_failure_rolls_back_policy_change_and_outbox(client, tenant_a, monkeypatch):
    from app.routers import network_revoke_proposals

    policy, body = setup(client, tenant_a)
    before = counts()

    original = network_revoke_proposals.audit
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('private backend diagnostic')
        return original(*args, **kwargs)

    monkeypatch.setattr(network_revoke_proposals, 'audit', fail)
    response = post(client, tenant_a, policy, body)
    assert response.status_code == 503
    assert 'private' not in response.text
    assert counts() == before


def test_actual_baseline_drift_refused(client, tenant_a):
    policy, body = setup(client, tenant_a)
    with session_scope() as session:
        source = session.get(DesiredPolicy, policy['id'])
        source.filesystem = {'read_only': ['/changed']}
        session.commit()
    before = counts()
    response = post(client, tenant_a, policy, body)
    assert response.status_code == 409
    assert response.json()['detail'] == 'network_revoke_baseline_changed'
    assert counts() == before


def test_same_client_key_is_tenant_scoped(client, tenant_a, tenant_b):
    # Synthetic proposer permissions in tenant B; no cross-tenant object access.
    other = {**tenant_b, 'X-Dev-Roles': 'security_admin,agent_owner'}
    policy_a, body_a = setup(client, tenant_a)
    policy_b, body_b = setup(client, other)
    body_b['request_key'] = body_a['request_key']
    first = post(client, tenant_a, policy_a, body_a)
    second = post(client, other, policy_b, body_b)
    assert first.status_code == second.status_code == 201
    assert first.json()['change_request_id'] != second.json()['change_request_id']
