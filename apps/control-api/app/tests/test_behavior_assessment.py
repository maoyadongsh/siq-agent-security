"""Scoped current assessment: real API/database, controlled external readback."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select

from app.adapters.openshell import behavior_journal
from app.adapters.openshell.behavior_protocol import validate_accepted_behavior_result
from app.db import session_scope
from app.models import AuditEvent, Deployment, OpenShellBehaviorOperation, RuntimeBinding
from app.routers import deployment_behavior
from app.tests.test_deployment_behavior import behavior as behavior
from app.tests.test_deployment_behavior import collect


def assess(client, headers, rig):
    return client.post(f'/api/v1/deployments/{rig.dep}/behavior-assessment', headers=headers,
                       json={'schema_version': 'deployment-behavior-assess/v1',
                             'verification_id': rig.body['verification_id']})


def test_viewer_current_assessment_is_scoped_audited_and_never_replays(client, tenant_a, behavior):
    rig = behavior
    history = collect(client, tenant_a, rig).json()
    response = assess(client, {**tenant_a, 'X-Dev-Roles': 'viewer'}, rig)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['state'] == 'verified' and value['level'] == 'enforcement_verified'
    assert value['current_enforcement_verified'] and value['scope'] == history['scope']
    assert value['valid_until'] == history['expires_at'] and len(rig.calls) == 12
    assert response.headers['cache-control'] == 'no-store'
    schema = json.loads((Path(__file__).resolve().parents[4] /
        'packages/contracts/deployment-behavior-assessment.v1.schema.json').read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    with session_scope() as session:
        row = session.get(OpenShellBehaviorOperation, rig.body['verification_id'])
        assert row.state == 'accepted' and row.epoch == 2
        assert session.get(Deployment, rig.dep).verification['level'] == 'readback_verified'
        events = list(session.scalars(select(AuditEvent).where(
            AuditEvent.resource_id == rig.dep, AuditEvent.action == 'deployment.behavior_assess')))
        assert len(events) == 1 and events[0].summary['level'] == 'enforcement_verified'
    assert client.get(rig.url + '/' + rig.body['verification_id'], headers=tenant_a).json() == history


@pytest.mark.parametrize('fault', ['revision', 'policy', 'profile', 'binding', 'target_authority', 'audit'])
def test_current_changes_remove_positive_grade_without_changing_history(client, tenant_a, behavior, monkeypatch, fault):
    rig = behavior
    history = collect(client, tenant_a, rig).json()
    assert assess(client, tenant_a, rig).json()['state'] == 'verified'
    if fault == 'revision':
        rig.runner.revision += 1
    elif fault == 'policy':
        rig.runner.policy['network_policies'] = {}
    elif fault == 'profile':
        rig.path.write_text(rig.path.read_text() + '\n')
    elif fault == 'binding':
        with session_scope() as session:
            session.get(RuntimeBinding, rig.binding).status = 'revoked'
    elif fault == 'target_authority':
        rig.authority_path.unlink()
    else:
        original = behavior_journal.audit

        def fail(*args, **kwargs):
            if args[4] == 'deployment.behavior_assess':
                raise RuntimeError('synthetic audit failure')
            return original(*args, **kwargs)

        monkeypatch.setattr(behavior_journal, 'audit', fail)
    response = assess(client, tenant_a, rig)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['state'] in ('changed', 'unavailable') and value['level'] == 'unverified'
    assert value['current_enforcement_verified'] is False and value['valid_until'] is None
    assert len(rig.calls) == 12
    assert client.get(rig.url + '/' + rig.body['verification_id'], headers=tenant_a).json() == history
    if fault == 'audit':
        with session_scope() as session:
            events = list(session.scalars(select(AuditEvent.id).where(
                AuditEvent.resource_id == rig.dep, AuditEvent.action == 'deployment.behavior_assess')))
            assert len(events) == 1  # Failed second assessment did not commit an audit.


def test_expired_assessment_never_contacts_backend(client, tenant_a, behavior, monkeypatch):
    rig = behavior
    collect(client, tenant_a, rig)

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(days=1)

    monkeypatch.setattr(deployment_behavior, 'datetime', Future)
    monkeypatch.setattr(deployment_behavior, 'OpenShellCliBackend', lambda: pytest.fail('expired backend access'))
    value = assess(client, tenant_a, rig).json()
    assert value['state'] == 'expired' and value['level'] == 'unverified' and value['valid_until'] is None
    assert len(rig.calls) == 12


def test_assessment_tenant_and_object_permissions(client, tenant_a, tenant_b, behavior):
    rig = behavior
    assert assess(client, {**tenant_a, 'X-Dev-Roles': ''}, rig).status_code == 404
    collect(client, tenant_a, rig)
    assert assess(client, tenant_b, rig).status_code == 404
    assert assess(client, {**tenant_a, 'X-Dev-Roles': ''}, rig).status_code == 403
    assert len(rig.calls) == 12


def test_unknown_collection_cannot_be_promoted(client, tenant_a, behavior):
    rig = behavior

    def revoke():
        with session_scope() as session:
            session.get(RuntimeBinding, rig.binding).status = 'revoked'

    rig.hook = revoke
    assert collect(client, tenant_a, rig).json()['state'] == 'unknown'
    value = assess(client, tenant_a, rig).json()
    assert value['state'] == 'not_accepted' and value['level'] == 'unverified' and len(rig.calls) == 1


def test_accepted_validator_never_treats_running_as_historical_authority():
    assert validate_accepted_behavior_result({}, {}, {}, now=datetime.now(UTC), operation_state='running') == (
        False, 'behavior_operation_not_accepted')
    assert validate_accepted_behavior_result({}, {'schema_version': 'openshell-behavior-challenge/v1'}, {},
        now=datetime.now(UTC), operation_state='accepted') == (False, 'behavior_current_version_required')


def test_profile_preview_v2_digest_binding_and_history_replay(client, tenant_a, tenant_b, behavior):
    rig = behavior
    url = f'/api/v1/deployments/{rig.dep}/behavior-profiles'
    assert client.get(url, headers=tenant_b).status_code == 404
    response = client.get(url, headers=tenant_a)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog['deployment_id'] == rig.dep and len(catalog['profiles']) == 1
    profile = catalog['profiles'][0]
    rig.body = {**rig.body, 'schema_version': 'deployment-behavior-start/v2',
                'profile_sha256': profile['profile_sha256']}
    root = Path(__file__).resolve().parents[4] / 'packages/contracts'
    for name, value in [('deployment-behavior-start.v2', rig.body), ('deployment-behavior-profiles.v1', catalog)]:
        Draft202012Validator(json.loads((root / (name + '.schema.json')).read_text()),
                             format_checker=FormatChecker()).validate(value)
    old_bytes = rig.path.read_bytes()
    rig.path.write_bytes(old_bytes + b'\n')
    assert client.post(rig.url, headers=tenant_a, json=rig.body).status_code == 409
    assert not rig.calls
    rig.path.write_bytes(old_bytes)
    assert collect(client, tenant_a, rig).json()['state'] == 'accepted'
    assert client.post(rig.url, headers=tenant_a, json={**rig.body, 'profile_sha256': '0' * 64}).status_code == 409
    assert collect(client, tenant_a, rig).json()['state'] == 'accepted' and len(rig.calls) == 12
