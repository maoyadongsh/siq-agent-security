"""Proposal-to-review-to-submission integration; isolated DB and fake runtime only."""

import uuid

from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, DesiredPolicy
from app.tests.binding_helpers import make_binding
from app.tests.test_change_review import approver, decide, review
from app.tests.test_deployment_preview import counts as deployment_counts
from app.tests.test_deployment_preview import preview
from app.tests.test_network_revoke_proposals import post
from app.tests.test_policy_flow import _create_policy


def proposal(client, headers, env):
    binding, asset, _ = make_binding(client, headers, env['id'])
    source = _create_policy(client, headers, agent_ids=[asset], enforcement_mode='block')
    response = client.get(f"/api/v1/policies/{source['id']}/network-revoke-options", headers=headers)
    assert response.status_code == 200, response.text
    options = response.json()
    body = {
        'schema_version': 'enterprise-network-revoke-proposal/v1',
        'baseline_digest': options['baseline_digest'],
        'request_key': str(uuid.uuid4()),
        'selections': options['selections'],
    }
    created = post(client, headers, source, body)
    assert created.status_code == 201, created.text
    result = created.json()
    selection = {
        'schema_version': 'deployment-preview-request/v1',
        'change_request_id': result['change_request_id'],
        'environment_id': env['id'],
        'binding_id': binding['id'],
    }
    return source, body, result, selection


def test_revoke_uses_independent_review_and_durable_submission(client, tenant_a, tenant_b, env_a):
    source, body, created, selection = proposal(client, tenant_a, env_a)
    with session_scope() as session:
        original_network = session.get(DesiredPolicy, source['id']).network
    cr = {'id': created['change_request_id']}
    before = deployment_counts()
    assert client.post('/api/v1/deployment-preview', headers=tenant_a, json=selection).status_code == 409
    own = review(client, tenant_a, cr)
    assert 'own_proposal' in own['approve_blockers']
    assert decide(client, tenant_a, cr, own).status_code == 409
    assert client.get(f"/api/v1/change-requests/{cr['id']}/review", headers=tenant_b).status_code == 404
    assert deployment_counts() == before

    reviewer = approver(tenant_a)
    snapshot = review(client, reviewer, cr)
    assert snapshot['can_approve'] is True
    assert decide(client, reviewer, cr, snapshot).status_code == 200
    before = deployment_counts()
    value = preview(client, tenant_a, selection)
    assert value['action'] == 'development_task'
    assert deployment_counts() == before
    submission = {**selection, 'schema_version': 'deployment-submission-create/v1',
                  'request_key': str(uuid.uuid4()), 'preview_digest': value['preview_digest']}
    response = client.post('/api/v1/deployment-submissions', headers=tenant_a, json=submission)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['state'] == 'recorded' and result['deployment_status'] == 'sent'
    saved = deployment_counts()
    assert saved[0] - before[0] == saved[1] - before[1] == 1
    replay = client.post('/api/v1/deployment-submissions', headers=tenant_a, json=submission)
    assert replay.status_code == 200 and replay.json() == result
    history = client.get(f"/api/v1/change-requests/{cr['id']}/execution", headers=tenant_a)
    assert history.status_code == 200, history.text
    assert history.json()['deployments'][0]['id'] == result['deployment_id']
    assert history.json()['deployments'][0]['status'] == 'sent'  # Not evidence of effective revocation.
    recovered = client.get(
        f"/api/v1/policies/{source['id']}/network-revoke-proposals/{body['request_key']}", headers=tenant_a)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()['change_request_id'] == cr['id']
    assert recovered.json()['change_status'] != 'effective'
    assert recovered.json()['lookup_executed'] is False
    assert deployment_counts() == saved
    with session_scope() as session:
        assert session.get(DesiredPolicy, source['id']).network == original_network
        assert session.get(DesiredPolicy, created['policy_id']).network == []
        events = list(session.scalars(select(AuditEvent).where(AuditEvent.resource_id == cr['id'])))
        assert {'change.request.create', 'change.approve'} <= {event.action for event in events}
        approval = next(event for event in events if event.action == 'change.approve')
        assert approval.summary['review_digest'] == snapshot['review_digest']


def test_approved_revoke_preview_cannot_execute_after_content_drift(client, tenant_a, env_a):
    _, _, created, selection = proposal(client, tenant_a, env_a)
    cr = {'id': created['change_request_id']}
    reviewer = approver(tenant_a)
    assert decide(client, reviewer, cr, review(client, reviewer, cr)).status_code == 200
    value = preview(client, tenant_a, selection)
    with session_scope() as session:
        session.get(DesiredPolicy, created['policy_id']).network = [
            {'endpoint': 'unexpected.example:443', 'effect': 'allow', 'binary_paths': ['/usr/bin/curl']}
        ]
        session.commit()
    before = deployment_counts()
    response = client.post('/api/v1/deployment-submissions', headers=tenant_a, json={
        **selection, 'schema_version': 'deployment-submission-create/v1',
        'request_key': str(uuid.uuid4()), 'preview_digest': value['preview_digest'],
    })
    assert response.status_code == 409, response.text
    assert deployment_counts() == before
