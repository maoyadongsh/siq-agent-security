"""Actual RS256 signature verification with synthetic, locally served JWKS keys."""
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import security
from app.tests.test_oidc_jwt_verify import oidc_env as oidc_env


def request(token=None, **headers):
    if token is not None:
        headers['authorization'] = 'Bearer ' + token
    return Request({'type': 'http', 'headers': [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


def test_verified_identity_deadline_and_production_dev_headers_ignored(oidc_env):
    expiry = int(datetime.now(UTC).timestamp()) + 60
    token = oidc_env['mint'](exp=expiry, permissions=['policy:read'])
    identity, deadline = security.get_identity_with_expiry(request(token, **{'X-Dev-Tenant-Id': 'spoofed'}))
    assert identity.tenant_id == 'default' and identity.actor_id == 'user-1'
    assert identity.has_permission('policy:read') and not identity.has_permission('policy:manage')
    assert deadline == datetime.fromtimestamp(expiry, UTC)
    with pytest.raises(HTTPException) as error:
        security.get_identity_with_expiry(request(**{'X-Dev-Tenant-Id': 'spoofed'}))
    assert error.value.status_code == 401


@pytest.mark.parametrize('expiry', [None, True, '9999999999', float('inf'), float('nan'), 2**1024, -1])
def test_malformed_or_expired_signed_deadline_rejected(oidc_env, expiry):
    token = oidc_env['mint'](exp=expiry)
    with pytest.raises(HTTPException) as error:
        security.get_identity_with_expiry(request(token))
    assert error.value.status_code == 401 and error.value.detail == 'invalid_token'


def test_wrong_signature_cannot_supply_deadline(oidc_env):
    from app.tests.test_oidc_jwt_verify import _rsa_pair

    key, _ = _rsa_pair()
    with pytest.raises(HTTPException) as error:
        security.get_identity_with_expiry(request(oidc_env['mint'](key=key)))
    assert error.value.status_code == 401
