"""Atomic batch proposals on isolated SQLite; no runtime execution or production claims."""

import copy
import uuid

import pytest

from app.db import session_scope
from app.models import ChangeRequest, DesiredPolicy
from app.tests.test_network_revoke_proposals import counts, setup


def request(client, headers):
    items = []
    for _ in range(2):
        source, body = setup(client, headers)
        items.append({'policy_id': source['id'], 'baseline_digest': body['baseline_digest'],
                      'selections': body['selections']})
    return {'schema_version': 'enterprise-network-revoke-batch/v1', 'request_key': str(uuid.uuid4()),
            'items': sorted(items, key=lambda item: item['policy_id'])}


def submit(client, headers, body):
    return client.post('/api/v1/network-revoke-batches', headers=headers, json=body)


def test_atomic_proposed_children_and_reordered_replay(client, tenant_a):
    body = request(client, tenant_a)
    before = counts()
    response = submit(client, tenant_a, body)
    assert response.status_code == 201, response.text
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['executed'] is False and data['requires_independent_approval'] is True
    assert [new - old for new, old in zip(counts(), before, strict=True)] == [2, 2, 4, 2, 0, 0]
    assert [item['source_policy_id'] for item in data['items']] == [item['policy_id'] for item in body['items']]
    for item in data['items']:
        with session_scope() as session:
            assert session.get(DesiredPolicy, item['source_policy_id']).network
            assert session.get(DesiredPolicy, item['policy_id']).network == []
            change = session.get(ChangeRequest, item['change_request_id'])
            assert change.status == 'proposed' and change.approver_user_id is None
        denied = client.post(f"/api/v1/change-requests/{item['change_request_id']}/approve",
                             headers=tenant_a, json={})
        assert denied.status_code == 409 and denied.json()['detail'] == 'segregation_of_duties'
    saved = counts()
    body['items'].reverse()
    assert submit(client, tenant_a, body).json() == data
    assert counts() == saved


@pytest.mark.parametrize('case,expected', [
    ('baseline', 409), ('selection', 422), ('foreign', 404), ('permission', 403),
    ('duplicate', 422), ('extra', 422), ('empty', 422), ('budget', 422),
])
def test_invalid_batch_leaves_no_partial_state(client, tenant_a, tenant_b, case, expected):
    body = request(client, tenant_a)
    headers = tenant_a
    if case == 'baseline':
        body['items'][-1]['baseline_digest'] = '0' * 64
    elif case == 'selection':
        body['items'][-1]['selections'][0]['endpoint'] = 'not-in-policy.example:443'
    elif case == 'foreign':
        foreign, _ = setup(client, {**tenant_b, 'X-Dev-Roles': 'security_admin,agent_owner'})
        body['items'][-1]['policy_id'] = foreign['id']
    elif case == 'permission':
        headers = {**tenant_a, 'X-Dev-Roles': 'viewer'}
    elif case == 'duplicate':
        body['items'].append(copy.deepcopy(body['items'][0]))
    elif case == 'extra':
        body['items'][-1]['approval_policy'] = 'emergency'
    elif case == 'empty':
        body['items'] = []
    else:
        body['items'] *= 11
    before = counts()
    response = submit(client, headers, body)
    assert response.status_code == expected, response.text
    assert counts() == before


@pytest.mark.parametrize('case', ['actor', 'subset', 'replaced', 'selection'])
def test_batch_key_binds_entire_input(client, tenant_a, case):
    body = request(client, tenant_a)
    assert submit(client, tenant_a, body).status_code == 201
    headers = tenant_a
    if case == 'actor':
        headers = {**tenant_a, 'X-Dev-User-Id': 'another-proposer'}
    elif case == 'subset':
        body['items'].pop()
    elif case == 'replaced':
        body['items'] = request(client, tenant_a)['items']
    else:
        body['items'][0]['selections'][0]['binary_path'] = '/bin/other'
    before = counts()
    response = submit(client, headers, body)
    assert response.status_code == 409, response.text
    assert counts() == before


def test_second_item_audit_failure_rolls_back_entire_batch(client, tenant_a, monkeypatch):
    from app.routers import network_revoke_proposals

    body = request(client, tenant_a)
    original = network_revoke_proposals.audit
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError('private diagnostic must not leave service')
        return original(*args, **kwargs)

    monkeypatch.setattr(network_revoke_proposals, 'audit', fail)
    before = counts()
    response = submit(client, tenant_a, body)
    assert response.status_code == 503, response.text
    assert response.json()['detail'] == 'network_revoke_batch_unavailable'
    assert counts() == before
    monkeypatch.setattr(network_revoke_proposals, 'audit', original)
    assert submit(client, tenant_a, body).status_code == 201


def test_two_versions_of_same_family_rejected(client, tenant_a):
    body = request(client, tenant_a)
    with session_scope() as session:
        first, second = [session.get(DesiredPolicy, item['policy_id']) for item in body['items']]
        second.name, second.version = first.name, first.version + 1
        session.commit()
    before = counts()
    response = submit(client, tenant_a, body)
    assert response.status_code == 422
    assert response.json()['detail'] == 'network_revoke_batch_duplicate_policy_family'
    assert counts() == before


def test_total_selection_budget_is_separate_from_item_limit(client, tenant_a):
    body = request(client, tenant_a)
    source, single = setup(client, tenant_a)
    body['items'].append({'policy_id': source['id'], 'baseline_digest': single['baseline_digest'],
                          'selections': single['selections']})
    for item in body['items']:
        item['selections'] *= 171
    before = counts()
    response = submit(client, tenant_a, body)
    assert response.status_code == 422
    assert 'selection_budget_exceeded' in response.text
    assert counts() == before


def test_incomplete_persisted_batch_is_not_silently_repaired(client, tenant_a):
    body = request(client, tenant_a)
    response = submit(client, tenant_a, body)
    assert response.status_code == 201
    # Fault injection only in the disposable test DB, never a supported cancellation operation.
    with session_scope() as session:
        session.delete(session.get(ChangeRequest, response.json()['items'][-1]['change_request_id']))
        session.commit()
    before = counts()
    response = submit(client, tenant_a, body)
    assert response.status_code == 409
    assert response.json()['detail'] == 'network_revoke_batch_incomplete'
    assert counts() == before


def test_same_uuid_in_two_tenants_does_not_share_results(client, tenant_a, tenant_b):
    other = {**tenant_b, 'X-Dev-Roles': 'security_admin,agent_owner'}
    first, second = request(client, tenant_a), request(client, other)
    second['request_key'] = first['request_key']
    response_a, response_b = submit(client, tenant_a, first), submit(client, other, second)
    assert response_a.status_code == response_b.status_code == 201
    assert {item['change_request_id'] for item in response_a.json()['items']}.isdisjoint(
        item['change_request_id'] for item in response_b.json()['items'])
