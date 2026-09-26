"""Real HTTP/SQLite checks; fake execution backend, not runtime coverage evidence."""

import hashlib
import json

import pytest

from app.db import session_scope
from app.models import RuntimeBinding
from app.tests.test_deployment_preview import counts, preview, setup


def request(body, value):
    return {**body, "schema_version": "enterprise-deployment-impact-request/v1",
            "preview_digest": value["preview_digest"]}


def test_registered_identity_is_not_complete_shared_impact(client, tenant_a, env_a):
    body, _ = setup(client, tenant_a, env_a)
    value = preview(client, tenant_a, body)
    before = counts()
    result = client.post('/api/v1/deployment-preview/impact', headers=tenant_a, json=request(body, value))
    assert result.status_code == 200, result.text
    assert result.headers['cache-control'] == 'no-store'
    data = result.json()
    assert data['preview'] == value
    with session_scope() as session:
        binding = session.get(RuntimeBinding, body['binding_id'])
        assert data['registered_subject'] == {
            'binding_id': binding.id, 'environment_id': binding.environment_id,
            'asset_id': binding.asset_id, 'agent_instance_id': binding.agent_instance_id,
        }
    assert data['coverage'] == 'registered_binding_only'
    assert data['shared_runtime_occupants'] == 'unknown'
    assert data['skill_isolation'] == 'not_established'
    assert data['execution_confirmation_supported'] is False
    digest = data.pop('impact_digest')
    expected = hashlib.sha256(json.dumps({
        'tenant': tenant_a['X-Dev-Tenant-Id'], 'actor': tenant_a['X-Dev-User-Id'],
        'actor_type': 'user', 'report': data,
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert digest == expected
    repeated = client.post('/api/v1/deployment-preview/impact', headers=tenant_a, json=request(body, value))
    assert repeated.status_code == 200
    assert repeated.json()['impact_digest'] == digest
    assert counts() == before


def test_inventory_permission_denied_before_backend_probe(client, tenant_a, env_a, monkeypatch):
    from app import security
    from app.routers import deployment_impact

    body, _ = setup(client, tenant_a, env_a)
    value = preview(client, tenant_a, body)
    monkeypatch.setitem(security.ROLE_PERMISSIONS, 'impact_without_inventory',
                        {'policy:manage', 'policy:read', 'env:read'})

    def unexpected_probe(*args, **kwargs):
        raise AssertionError('backend must not be probed before inventory permission')

    monkeypatch.setattr(deployment_impact, '_prepare', unexpected_probe)
    result = client.post('/api/v1/deployment-preview/impact',
                         headers={**tenant_a, 'X-Dev-Roles': 'impact_without_inventory'},
                         json=request(body, value))
    assert result.status_code == 403


@pytest.mark.parametrize('case', ['tenant', 'viewer', 'digest', 'actor', 'extra'])
def test_rejected_reads_never_write(client, tenant_a, tenant_b, env_a, case):
    body, _ = setup(client, tenant_a, env_a)
    value = preview(client, tenant_a, body)
    payload = request(body, value)
    headers = tenant_a
    expected = 409
    if case == 'tenant':
        headers, expected = tenant_b, 404
    elif case == 'viewer':
        headers, expected = {**tenant_a, 'X-Dev-Roles': 'viewer'}, 403
    elif case == 'digest':
        payload['preview_digest'] = '0' * 64
    elif case == 'actor':
        headers = {**tenant_a, 'X-Dev-User-Id': 'different-actor'}
    else:
        payload['tenant_id'], expected = 'injected', 422
    before = counts()
    result = client.post('/api/v1/deployment-preview/impact', headers=headers, json=payload)
    assert result.status_code == expected, result.text
    assert counts() == before
