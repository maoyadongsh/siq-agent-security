"""Real API/CLI/ELF on disposable SQLite; synthetic approvers and RS256 issuer.

No application database or real identity provider is used. The API startup is
explicit development storage; the exercised authentication disables dev headers.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.adapters.openshell.behavior_journal import behavior_fact
from app.adapters.openshell.behavior_protocol import BehaviorChallengeV2
from app.models import (
    AuditEvent,
    ChangeRequest,
    DesiredPolicy,
    Environment,
    OpenShellBehaviorOperation,
    RuntimeBinding,
)
from behavior_coordinated_fixture import CoordinatedFixture
from sqlalchemy import select


class ApiFixture(CoordinatedFixture):
    def apply(self, network):
        with self.sessions.begin() as session:
            session.get(Environment, 'e').mode = 'enforce'
            session.get(ChangeRequest, 'c').approved_at = datetime.now(UTC).replace(tzinfo=None)
            session.get(DesiredPolicy, 'p').network = network
        super().apply(network)

    def collect(self, challenge, protection_target):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from fastapi.testclient import TestClient

        self.profile_directory = tempfile.TemporaryDirectory(prefix='siq-behavior-api-')
        private = Path(self.profile_directory.name)
        profile = {k: v for k, v in challenge.model_dump().items()
                   if k not in ('schema_version', 'verification_id', 'nonce')}
        profile.update(profile_id='owned-api-acceptance', gateway_name_sha256=self.gateway_hash,
                       protection=asdict(protection_target))
        raw = json.dumps({'schema_version': 'openshell-behavior-profiles/v1', 'profiles': [profile]}, indent=2)
        (private / 'profiles.json').write_text(raw)
        (self.out / 'approved-profiles.json').write_text(raw)
        now = datetime.now(UTC)
        authority = {'schema_version': 'enterprise-runtime-target-authority/v1',
            'issued_at': (now - timedelta(minutes=1)).isoformat(),
            'expires_at': (now + timedelta(minutes=10)).isoformat(), 'assignments': [{
                'id': 'owned-api-assignment', 'tenant_id': 't', 'environment_id': 'e', 'asset_id': 'a',
                'agent_instance_id': 'i', 'backend_target_id': self.target,
                'endpoint_fingerprint': self.caps.endpoint_fingerprint, 'gateway_name_sha256': self.gateway_hash}]}
        (private / 'authority.json').write_text(json.dumps(authority))
        # Only this fixture's generated key material; private file removed on close.
        (private / 'recovery.json').write_text(json.dumps({'active_key_id': self.cipher._active,
            'keys': {key: base64.b64encode(value).decode() for key, value in self.cipher._keys.items()}}))
        for path in private.iterdir():
            path.chmod(0o600)
        os.environ.update(SIQ_AS_DEV='1', SIQ_AS_ALLOW_SQLITE='1', SIQ_AS_ENFORCEMENT_BACKEND='openshell-cli',
            SIQ_AS_DATABASE_URL=f"sqlite:///{self.out / 'coordination.db'}",
            SIQ_AS_SIGNING_KEY_FILE=str(private / 'signing.seed'),
            SIQ_AS_OPENSHELL_BEHAVIOR_PROFILES_FILE=str(private / 'profiles.json'),
            SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE=str(private / 'authority.json'),
            SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE=str(private / 'recovery.json'))
        from app import security
        from app.db import get_engine
        from app.jwks import JWKSCache
        from app.main import app

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update(kid='owned-fixture', alg='RS256', use='sig')
        original_settings, original_cache = security.settings, security._jwks_cache
        security.settings = replace(security.settings, dev_mode=False, oidc_jwks_url='https://issuer.invalid/jwks',
                                    oidc_issuer='https://issuer.invalid/')
        security._jwks_cache = JWKSCache(url=security.settings.oidc_jwks_url, ttl_seconds=60,
                                        fetch=lambda _: {'keys': [jwk]})

        def headers(tenant='t', roles=('security_admin',)):
            token = jwt.encode({'sub': 'synthetic-api-operator', 'tenant_id': tenant, 'type': 'access',
                'iss': security.settings.oidc_issuer, 'aud': security.settings.jwt_audience,
                'iat': int(time.time()), 'exp': int(time.time()) + 600, 'role_codes': list(roles)},
                key, algorithm='RS256', headers={'kid': 'owned-fixture'})
            return {'Authorization': 'Bearer ' + token}

        url = '/api/v1/deployments/d/behavior-verifications'
        body = {'schema_version': 'deployment-behavior-start/v1', 'verification_id': challenge.verification_id,
                'profile_id': profile['profile_id']}
        checks = {}
        try:
            with TestClient(app) as client:
                assert client.post(url, json=body).status_code == 401
                assert client.post(url, headers={'X-Dev-Tenant-Id': 't'}, json=body).status_code == 401
                checks['anonymous_and_dev_header_denied'] = True
                assert client.post(url, headers=headers('different-tenant'), json=body).status_code == 404
                assert client.post(url, headers=headers(roles=('viewer',)), json=body).status_code == 403
                checks['cross_tenant_and_readonly_probe_denied'] = True
                response = client.post(url, headers=headers(), json=body)
                assert response.status_code == 200, response.text
                value = response.json()
                assert value['state'] == 'accepted' and value['observation_count'] == 12
                assert value['current_enforcement_verified'] is False
                checks['rs256_authenticated_real_collection'] = True
                assert client.post(url, headers=headers(), json=body).json() == value
                history = client.get(url + '/' + body['verification_id'], headers=headers(roles=('viewer',)))
                assert history.status_code == 200 and history.json() == value
                assert history.headers['cache-control'] == 'no-store'
                checks['repeat_and_history_no_probe_replay'] = True
                with self.sessions.begin() as session:
                    session.get(RuntimeBinding, 'b').status = 'revoked'
                new_id = 'opv-' + uuid.uuid4().hex
                blocked = client.post(url, headers=headers(), json={**body, 'verification_id': new_id})
                assert blocked.status_code == 409
                with self.sessions.begin() as session:
                    assert session.get(OpenShellBehaviorOperation, new_id) is None
                    session.get(RuntimeBinding, 'b').status = 'active'
                checks['revoked_binding_blocks_new_operation'] = True
                (self.out / 'api-response.json').write_text(json.dumps(value, indent=2) + '\n')
        finally:
            security.settings, security._jwks_cache = original_settings, original_cache
            get_engine().dispose()
        with self.sessions() as session:
            fact = behavior_fact(session.get(OpenShellBehaviorOperation, challenge.verification_id), 't', 'd')
            audits = list(session.scalars(select(AuditEvent).where(AuditEvent.action.like('openshell.behavior.%'))))
            assert len(audits) == 3 and all(row.actor_id == 'synthetic-api-operator' for row in audits)
            assert fact.profile_id == profile['profile_id'] and fact.state == 'accepted'
            checks['authenticated_actor_and_profile_durable_audit'] = True
        (self.out / 'api-acceptance.json').write_text(json.dumps({
            'schema_version': 'behavior-api-live-fixture/v1', 'passed': True, 'checks': checks,
            'database_backend': 'disposable_development_sqlite', 'synthetic_database_approval': True,
            'synthetic_rs256_issuer': True, 'real_identity_provider': False, 'authenticated_api': True,
            'transport': 'in_process_asgi', 'real_cli_and_probe': True, 'real_durable_apply': True,
            'verification_id': fact.verification_id, 'deployment_grade_promoted': False,
            'recorded_at': datetime.now(UTC).isoformat()}, indent=2) + '\n')
        return BehaviorChallengeV2.model_validate(fact.challenge), fact.result
