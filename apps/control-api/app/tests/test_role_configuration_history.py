import copy
import json
import uuid

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.evidence_signing import evidence_signed_bytes
from app.models import AgentAsset, EdgeTask, RoleConfigurationObservation
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


@pytest.fixture
def config_history(client, tenant_a):
    tenant = {**tenant_a, 'X-Dev-Tenant-Id': 'history-' + uuid.uuid4().hex}
    identity = 'history-' + uuid.uuid4().hex
    env = client.post('/api/v1/environments', headers=tenant, json={'name': identity}).json()['id']
    headers, key = register_edge(client, tenant, env, identity)

    def prepare(hash_char='b', roots=True, legacy=False):
        task_id = create_scan_task(client, tenant, env, 'openclaw')
        role_id = 'openclaw:v2:' + 'a' * 64
        evidence = signed_evidence(key, identity, 'ev-' + hash_char, source_type='openclaw_config',
                                   content_hash=hash_char * 64)
        evidence['subject_ref'] = role_id
        evidence['signature'] = key.sign(evidence_signed_bytes(evidence)).hex()
        role = candidate('history-role', [evidence['evidence_id']], source_type='openclaw_agent')
        role.update(candidate_id=role_id, framework='openclaw', source_locator='openclaw://agents/v2/' + 'a' * 64)
        role['attributes'] = {} if legacy else {'framework_source': json.dumps({
            'schema_version': 'enterprise-framework-source/v1', 'framework': 'openclaw',
            'instance_key': 'a' * 64, 'config_sha256': hash_char * 64, 'evidence_id': evidence['evidence_id']})}
        if roots and not legacy:
            role['attributes']['skill_source_roots'] = json.dumps({
                'schema_version': 'enterprise-role-skill-roots/v1', 'status': 'declared', 'basis': 'agent_workspace',
                'roots': [{'kind': 'workspace_skills', 'locator_sha256': 'e' * 64},
                          {'kind': 'project_agent_skills', 'locator_sha256': 'f' * 64}]})
        return task_id, role, evidence

    def upload(prepared, duplicate=False):
        task, role, evidence = prepared
        roles = [role, copy.deepcopy(role)] if duplicate else [role]
        if duplicate == 'location':
            roles[1]['candidate_id'] = 'legacy-other'
            roles[1]['attributes'] = {}
        return client.post('/edge/v1/batches', headers=headers,
                           json=signed_batch(key, task, candidates=roles, evidence=[evidence]))

    return tenant, prepare, upload


def test_config_history_preserves_versions_and_absence(config_history):
    tenant, prepare, upload = config_history
    first = prepare()
    assert upload(first).status_code == 200
    assert upload(first).json()['idempotent']
    with session_scope() as session:
        original = session.scalar(select(RoleConfigurationObservation).where(
            RoleConfigurationObservation.task_id == first[0]))
        original_id, asset_id = original.id, original.asset_id
        before = (copy.deepcopy(original.framework_source), copy.deepcopy(original.skill_source_roots),
                  original.observed_at)
    for prepared in (prepare('c'), prepare('d', roots=False), prepare('d', legacy=True)):
        assert upload(prepared).status_code == 200
    with session_scope() as session:
        rows = list(session.scalars(select(RoleConfigurationObservation).where(
            RoleConfigurationObservation.tenant_id == tenant['X-Dev-Tenant-Id'])))
        assert len(rows) == 3 and {row.asset_id for row in rows} == {asset_id}
        assert {row.framework_source['config_sha256'] for row in rows} == {char * 64 for char in 'bcd'}
        assert next(row for row in rows if row.framework_source['config_sha256'] == 'd' * 64).skill_source_roots is None
        original = session.get(RoleConfigurationObservation, original_id)
        assert (original.framework_source, original.skill_source_roots, original.observed_at) == before
        assert json.loads(session.get(AgentAsset, asset_id).attributes['framework_source'])['config_sha256'] == 'd' * 64


@pytest.mark.parametrize('duplicate,detail', [(True, 'duplicate_candidate_id'),
                                            ('location', 'framework_source_duplicate_asset')])
def test_config_duplicate_asset_rejected_before_history(config_history, duplicate, detail):
    _, prepare, upload = config_history
    prepared = prepare()
    result = upload(prepared, duplicate=duplicate)
    assert result.status_code == 422 and result.json()['detail'] == detail
    with session_scope() as session:
        assert session.scalar(select(RoleConfigurationObservation).where(
            RoleConfigurationObservation.task_id == prepared[0])) is None
        assert session.get(EdgeTask, prepared[0]).status == 'pending'


def test_config_history_rolls_back_with_audit_failure(config_history, monkeypatch):
    from app.routers import inventory

    tenant, prepare, upload = config_history
    prepared = prepare()

    def fail(*args, **kwargs):
        raise RuntimeError('synthetic audit failure')

    monkeypatch.setattr(inventory, 'audit', fail)
    with pytest.raises(RuntimeError, match='synthetic audit failure'):
        upload(prepared)
    with session_scope() as session:
        assert session.scalar(select(RoleConfigurationObservation).where(
            RoleConfigurationObservation.task_id == prepared[0])) is None
        assert session.scalar(select(AgentAsset).where(AgentAsset.tenant_id == tenant['X-Dev-Tenant-Id'])) is None
        assert session.get(EdgeTask, prepared[0]).status == 'pending'
