from app.db import session_scope
from app.models import DesiredPolicy
from app.tests.test_network_revoke_proposals import counts, post, setup


def test_options_bound_to_same_baseline_and_can_propose(client, tenant_a):
    policy, body = setup(client, tenant_a)
    before = counts()
    response = client.get(f"/api/v1/policies/{policy['id']}/network-revoke-options", headers=tenant_a)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['baseline_digest'] == body['baseline_digest']
    assert data['selections'] == body['selections']
    assert data['coverage'] == 'complete_policy_network'
    assert response.headers['cache-control'] == 'no-store'
    assert counts() == before
    assert post(client, tenant_a, policy, {**body, 'selections': data['selections']}).status_code == 201


def test_options_tenant_and_permission_denial(client, tenant_a, tenant_b):
    policy, _ = setup(client, tenant_a)
    url = f"/api/v1/policies/{policy['id']}/network-revoke-options"
    assert client.get(url, headers=tenant_b).status_code == 404
    assert client.get(url, headers={**tenant_a, 'X-Dev-Roles': 'viewer'}).status_code == 403


def test_unknown_network_is_not_empty_success(client, tenant_a):
    policy, _ = setup(client, tenant_a)
    with session_scope() as session:
        source = session.get(DesiredPolicy, policy['id'])
        source.network = None
        session.commit()
    response = client.get(f"/api/v1/policies/{policy['id']}/network-revoke-options", headers=tenant_a)
    assert response.status_code == 422
    assert response.json()['detail'] == 'network_revoke_baseline_unsupported'


def test_incomplete_display_refuses_all_options(client, tenant_a, monkeypatch):
    from types import SimpleNamespace

    from app.routers import network_revoke_proposals
    policy, _ = setup(client, tenant_a)
    monkeypatch.setattr(network_revoke_proposals, '_section',
                        lambda *args: SimpleNamespace(redacted=True, truncated=False))
    response = client.get(f"/api/v1/policies/{policy['id']}/network-revoke-options", headers=tenant_a)
    assert response.status_code == 422
    assert 'api.example.com' not in response.text
