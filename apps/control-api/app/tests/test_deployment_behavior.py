"""Authenticated API and durable storage; external CLI/probe effects are fixtures."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select

from app.adapters.openshell.behavior_coordinator import BehaviorCoordinator
from app.adapters.openshell.behavior_profiles import BehaviorProfile
from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, OpenShellBehaviorOperation, RuntimeBinding, Tenant
from app.routers import deployment_behavior, policies
from app.tests.binding_helpers import assign_target_authority, make_binding
from app.tests.test_change_review import approver, change
from app.tests.test_deployment_preview import preview
from app.tests.test_oidc_jwt_verify import oidc_env as oidc_env
from app.tests.test_online_openshell_recovery import deployed
from app.tests.test_openshell_policy_operations import StatefulRunner

ROOT = Path(__file__).resolve().parents[4]


def events_for(session, verification_id):
    return list(session.scalars(select(AuditEvent).where(
        AuditEvent.summary["verification_id"].as_string() == verification_id).order_by(AuditEvent.created_at)))


def stamp(value=None):
    return (value or datetime.now(UTC)).isoformat().replace('+00:00', 'Z')


@pytest.fixture
def behavior(client, tenant_a, env_a, monkeypatch, tmp_path):
    monkeypatch.setenv('SIQ_AS_ENFORCEMENT_BACKEND', 'openshell-cli')
    with session_scope() as session:
        if session.get(Tenant, tenant_a['X-Dev-Tenant-Id']) is None:
            session.add(Tenant(id=tenant_a['X-Dev-Tenant-Id'], name='Synthetic API tenant'))
    runner = StatefulRunner()

    def run(args):
        if args[:2] == ['policy', 'get']:
            args = [*args[:2], 's1', *args[3:]]
        return runner(args)

    def factory():
        return OpenShellCliBackend(runner=run, env_script='')
    monkeypatch.setattr(policies, 'OpenShellCliBackend', factory)
    monkeypatch.setattr(deployment_behavior, 'OpenShellCliBackend', factory)
    binding, asset, _ = make_binding(client, tenant_a, env_a['id'], backend='openshell-cli')
    cr, _ = change(client, tenant_a, agent_ids=[asset], enforcement_mode='block', network=[
        {'endpoint': '127.0.0.1:19090', 'effect': 'allow', 'binary_paths': ['/opt/probe/allow']}])
    approval = client.post(f"/api/v1/change-requests/{cr['id']}/approve", headers=approver(tenant_a), json={})
    assert approval.status_code == 200
    authority_path = assign_target_authority(monkeypatch, tmp_path, binding['id'], factory())
    body = {'schema_version': 'deployment-preview-request/v1', 'change_request_id': cr['id'],
            'environment_id': env_a['id'], 'binding_id': binding['id']}
    value = preview(client, tenant_a, body)
    dep = deployed(client, tenant_a, {**body, 'schema_version': 'deployment-submission-create/v1',
                   'request_key': str(uuid.uuid4()), 'preview_digest': value['preview_digest']})
    with session_scope() as session:
        receipt = dict(session.get(Deployment, dep).receipt)
    now = datetime.now(UTC)
    profile = BehaviorProfile.model_validate({
        'profile_id': 'api-test', 'binding': {
            'tenant_id': tenant_a['X-Dev-Tenant-Id'], 'environment_id': env_a['id'], 'binding_id': binding['id'],
            'deployment_id': dep, 'operation_id': receipt['operation_id'], 'target': binding['backend_target_id'],
            'gateway_fingerprint': receipt['endpoint_fingerprint'], 'policy_revision': receipt['backend_revision'],
            'policy_digest': receipt['applied_policy_digest'], 'image_digest': 'sha256:' + 'a' * 64,
            'probe_sha256': 'b' * 64, 'protected_execution_sha256': 'c' * 64},
        'gateway_name_sha256': receipt['gateway_name_sha256'],
        'transport': {'mode': 'http_connect', 'proxy_ipv4': '10.200.0.1', 'proxy_port': 3128},
        'protection': {'container_id': 'd' * 64, 'image_digest': 'sha256:' + 'a' * 64, 'namespace': 'api-test',
            'sandbox_name': binding['backend_target_id'], 'sandbox_id': 'api-test', 'uid': 998,
            'allow_path': '/opt/probe/allow', 'deny_path': '/opt/probe/deny', 'probe_sha256': 'b' * 64,
            'supervisor_profile': 'openshell-rootful-v0'},
        'receiver_ipv4': '127.0.0.1', 'receiver_port': 19090, 'allow_path': '/opt/probe/allow',
        'deny_path': '/opt/probe/deny', 'attempts': 3, 'timeout_ms': 1000,
        'issued_at': stamp(now - timedelta(minutes=1)), 'expires_at': stamp(now + timedelta(minutes=4))})
    path = tmp_path / 'profiles.json'
    path.write_text(json.dumps({'schema_version': 'openshell-behavior-profiles/v1',
                               'profiles': [profile.model_dump()]}))
    path.chmod(0o600)
    monkeypatch.setenv('SIQ_AS_OPENSHELL_BEHAVIOR_PROFILES_FILE', str(path))
    rig = SimpleNamespace(profile=profile, path=path, authority_path=authority_path, calls=[], hook=None,
                          dep=dep, binding=binding['id'], change=cr['id'], runner=runner,
                          url=f'/api/v1/deployments/{dep}/behavior-verifications',
                          body={'schema_version': 'deployment-behavior-start/v1',
                                'profile_id': profile.profile_id, 'verification_id': 'opv-' + uuid.uuid4().hex})

    class Guard:
        def __init__(self, target):
            assert target == profile.protection.target()

        def verify(self):
            return {'protected_execution_sha256': profile.binding.protected_execution_sha256}

    class Channel:
        def __init__(self, *args, **kwargs):
            pass

        def run_arm(self, challenge, *, round_index, kind, expected_uid):
            assert expected_uid == 998
            return self.control(challenge, round_index=round_index, kind=kind)

        def control(self, challenge, *, round_index, kind):
            with session_scope() as session:
                row = session.get(OpenShellBehaviorOperation, challenge.verification_id)
                assert row.state == 'running'
                events = events_for(session, row.id)
                assert len(events) == 2  # Durable claim and audit precede any external effect.
            rig.calls.append(kind)
            inside, denied = kind in ('allow', 'deny'), kind == 'deny'
            observation = {'round': round_index, 'kind': kind, 'nonce': challenge.nonce,
                'origin': 'sandbox_exec' if inside else 'control_plane_host', 'endpoint': '127.0.0.1:19090',
                'program_path': (profile.allow_path if kind == 'allow' else profile.deny_path) if inside else '',
                'program_sha256': profile.binding.probe_sha256 if inside else '',
                'transport': 'http_connect' if inside else 'direct_tcp',
                'proxy_endpoint': '10.200.0.1:3128' if inside else '',
                'proxy_status': 403 if denied else 200 if inside else 0,
                'proxy_error': 'policy_denied' if denied else '',
                'outcome': 'proxy_denied' if denied else 'connected', 'elapsed_ms': 1, 'observed_at': stamp()}
            if rig.hook:
                rig.hook()
            return observation

    def coordinator(*args, **kwargs):
        return BehaviorCoordinator(*args, **kwargs, guard_factory=Guard, channel_factory=Channel)

    monkeypatch.setattr(deployment_behavior, 'BehaviorCoordinator', coordinator)
    return rig


def collect(client, tenant_a, rig):
    response = client.post(rig.url, headers=tenant_a, json=rig.body)
    assert response.status_code == 200, response.text
    return response


def test_api_collection_contract_audit_and_readonly_replay(client, tenant_a, behavior, monkeypatch):
    rig = behavior
    response = collect(client, tenant_a, rig)
    result = response.json()
    assert result['state'] == 'accepted' and result['observation_count'] == 12
    assert result['current_enforcement_verified'] is False and len(rig.calls) == 12
    for name, data in [('deployment-behavior-start', rig.body), ('deployment-behavior-operation', result)]:
        schema = json.loads((ROOT / f'packages/contracts/{name}.v1.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
    with session_scope() as session:
        row = session.get(OpenShellBehaviorOperation, rig.body['verification_id'])
        assert row.profile_id == rig.profile.profile_id
        assert row.profile_sha256 == hashlib.sha256(rig.path.read_bytes()).hexdigest()
        events = events_for(session, row.id)
        assert len(events) == 3
        assert all(event.summary['profile_sha256'] == row.profile_sha256 for event in events)
        assert session.get(Deployment, rig.dep).verification['level'] == 'readback_verified'
        assert row.challenge['nonce'] not in response.text and row.owner_sha256 not in response.text
    rig.path.unlink()
    rig.authority_path.unlink()
    monkeypatch.delenv('SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE')
    monkeypatch.setenv('SIQ_AS_ENFORCEMENT_BACKEND', 'none')
    monkeypatch.setattr(deployment_behavior, 'OpenShellCliBackend', lambda: pytest.fail('history touched backend'))
    viewer = {**tenant_a, 'X-Dev-Roles': 'viewer'}
    for reply in [client.get(rig.url, headers=viewer),
                  client.get(rig.url + '/' + rig.body['verification_id'], headers=viewer),
                  client.post(rig.url, headers=tenant_a, json=rig.body)]:
        assert reply.status_code == 200 and reply.headers['cache-control'] == 'no-store', reply.text
        assert reply.json() in (result, [result])
    assert len(rig.calls) == 12
    assert client.post(rig.url, headers=tenant_a, json={**rig.body, 'profile_id': 'different'}).status_code == 409


def test_api_object_isolation_permissions_and_request_injection(client, tenant_a, tenant_b, behavior):
    rig = behavior
    viewer = {**tenant_a, 'X-Dev-Roles': 'viewer'}
    nobody = {**tenant_a, 'X-Dev-Roles': ''}
    assert client.post(rig.url, headers=tenant_b, json=rig.body).status_code == 404
    assert client.get(rig.url, headers=tenant_b).status_code == 404
    assert client.post(rig.url, headers=viewer, json=rig.body).status_code == 403
    assert client.get(rig.url + '/' + rig.body['verification_id'], headers=nobody).status_code == 404
    for field in ['tenant_id', 'receiver_ipv4', 'nonce', 'result', 'target', 'allow_path']:
        assert client.post(rig.url, headers=tenant_a, json={**rig.body, field: 'injected'}).status_code == 422
    assert not rig.calls
    collect(client, tenant_a, rig)
    for method in ('get', 'post'):
        args = {'json': rig.body} if method == 'post' else {}
        assert getattr(client, method)(rig.url, headers=nobody, **args).status_code == 403
    assert client.get(rig.url + '/' + rig.body['verification_id'], headers=tenant_b).status_code == 404
    assert client.get(rig.url + '/' + rig.body['verification_id'], headers=nobody).status_code == 403
    assert client.get(rig.url + '?limit=101', headers=tenant_a).status_code == 422


@pytest.mark.parametrize('fault', ['binding', 'approval', 'receipt', 'authority', 'expired_profile'])
def test_api_changed_authority_prevents_probe_and_record(client, tenant_a, behavior, fault):
    rig = behavior
    with session_scope() as session:
        if fault == 'binding':
            session.get(RuntimeBinding, rig.binding).status = 'revoked'
        elif fault == 'approval':
            session.get(ChangeRequest, rig.change).approved_at = None
        elif fault == 'receipt':
            row = session.get(Deployment, rig.dep)
            row.receipt = {**row.receipt, 'operation_id': 'opo-forged'}
    if fault == 'authority':
        rig.authority_path.unlink()
    if fault == 'expired_profile':
        content = json.loads(rig.path.read_text())
        content['profiles'][0]['expires_at'] = stamp(datetime.now(UTC) - timedelta(seconds=1))
        rig.path.write_text(json.dumps(content))
    response = client.post(rig.url, headers=tenant_a, json=rig.body)
    assert response.status_code == 409, response.text
    assert not rig.calls
    with session_scope() as session:
        assert session.get(OpenShellBehaviorOperation, rig.body['verification_id']) is None


def test_api_revocation_during_collection_stops_and_audits_unknown(client, tenant_a, behavior):
    rig = behavior

    def revoke():
        with session_scope() as session:
            session.get(RuntimeBinding, rig.binding).status = 'revoked'

    rig.hook = revoke
    response = collect(client, tenant_a, rig)
    assert response.json()['state'] == 'unknown' and response.json()['observed_at'] is None
    assert len(rig.calls) == 1
    with session_scope() as session:
        events = events_for(session, rig.body['verification_id'])
        assert len(events) == 3 and events[-1].action == 'openshell.behavior.unknown'
    assert collect(client, tenant_a, rig).json() == response.json() and len(rig.calls) == 1


def test_api_production_rs256_identity_and_key_removal(client, tenant_a, behavior, oidc_env):
    rig = behavior
    token = oidc_env['mint'](tenant_id=tenant_a['X-Dev-Tenant-Id'], role_codes=['security_admin'])
    headers = {'Authorization': 'Bearer ' + token, 'X-Dev-Tenant-Id': 'injected-tenant'}
    assert client.post(rig.url, headers=tenant_a, json=rig.body).status_code == 401
    assert client.post(rig.url, json=rig.body).status_code == 401
    denied = oidc_env['mint'](tenant_id=tenant_a['X-Dev-Tenant-Id'], role_codes=['viewer'])
    assert client.post(rig.url, headers={'Authorization': 'Bearer ' + denied}, json=rig.body).status_code == 403

    def remove_key():
        oidc_env['keys']['current'] = []
        oidc_env['clock']['t'] += 61

    rig.hook = remove_key
    response = collect(client, headers, rig)
    assert response.json()['state'] == 'unknown' and len(rig.calls) == 1
    assert client.get(rig.url, headers=headers).status_code == 401


def test_api_production_rs256_success(client, tenant_a, behavior, oidc_env):
    rig = behavior
    token = oidc_env['mint'](tenant_id=tenant_a['X-Dev-Tenant-Id'], role_codes=['security_admin'])
    response = collect(client, {'Authorization': 'Bearer ' + token}, rig)
    assert response.json()['state'] == 'accepted' and len(rig.calls) == 12
    with session_scope() as session:
        events = events_for(session, rig.body['verification_id'])
        assert len(events) == 3 and all(event.actor_id == 'user-1' for event in events)


def test_token_expiry_at_final_transaction_cannot_accept(client, tenant_a, behavior, monkeypatch):
    from app.behavior_authority import BehaviorAuthority

    original = BehaviorAuthority.before_accept

    def expired(self, session, profile):
        self.deadline = datetime.now(UTC) - timedelta(seconds=1)
        original(self, session, profile)

    monkeypatch.setattr(BehaviorAuthority, 'before_accept', expired)
    response = collect(client, tenant_a, behavior)
    assert response.json()['state'] == 'unknown' and len(behavior.calls) == 12
    with session_scope() as session:
        row = session.get(OpenShellBehaviorOperation, behavior.body['verification_id'])
        assert row.result is None
        events = events_for(session, row.id)
        assert len(events) == 3 and all(event.action != 'openshell.behavior.accepted' for event in events)


def test_acceptance_audit_failure_rolls_back_result(client, tenant_a, behavior, monkeypatch):
    from app.adapters.openshell import behavior_journal

    original = behavior_journal.audit

    def fail_acceptance(*args, **kwargs):
        if args[4] == 'openshell.behavior.accepted':
            raise RuntimeError('synthetic database audit failure')
        return original(*args, **kwargs)

    monkeypatch.setattr(behavior_journal, 'audit', fail_acceptance)
    response = collect(client, tenant_a, behavior)
    assert response.json()['state'] == 'unknown' and len(behavior.calls) == 12
    with session_scope() as session:
        row = session.get(OpenShellBehaviorOperation, behavior.body['verification_id'])
        assert row.result is None and row.result_digest is None
        events = events_for(session, row.id)
        assert len(events) == 3 and all(event.action != 'openshell.behavior.accepted' for event in events)


def test_history_expiry_and_bounded_list_never_claim_current_enforcement(client, tenant_a, behavior, monkeypatch):
    rig = behavior
    collect(client, tenant_a, rig)
    rig.body = {**rig.body, 'verification_id': 'opv-' + uuid.uuid4().hex}
    collect(client, tenant_a, rig)

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(days=1)

    monkeypatch.setattr(deployment_behavior, 'datetime', Future)
    reply = client.get(rig.url + '?limit=1', headers=tenant_a)
    assert reply.status_code == 200 and len(reply.json()) == 1
    assert reply.headers['X-SIQ-List-Truncated'] == '1'
    assert reply.json()[0]['state'] == 'accepted' and reply.json()[0]['time_window'] == 'expired'
    assert reply.json()[0]['current_enforcement_verified'] is False and len(rig.calls) == 24
