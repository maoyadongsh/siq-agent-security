"""Real API/CLI/ELF on disposable SQLite; synthetic approvers and RS256 issuer.

No application database or real identity provider is used. The API startup is
explicit development storage; the exercised authentication disables dev headers.
"""
from __future__ import annotations

import base64
import hashlib
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
        body = {'schema_version': 'deployment-behavior-start/v2', 'verification_id': challenge.verification_id,
                'profile_id': profile['profile_id'], 'profile_sha256': hashlib.sha256(raw.encode()).hexdigest()}
        checks = {}
        verified_settings, verified_cache = security.settings, security._jwks_cache
        try:
            with TestClient(app) as client:
                assert client.post(url, json=body).status_code == 401
                assert client.post(url, headers={'X-Dev-Tenant-Id': 't'}, json=body).status_code == 401
                checks['anonymous_and_dev_header_denied'] = True
                assert client.post(url, headers=headers('different-tenant'), json=body).status_code == 404
                assert client.post(url, headers=headers(roles=('viewer',)), json=body).status_code == 403
                checks['cross_tenant_and_readonly_probe_denied'] = True
                preview = client.get('/api/v1/deployments/d/behavior-profiles', headers=headers(roles=('viewer',)))
                assert preview.status_code == 200 and preview.json()['profiles'][0]['profile_sha256'] == body['profile_sha256']
                checks['readonly_template_preview_matches_v2_request'] = True
                response = client.post(url, headers=headers(), json=body)
                assert response.status_code == 200, response.text
                value = response.json()
                assert value['state'] == 'accepted' and value['observation_count'] == 12
                assert value['current_enforcement_verified'] is False
                checks['rs256_authenticated_real_collection'] = True
                assessment = client.post('/api/v1/deployments/d/behavior-assessment', headers=headers(roles=('viewer',)),
                    json={'schema_version': 'deployment-behavior-assess/v1', 'verification_id': challenge.verification_id})
                assert assessment.status_code == 200 and assessment.json()['state'] == 'verified', assessment.text
                assert assessment.json()['level'] == 'enforcement_verified'
                (self.out / 'current-assessment.json').write_text(json.dumps(assessment.json(), indent=2) + '\n')
                checks['read_only_current_grade_from_same_accepted_evidence'] = True
                if getattr(self, 'web', None) is not None:
                    self._browser(app, headers(roles=('viewer',)))
                    checks['real_browser_api_runtime_readback'] = True

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
        def after_change():
            previous_settings, previous_cache = security.settings, security._jwks_cache
            security.settings, security._jwks_cache = verified_settings, verified_cache
            try:
                with TestClient(app) as client:
                    response = client.post('/api/v1/deployments/d/behavior-assessment', headers=headers(roles=('viewer',)),
                        json={'schema_version': 'deployment-behavior-assess/v1',
                              'verification_id': challenge.verification_id})
                    assert response.status_code == 200 and response.json()['state'] == 'changed', response.text
                    assert response.json()['level'] == 'unverified' and not response.json()['current_enforcement_verified']
                    (self.out / 'changed-assessment.json').write_text(json.dumps(response.json(), indent=2) + '\n')
            finally:
                security.settings, security._jwks_cache = previous_settings, previous_cache
                get_engine().dispose()
        self.assess_changed = after_change

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

    def _browser(self, app, headers):
        import socket
        import subprocess
        import threading

        import uvicorn
        from fastapi.responses import FileResponse

        web = self.web.resolve(strict=True)
        assert (web / 'index.html').is_file()

        @app.get('/{asset_path:path}')
        def asset(asset_path: str):
            path = (web / asset_path).resolve()
            if not path.is_relative_to(web) or not path.is_file():
                path = web / 'index.html'
            return FileResponse(path)

        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(32)
        endpoint = f'http://127.0.0.1:{listener.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, lifespan='off'))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.05)
            worker = Path(__file__).with_name('behavior-live-browser-worker.py')
            env = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': '/home/maoyd/.cache/ms-playwright'}
            result = subprocess.run(['/home/maoyd/miniconda3/bin/python', str(worker)],
                input=json.dumps({'endpoint': endpoint, 'out': str(self.out), 'target': self.target,
                                  'authorization': headers['Authorization']}),
                text=True, capture_output=True, timeout=60, env=env, check=False)
            (self.out / 'live-browser.log').write_text(result.stdout + result.stderr)
            assert result.returncode == 0, 'owned live browser check failed; inspect private log'
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()
            assert not thread.is_alive(), 'owned API server did not stop'
