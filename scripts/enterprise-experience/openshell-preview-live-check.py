#!/usr/bin/env python3
"""Read-only real OpenShell preview with an isolated dev control plane; never apply."""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--xdg-root', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    endpoint = urlparse(args.endpoint)
    if (endpoint.scheme != 'https' or not ipaddress.ip_address(endpoint.hostname).is_loopback
            or endpoint.username or endpoint.password or endpoint.path not in ('', '/')
            or endpoint.query or endpoint.fragment or not endpoint.port):
        parser.error('An explicit HTTPS loopback gateway is required')
    if not args.cli.is_absolute() or not args.cli.is_file() or not args.xdg_root.is_absolute():
        parser.error('Explicit absolute CLI and XDG root are required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', args.target):
        parser.error('Invalid sandbox target')
    for name in ('config', 'state'):
        if not (args.xdg_root / name).is_dir():
            parser.error('Existing XDG config and TLS state directories are required')
    args.out_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='siq-e149-preview-') as raw:
        root = Path(raw)
        # No inherited provider credentials or unrelated control-plane settings.
        baseline = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL')}
        os.environ.clear()
        os.environ.update(baseline)
        os.environ.update({
            'SIQ_AS_DEV': '1', 'SIQ_AS_ALLOW_SQLITE': '1',
            'SIQ_AS_DATABASE_URL': 'sqlite:///' + str(root / 'control.db'),
            'SIQ_AS_SIGNING_KEY_FILE': str(root / 'signing.seed'),
            'SIQ_AS_ENFORCEMENT_BACKEND': 'openshell-cli',
            'SIQ_AS_OPENSHELL_CLI_BIN': str(args.cli),
            'SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT': args.endpoint,
            'SIQ_AS_OPENSHELL_GATEWAY_INSECURE': '0',
        })
        for name in ('CONFIG', 'STATE', 'DATA', 'CACHE'):
            os.environ['XDG_' + name + '_HOME'] = str(args.xdg_root / name.lower())
        sys.path.insert(0, str(ROOT / 'apps/control-api'))
        from app.adapters.openshell.cli_backend import OpenShellCliBackend
        from app.adapters.openshell.contracts import AdapterError
        from app.db import session_scope
        from app.main import app
        from app.models import (
            AgentAsset,
            AgentInstance,
            AuditEvent,
            Deployment,
            EdgeTask,
        )
        from app.routers import policies
        from fastapi.testclient import TestClient
        from sqlalchemy import func, select

        commands = []

        class ReadOnlyBackend(OpenShellCliBackend):
            def __init__(self):
                super().__init__(env_script='', runner=self.read_only_runner)

            def read_only_runner(self, argv):
                allowed = [
                    ['gateway', 'info'], ['status'], ['--version'],
                    ['policy', 'get', args.target, '--full'],
                ]
                if argv not in allowed:
                    raise AdapterError('live_check_write_command_forbidden')
                commands.append(argv[0])
                return self._subprocess_runner(argv)

        # Guard only restricts commands; all permitted responses come from the real CLI.
        policies.OpenShellCliBackend = ReadOnlyBackend
        backend = ReadOnlyBackend()
        caps = backend.probe()
        assert caps.handshake_verified and caps.gateway_version != 'unknown'
        first = backend.read_effective_policy(args.target)
        headers = {'X-Dev-Tenant-Id': 'dev-tenant', 'X-Dev-User-Id': 'preview-owner',
                   'X-Dev-Roles': 'platform_operator,security_admin,agent_owner,auditor'}
        reviewer = {**headers, 'X-Dev-User-Id': 'preview-reviewer', 'X-Dev-Roles': 'reviewer,viewer'}
        checks = {'live_tls_handshake': True, 'live_version_observed': True}
        with TestClient(app) as client:
            def post(path, body, status=200, identity=None):
                response = client.post('/api/v1' + path, headers=identity or headers, json=body)
                assert response.status_code == status, (path, response.status_code)
                return response.json()

            def counts():
                with session_scope() as session:
                    return [session.scalar(select(func.count()).select_from(model))
                            for model in (Deployment, EdgeTask, AuditEvent)]

            env = post('/environments', {'name': '真实网关只读验收', 'mode': 'enforce'}, 201)
            with session_scope() as session:
                asset = AgentAsset(tenant_id='dev-tenant', name='只读预览验收对象', status='confirmed')
                session.add(asset)
                session.flush()
                instance = AgentInstance(tenant_id='dev-tenant', asset_id=asset.id,
                                         environment_id=env['id'], runtime='hermes')
                session.add(instance)
                session.flush()
                asset_id, instance_id = asset.id, instance.id
                session.commit()
            binding = post('/runtime-bindings', {'agent_instance_id': instance_id,
                'environment_id': env['id'], 'backend': 'openshell-cli',
                'backend_target_id': args.target}, 201)
            # A proposed network restriction exists only in the isolated DB.
            policy = post('/policies', {'name': '只读验收提案（不执行）', 'selector': {'agent_ids': [asset_id]},
                                       'enforcement_mode': 'block', 'network': []}, 201)
            change = post('/change-requests', {'policy_id': policy['id'],
                                             'idempotency_key': 'live-preview-only'}, 201)
            review = client.get('/api/v1/change-requests/' + change['id'] + '/review', headers=reviewer)
            assert review.status_code == 200
            post('/change-requests/' + change['id'] + '/review-decision', {
                'schema_version': 'change-review-decision/v1', 'decision': 'approve',
                'review_digest': review.json()['review_digest']}, identity=reviewer)
            checks['isolated_api_binding_and_review'] = True
            body = {'schema_version': 'deployment-preview-request/v1', 'change_request_id': change['id'],
                    'environment_id': env['id'], 'binding_id': binding['id']}
            before = counts()
            value = post('/deployment-preview', body)
            assert value['backend'] == 'openshell-cli' and value['action'] == 'dynamic_update'
            assert value['target'] == args.target and value['base_revision'] == first.revision
            assert counts() == before
            checks['real_preview_no_state_or_audit_write'] = True
            second = post('/deployment-preview', body)
            assert second['preview_digest'] == value['preview_digest']
            checks['unchanged_context_has_stable_preview'] = True
            # Cache context changes without replacing live TLS state; stale submit
            # must stop before apply even though the real gateway is still reachable.
            os.environ['XDG_CACHE_HOME'] = str(root / 'other-cache')
            rejected = post('/deployment-preview/submit', {**body,
                'schema_version': 'deployment-preview-submit/v1',
                'preview_digest': value['preview_digest']}, 409)
            assert rejected['detail'] == 'deployment_preview_changed' and counts() == before
            checks['changed_context_refuses_old_digest_without_writes'] = True
            os.environ['XDG_CACHE_HOME'] = str(args.xdg_root / 'cache')
            final = backend.read_effective_policy(args.target)
            assert (first.revision, first.policy_digest) == (final.revision, final.policy_digest)
            checks['live_policy_revision_and_digest_unchanged'] = True
            checks['only_allowlisted_read_commands_executed'] = True
            result = {'schema_version': 'openshell-preview-live-check/v1', 'passed': all(checks.values()),
                'checks': checks, 'identity': 'isolated_dev_headers', 'real_gateway': True,
                'production_eligible': False, 'runtime_policy_mutated': False,
                'enforcement_verified': False, 'gateway_version': caps.gateway_version,
                'cli_version': caps.cli_version, 'tls_insecure': False,
                'target_digest': hashlib.sha256(args.target.encode()).hexdigest(),
                'gateway_scope_digest': caps.endpoint_fingerprint,
                'before_revision': first.revision, 'after_revision': final.revision,
                'before_policy_digest': first.policy_digest, 'after_policy_digest': final.policy_digest,
                'preview_digest': value['preview_digest'], 'command_count': len(commands),
                'post_preview_counts': {'deployments': before[0], 'edge_tasks': before[1]},
                'cli_sha256': hashlib.sha256(args.cli.read_bytes()).hexdigest()}
            (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps({'passed': result['passed'], 'checks': len(checks), 'runtime_policy_mutated': False}))


if __name__ == '__main__':
    main()
