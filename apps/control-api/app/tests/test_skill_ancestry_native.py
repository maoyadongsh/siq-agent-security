"""Actual Directory NDJSON -> Edge signature -> isolated API and source readback.

Not installed-service, real IAM/TLS, production database, or runtime acceptance.
"""
import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.evidence_signing import evidence_signed_bytes
from app.models import (
    AgentAsset,
    AuditEvent,
    EdgeAgent,
    EdgeTask,
    OutboxEvent,
    PermissionFact,
    RoleConfigurationObservation,
    SkillManifestObservation,
    SkillUploadReceipt,
)
from app.signing import sign_task_payload
from app.tests.edge_helpers import edge_private_key, signed_batch
from app.tests.test_skill_upload import upload_case as upload_case


@pytest.fixture(scope='module')
def native_directory(tmp_path_factory):
    assert shutil.which('go'), 'native ancestry verification requires Go'
    root = Path(__file__).resolve().parents[4]
    directory = tmp_path_factory.mktemp('skill-ancestry-native-build')
    binary = directory / 'directory-connector'
    result = subprocess.run(['go', 'build', '-o', str(binary), '.'], cwd=root / 'connectors/directory',
                            capture_output=True, timeout=120)
    assert result.returncode == 0, 'native directory build failed'
    openclaw = directory / 'openclaw-connector'
    result = subprocess.run(['go', 'build', '-o', str(openclaw), '.'], cwd=root / 'connectors/openclaw',
                            capture_output=True, timeout=120)
    assert result.returncode == 0, 'native OpenClaw build failed'
    return root, binary, openclaw


