"""Batch response-loss recovery is read-only and bound to the original verified identity."""

import uuid

import pytest

from app.db import session_scope
from app.models import ChangeRequest
from app.tests.test_change_review import approver, decide, review
from app.tests.test_network_revoke_batches import request, submit
from app.tests.test_network_revoke_proposals import counts, setup


def url(body):
    return f"/api/v1/network-revoke-batches/{body['request_key']}"


def test_current_per_item_status_without_replay_or_writes(client, tenant_a):
    body = request(client, tenant_a)
    created = submit(client, tenant_a, body)
    assert created.status_code == 201, created.text
    items = created.json()['items']
    with session_scope() as session:
        session.get(ChangeRequest, items[0]['change_request_id']).status = 'failed'
        session.commit()
    before = counts()
    for _ in range(2):
        response = client.get(url(body), headers=tenant_a)
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.json() == {
            'schema_version': 'enterprise-network-revoke-batch-recovery/v1', 'lookup_executed': False,
            'items': [{'source_policy_id': item['source_policy_id'], 'policy_id': item['policy_id'],
                       'change_request_id': item['change_request_id'],
                       'change_status': 'failed' if index == 0 else 'proposed'}
                      for index, item in enumerate(items)],
        }
        assert 'api.example.com' not in response.text
    assert counts() == before


def test_approving_one_child_does_not_approve_the_batch(client, tenant_a):
    body = request(client, tenant_a)
    created = submit(client, tenant_a, body).json()['items']
    reviewer = approver(tenant_a)
    cr = {'id': created[0]['change_request_id']}
    snapshot = review(client, reviewer, cr)
    assert snapshot['can_approve'] is True
    decision = decide(client, reviewer, cr, snapshot)
    assert decision.status_code == 200, decision.text
    before = counts()
    response = client.get(url(body), headers=tenant_a)
    assert response.status_code == 200, response.text
    assert [item['change_status'] for item in response.json()['items']] == ['approved', 'proposed']
    assert counts() == before


@pytest.mark.parametrize('case', [
    'tenant', 'actor', 'permission', 'unknown', 'legacy', 'type', 'child_actor', 'child_type',
    'missing_child', 'child_tenant', 'source', 'manifest', 'digest', 'oversized_manifest',
])
def test_no_partial_or_foreign_recovery(client, tenant_a, tenant_b, case):
    body = request(client, tenant_a)
    created = submit(client, tenant_a, body).json()['items']
    headers, expected = tenant_a, 404
    if case == 'tenant':
        headers = tenant_b
    elif case == 'actor':
        headers = {**tenant_a, 'X-Dev-User-Id': 'other-proposer'}
    elif case == 'permission':
        headers, expected = {**tenant_a, 'X-Dev-Roles': 'viewer'}, 403
    elif case == 'unknown':
        body['request_key'] = str(uuid.uuid4())
    elif case == 'child_tenant':
        foreign, _ = setup(client, {**tenant_b, 'X-Dev-Roles': 'security_admin,agent_owner'})
        with session_scope() as session:
            session.get(ChangeRequest, created[-1]['change_request_id']).policy_id = foreign['id']
            session.commit()
    else:
        with session_scope() as session:
            index = 0 if case in ('legacy', 'type', 'oversized_manifest') else -1
            cr = session.get(ChangeRequest, created[index]['change_request_id'])
            impact = dict(cr.impact)
            if case == 'legacy':
                impact.pop('batch_manifest')
            elif case in ('type', 'child_type'):
                impact['proposal_actor_type'] = 'service'
            elif case == 'child_actor':
                cr.proposer_user_id = 'different-actor'
            elif case == 'source':
                impact['source_policy_id'] = created[0]['source_policy_id']
            elif case == 'manifest':
                impact['batch_manifest'] = {**impact['batch_manifest'], 'batch_digest': '0' * 64}
            elif case == 'digest':
                impact['network_revoke_request_digest'] = '0' * 64
            elif case == 'oversized_manifest':
                impact['batch_manifest'] = {**impact['batch_manifest'], 'policy_ids': ['p'] * 21}
            elif case == 'missing_child':
                session.delete(cr)  # Only the disposable fixture DB; simulate incomplete durable state.
            cr.impact = impact
            session.commit()
    before = counts()
    response = client.get(url(body), headers=headers)
    assert response.status_code == expected, response.text
    assert all(item['change_request_id'] not in response.text for item in created)
    assert counts() == before
