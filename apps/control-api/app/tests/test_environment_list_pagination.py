"""Environment list paging uses the existing array + list-header protocol."""

import uuid

from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, Environment, OutboxEvent, Tenant


def test_environment_list_paging_and_legacy(client, tenant_a):
    tenant = tenant_a['X-Dev-Tenant-Id']
    prefix = uuid.uuid4().hex
    with session_scope() as session:
        session.add_all(Environment(tenant_id=tenant, name=f'{prefix}-{i:03}') for i in range(51))
        session.commit()
        before = [session.scalar(select(func.count()).select_from(model)) for model in (AuditEvent, OutboxEvent)]
    legacy = client.get('/api/v1/environments', headers=tenant_a)
    assert legacy.status_code == 200
    expected = [row['id'] for row in legacy.json()]
    assert len(expected) >= 51
    seen, cursor = [], None
    while True:
        params = {'limit': 50, 'include_total': 'true'}
        if cursor:
            params['cursor'] = cursor
        response = client.get('/api/v1/environments', headers=tenant_a, params=params)
        assert response.status_code == 200
        assert len(response.json()) <= 50
        assert int(response.headers['x-siq-list-total']) == len(expected)
        assert int(response.headers['x-siq-list-returned']) == len(response.json())
        assert response.headers['cache-control'] == 'no-store'
        seen.extend(row['id'] for row in response.json())
        if response.headers['x-siq-list-truncated'] == '0':
            assert 'x-siq-next-cursor' not in response.headers
            break
        next_cursor = response.headers['x-siq-next-cursor']
        assert next_cursor == seen[-1] and next_cursor != cursor
        cursor = next_cursor
    assert seen == expected
    assert len(seen) == len(set(seen))
    with session_scope() as session:
        after = [session.scalar(select(func.count()).select_from(model)) for model in (AuditEvent, OutboxEvent)]
        assert after == before


def test_environment_list_cursor_is_tenant_scoped(client, tenant_a, tenant_b, env_b):
    response = client.get('/api/v1/environments', headers=tenant_a, params={'limit': 1, 'cursor': env_b['id']})
    assert response.status_code == 422
    assert response.json()['detail'] == 'environment_list_cursor_unavailable'
    assert env_b['name'] not in response.text
    unknown = client.get('/api/v1/environments', headers=tenant_a, params={'limit': 1, 'cursor': 'missing'})
    assert unknown.status_code == response.status_code and unknown.json() == response.json()
    denied = client.get('/api/v1/environments', headers={**tenant_a, 'X-Dev-Roles': 'viewer'}, params={'limit': 1})
    assert denied.status_code == 403


def test_environment_list_invalid_paging(client, tenant_a):
    for params in ({'limit': 0}, {'limit': 201}, {'limit': 1, 'cursor': ''}, {'cursor': 'missing'}):
        assert client.get('/api/v1/environments', headers=tenant_a, params=params).status_code == 422


def test_environment_list_empty_total(client, tenant_a):
    tenant = 'env-list-' + uuid.uuid4().hex
    with session_scope() as session:
        session.add(Tenant(id=tenant, name='synthetic empty list'))
        session.commit()
    response = client.get('/api/v1/environments', headers={**tenant_a, 'X-Dev-Tenant-Id': tenant},
                          params={'limit': 50, 'include_total': 'true'})
    assert response.status_code == 200 and response.json() == []
    assert response.headers['x-siq-list-total'] == '0'
    assert response.headers['x-siq-list-truncated'] == '0'
    assert 'x-siq-next-cursor' not in response.headers