def test_native_skill_ancestry_signed_upload_and_match(client, tenant_a, upload_case, native_directory, tmp_path):
    _, upload, task_id, edge_id, identity, environment_id = upload_case
    root, binary, openclaw = native_directory
    workspace = tmp_path / 'workspace'
    skill_root = workspace / 'skills'
    manifests = {}
    for name in ('group/one', 'two'):
        location = skill_root / name
        location.mkdir(parents=True)
        data = b'---\nname: same-name\nallowed-tools: [read_file]\n---\n'
        (location / 'SKILL.md').write_bytes(data)
        (location / '.env').write_text('SYNTHETIC_SECRET_DO_NOT_COLLECT=fixture\n')
        manifests[str(location)] = hashlib.sha256(data).hexdigest()
    scope = {'roots': [str(skill_root)], 'include': ['SKILL.md']}
    with session_scope() as session:
        task = session.get(EdgeTask, task_id)
        task.payload = {**task.payload, 'scope': scope}
        task.signature = sign_task_payload(task.id, task.task_type, environment_id,
                                           task.payload, task.expires_at.isoformat())
    input_file, output_file = tmp_path / 'input.json', tmp_path / 'signed.json'
    input_file.write_text(json.dumps({'connector': str(binary), 'identity': identity,
                                     'task_id': task_id, 'scope': scope}))
    env = {**os.environ, 'SIQ_SKILL_ANCESTRY_INPUT': str(input_file), 'SIQ_SKILL_ANCESTRY_OUTPUT': str(output_file)}
    run = subprocess.run(['go', 'test', '.', '-run', '^TestSkillAncestryNativeExport$', '-count=1'],
                         cwd=root / 'edge/agent', env=env, capture_output=True, timeout=120)
    assert run.returncode == 0, 'native collection/signature export failed'
    wire = json.loads(output_file.read_text())
    assert set(wire) == {'body', 'digest', 'public_key_pem'}
    assert wire['body']['schema_version'] == 'enterprise-skill-upload/v2'
    assert len(wire['body']['observations']) == 2
    for observation in wire['body']['observations']:
        location = next(path for path in manifests if hashlib.sha256(path.encode()).hexdigest()
                        == observation['locator_sha256'])
        expected = []
        parent = Path(location)
        while True:
            expected.append(hashlib.sha256(str(parent).encode()).hexdigest())
            if parent == skill_root:
                break
            parent = parent.parent
        assert observation['ancestor_sha256'] == expected
        assert observation['manifest_sha256'] == manifests[location]
    assert 'SYNTHETIC_SECRET' not in output_file.read_text()
    assert str(workspace) not in output_file.read_text()
    with session_scope() as session:
        assert wire['public_key_pem'] == session.get(EdgeAgent, edge_id).public_key_pem
    tampered = copy.deepcopy(wire['body'])
    tampered['observations'][0]['ancestor_sha256'] = [tampered['observations'][0]['locator_sha256']]
    assert upload(tampered, resign=False).status_code == 401
    response = upload(wire['body'], resign=False)
    assert response.status_code == 200 and response.json()['batch_digest'] == wire['digest']
    assert upload(wire['body'], resign=False).json()['idempotent']
    config_root = tmp_path / 'openclaw'
    config_root.mkdir()
    config = json.dumps({'agents': {'entries': {'main': {'name': 'native-fixture-role',
                                                       'workspace': str(workspace), 'skills': ['same-name']}}}})
    (config_root / 'openclaw.json').write_text(config)
    request = {'id': 'fixture', 'op': 'collect', 'params': {'plan': {
        'scope': {'roots': [str(config_root)], 'include': ['openclaw.json']},
        'limits': {'max_files': 200, 'max_bytes': 1048576}}}}
    collected = subprocess.run([str(openclaw), '--serve'], input=json.dumps(request) + '\n',
                               text=True, capture_output=True, timeout=20)
    assert collected.returncode == 0
    config_result = json.loads(collected.stdout)
    assert config_result['ok']
    config_batch = config_result['result']
    assert not config_batch.get('truncated') and len(config_batch['candidates']) == 1
    config_task = client.post('/api/v1/scans', headers=tenant_a, json={
        'environment_id': environment_id, 'connector': 'openclaw', 'scope': request['params']['plan']['scope']})
    assert config_task.status_code == 200
    key = edge_private_key(identity)
    for evidence in config_batch['evidence']:
        evidence['collector_id'] = identity
        evidence['signing_schema'] = 'evidence_utf8/v1'
        evidence['signature'] = key.sign(evidence_signed_bytes(evidence)).hex()
    role_body = signed_batch(key, config_task.json()['task_id'], candidates=config_batch['candidates'],
                             evidence=config_batch['evidence'], permission_facts=config_batch.get('permission_facts'))
    role_response = client.post('/edge/v1/batches', json=role_body, headers={
        name: response.request.headers[name] for name in ('Authorization', 'X-Edge-Identity')})
    assert role_response.status_code == 200, role_response.text
    with session_scope() as session:
        receipt = session.get(SkillUploadReceipt, task_id)
        assert json.loads(receipt.signed_payload)['observations'] == wire['body']['observations']
        asset = session.scalar(select(AgentAsset).where(AgentAsset.discovery_scope == edge_id))
        assert asset is not None and asset.status == 'candidate'
        asset_id = asset.id
        facts = list(session.scalars(select(PermissionFact).where(PermissionFact.subject_id == asset_id)))
        assert len(facts) == 1 and facts[0].state == 'declared'
        snapshot_id = session.scalar(select(RoleConfigurationObservation.id).where(
            RoleConfigurationObservation.asset_id == asset_id))
        assert snapshot_id is not None
        before = [session.scalar(select(func.count()).select_from(model))
                  for model in (AuditEvent, OutboxEvent, PermissionFact, SkillManifestObservation)]
    value = client.get(f'/api/v1/agents/{asset_id}/skill-installation-sources', headers=tenant_a).json()
    assert len(value['items']) == 2
    assert all(item['relationship_status'] == 'historical_source_match' for item in value['items'])
    assert len({item['installation_id'] for item in value['items']}) == 2
    assert {item['observation']['batch_digest'] for item in value['items']} == {wire['digest']}
    assert value['effective_permissions'] is None and value['runtime_status'] == 'unverified'
    assert value['framework_source']['source']['config_sha256'] == hashlib.sha256(config.encode()).hexdigest()
    snapshot = client.get(
        f'/api/v1/agents/{asset_id}/configuration-observations/{snapshot_id}/skill-installation-sources',
        headers=tenant_a,
    )
    assert snapshot.status_code == 200
    assert snapshot.json()['items'] == value['items']
    assert snapshot.json()['configuration_observation']['configuration']['framework_source']['config_sha256'] == \
        hashlib.sha256(config.encode()).hexdigest()
    with session_scope() as session:
        assert before == [session.scalar(select(func.count()).select_from(model))
                          for model in (AuditEvent, OutboxEvent, PermissionFact, SkillManifestObservation)]
    second = subprocess.run(['go', 'test', '.', '-run', '^TestSkillAncestryNativeExport$', '-count=1'],
                            cwd=root / 'edge/agent', env=env, capture_output=True, timeout=120)
    assert second.returncode != 0, 'native export overwrote prior signed evidence'
    assert json.loads(output_file.read_text()) == wire
