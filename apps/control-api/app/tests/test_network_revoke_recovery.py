import uuid

import pytest

from app.db import session_scope
from app.models import ChangeRequest
from app.tests.test_network_revoke_proposals import counts, post, setup


def url(policy, body):
    return f"/api/v1/policies/{policy['id']}/network-revoke-proposals/{body['request_key']}"


def test_recovery_reads_current_status_without_replaying(client, tenant_a):
    policy, body = setup(client, tenant_a)
    created = post(client, tenant_a, policy, body).json()
    # Lost-response recovery uses the saved request key, not a replacement POST.
    before = counts()
    for _ in range(2):
        response = client.get(url(policy, body), headers=tenant_a)
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.json() == {
            'schema_version': 'enterprise-network-revoke-recovery/v1', 'source_policy_id': policy['id'],
            'policy_id': created['policy_id'], 'change_request_id': created['change_request_id'],
            'change_status': 'proposed', 'lookup_executed': False,
        }
    assert counts() == before
    with session_scope() as session:
        session.get(ChangeRequest, created['change_request_id']).status = 'failed'
        session.commit()
    response = client.get(url(policy, body), headers=tenant_a)
    assert response.json()['change_status'] == 'failed'
    assert response.json()['lookup_executed'] is False
    assert counts() == before


@pytest.mark.parametrize('case', ['tenant', 'actor', 'permission', 'key', 'source', 'legacy', 'type', 'child_tenant'])
def test_recovery_denials_do_not_leak_or_write(client, tenant_a, tenant_b, case):
    policy, body = setup(client, tenant_a)
    created = post(client, tenant_a, policy, body).json()
    headers, expected = tenant_a, 404
    if case == 'tenant':
        headers = tenant_b
    elif case == 'actor':
        headers = {**tenant_a, 'X-Dev-User-Id': 'different-actor'}
    elif case == 'permission':
        headers, expected = {**tenant_a, 'X-Dev-Roles': 'viewer'}, 403
    elif case == 'key':
        body['request_key'] = str(uuid.uuid4())
    elif case == 'source':
        policy, _ = setup(client, tenant_a)
    elif case == 'child_tenant':
        other, _ = setup(client, {**tenant_b, 'X-Dev-Roles': 'security_admin,agent_owner'})
        with session_scope() as session:
            session.get(ChangeRequest, created['change_request_id']).policy_id = other['id']
            session.commit()
    else:
        with session_scope() as session:
            cr = session.get(ChangeRequest, created['change_request_id'])
            impact = dict(cr.impact)
            if case == 'legacy':
                impact.pop('proposal_actor_type')
            else:
                impact['proposal_actor_type'] = 'service'
            cr.impact = impact
            session.commit()
    before = counts()
    response = client.get(url(policy, body), headers=headers)
    assert response.status_code == expected, response.text
    assert created['change_request_id'] not in response.text
    assert counts() == before
