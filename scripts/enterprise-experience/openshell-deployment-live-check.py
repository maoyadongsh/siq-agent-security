#!/usr/bin/env python3
"""Own a disposable sandbox; exercise actual control API deployment and rollback."""
import argparse
import contextlib
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = Path('/home/maoyd/siq-research-engine/var/openshell/toolchains/v0.0.83/bin/openshell')
XDG = Path('/home/maoyd/siq-research-engine/var/openshell/xdg')
GATEWAY = 'siq-openshell-scope-validation'
ENDPOINT = 'https://127.0.0.1:17771'
IMAGE = 'ghcr.io/nvidia/openshell-community/sandboxes/base:latest'


def sha(data):
    return hashlib.sha256(data).hexdigest()


@contextlib.contextmanager
def serve_browser(app, web):
    import uvicorn
    from fastapi.responses import FileResponse

    @app.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        candidate = (web / path).resolve()
        if not candidate.is_relative_to(web) or not candidate.is_file():
            candidate = web / 'index.html'
        return FileResponse(candidate)

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        endpoint = f'http://127.0.0.1:{sock.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, lifespan='off', log_level='error', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                assert thread.is_alive(), 'isolated API server stopped'
                time.sleep(.05)
            assert server.started, 'isolated API server readiness timeout'
            yield endpoint
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), 'isolated API server cleanup not confirmed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--web', type=Path, required=True)
    args = parser.parse_args()
    web = args.web.resolve()
    assert (web / 'index.html').is_file(), 'Web build must exist before live validation'
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', str(Path.home() / '.cache/ms-playwright'))
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    target = 'siq-e151-' + uuid.uuid4().hex[:14]
    checks, traces = {}, []
    metadata = XDG / 'config/openshell/gateways' / GATEWAY / 'metadata.json'
    original_metadata = sha(metadata.read_bytes())
    assert json.loads(metadata.read_text())['gateway_endpoint'] == ENDPOINT
    image_id = subprocess.run(['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}'],
                              check=True, capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='siq-live-deployment-') as temporary:
        root = Path(temporary)
        baseline = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL', 'USER')}
        os.environ.clear()
        os.environ.update(baseline)
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = browser_cache
        os.environ['HOME'] = str(root / 'home')
        Path(os.environ['HOME']).mkdir()
        for name in ('CONFIG', 'STATE', 'DATA', 'CACHE'):
            p = root / name.lower()
            p.mkdir()
            os.environ['XDG_' + name + '_HOME'] = str(p)
        gateway_dir = root / 'config/openshell/gateways'
        gateway_dir.mkdir(parents=True)
        (gateway_dir / GATEWAY).symlink_to(metadata.parent, target_is_directory=True)
        (root / 'state/openshell').mkdir(parents=True)
        (root / 'state/openshell/tls').symlink_to(XDG / 'state/openshell/tls', target_is_directory=True)
        os.environ.update({'SIQ_AS_DEV': '1', 'SIQ_AS_ALLOW_SQLITE': '1',
            'SIQ_AS_DATABASE_URL': 'sqlite:///' + str(root / 'control.db'),
            'SIQ_AS_SIGNING_KEY_FILE': str(root / 'signing.seed'),
            'SIQ_AS_ENFORCEMENT_BACKEND': 'openshell-cli',
            'SIQ_AS_OPENSHELL_CLI_BIN': str(CLI), 'SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT': ENDPOINT,
            'SIQ_AS_OPENSHELL_GATEWAY_INSECURE': '0'})
        def cli(*args, timeout=45):
            try:
                r = subprocess.run([str(CLI), '--gateway', GATEWAY, *args],
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
                text = (r.stdout + r.stderr).decode('utf-8', 'replace').lower()
                traces.append({'operation': list(args[:2]), 'rc': r.returncode,
                    'stdout_digest': sha(r.stdout), 'stderr_digest': sha(r.stderr),
                    'diagnostic_tags': [s for s in ['decode', 'permission denied', 'not found', 'certificate',
                        'policy', 'image', 'timed out', 'connection refused', 'error'] if s in text]})
                return r
            except subprocess.TimeoutExpired:
                traces.append({'operation': list(args[:2]), 'timed_out': True})
                raise RuntimeError('CLI observation timed out; outcome unconfirmed') from None
        def catalog():
            r = cli('sandbox', 'list', '--limit', '1000', '--output', 'json')
            assert r.returncode == 0, 'cannot read gateway sandbox catalog'
            rows = json.loads(r.stdout)
            assert isinstance(rows, list)
            return rows
        def names(rows):
            return sorted(row['name'] for row in rows)
        # Selection and last-used sandbox metadata remain inside our private config.
        assert cli('gateway', 'select', GATEWAY).returncode == 0
        before = catalog()
        assert not before, 'dedicated validation gateway must be empty before ownership starts'
        policy = root / 'initial.yaml'
        policy.write_text('''version: 1
filesystem_policy:
  include_workdir: true
  read_only: [/]
  read_write: [/sandbox, /tmp, /dev/null]
landlock:
  compatibility: hard_requirement
process:
  run_as_user: sandbox
  run_as_group: sandbox
network_policies: {}
''')
        attempted = False
        result = {'schema_version': 'openshell-deployment-live-check/v1', 'passed': False,
                  'target': target, 'gateway': GATEWAY, 'gateway_endpoint': ENDPOINT,
                  'cli_sha256': sha(CLI.read_bytes()), 'image_id': image_id,
                  'production_eligible': False, 'checks': checks,
                  'web_files': {str(p.relative_to(web)): sha(p.read_bytes()) for p in sorted(web.rglob('*')) if p.is_file()}}
        try:
            attempted = True
            created = cli('sandbox', 'create', '--name', target, '--from', IMAGE,
                '--cpu', '500m', '--memory', '512Mi', '--no-auto-providers', '--policy', str(policy),
                '--label', 'siq.acceptance=e151', '--', '/bin/true', timeout=55)
            result['create_exit_code'] = created.returncode
            if created.returncode:
                # Synthetic create input contains no credentials. Retain only
                # a bounded redacted diagnostic to distinguish setup failures.
                diagnostic = re.sub(r'[A-Za-z0-9_+/=-]{32,}', '[REDACTED]', created.stderr.decode('utf-8', 'replace'))
                result['create_diagnostic'] = diagnostic[:500]
            assert target in names(catalog()), 'sandbox creation not independently confirmed'
            checks['owned_sandbox_created'] = True
            probe = cli('sandbox', 'exec', '--name', target, '--no-tty', '--timeout', '15', '--',
                        '/bin/sh', '-c', 'id -u; command -v curl', timeout=25)
            assert probe.returncode == 0, 'sandbox exec readiness failed'
            output = probe.stdout.decode().strip().splitlines()
            assert output and output[0] != '0', 'sandbox command unexpectedly ran as root'
            assert '/usr/bin/curl' in output, 'required curl executable absent'
            checks['non_root_execution_ready'] = True
            sys.path.insert(0, str(ROOT / 'apps/control-api'))
            from app.adapters.openshell.cli_backend import OpenShellCliBackend
            from app.adapters.openshell.contracts import AdapterError
            from app.adapters.openshell.policy_safety import policy_digest
            from app.db import session_scope
            from app.main import app
            from app.models import AgentAsset, AgentInstance
            from app.routers import policies
            from fastapi.testclient import TestClient
            class ObservedBackend(OpenShellCliBackend):
                def apply_dynamic(self, *args, **kwargs):
                    try:
                        return super().apply_dynamic(*args, **kwargs)
                    except AdapterError as error:
                        code = str(error)
                        result['adapter_error_code'] = code if re.fullmatch(r'[a-z0-9_]{1,96}', code) else 'redacted'
                        snapshot = self.read_effective_policy(target)
                        result['failed_readback_shape'] = {'keys': sorted(snapshot.policy),
                            'network_present': 'network_policies' in snapshot.policy,
                            'network_empty': not snapshot.policy.get('network_policies')}
                        raise
            # Observational wrapper records only failure categories. It never
            # substitutes CLI output or changes the actual adapter operation.
            policies.OpenShellCliBackend = ObservedBackend
            backend = OpenShellCliBackend(env_script='')
            caps = backend.probe()
            assert caps.handshake_verified and caps.handshake_gateway == GATEWAY
            initial = backend.read_effective_policy(target)
            result['initial_revision'] = initial.revision
            result['initial_policy_digest'] = initial.policy_digest
            headers = {'X-Dev-Tenant-Id': 'dev-tenant', 'X-Dev-User-Id': 'live-owner',
                       'X-Dev-Roles': 'platform_operator,security_admin,agent_owner,auditor'}
            reviewer = {**headers, 'X-Dev-User-Id': 'live-reviewer', 'X-Dev-Roles': 'reviewer,viewer'}
            with TestClient(app) as client, serve_browser(app, web) as endpoint:
                def post(path, body, expected=200, identity=None):
                    r = client.post('/api/v1' + path, headers=identity or headers, json=body)
                    if r.status_code != expected:
                        result['failed_api'] = {'path_kind': path.split('/')[1], 'status': r.status_code}
                        raise RuntimeError('control API step failed')
                    return r.json()
                env = post('/environments', {'name': '独立沙箱执行验收', 'mode': 'enforce'}, 201)
                with session_scope() as session:
                    asset = AgentAsset(tenant_id='dev-tenant', name='独立网络验收', status='confirmed')
                    session.add(asset)
                    session.flush()
                    instance = AgentInstance(tenant_id='dev-tenant', asset_id=asset.id,
                                             environment_id=env['id'], runtime='openshell')
                    session.add(instance)
                    session.flush()
                    asset_id, instance_id = asset.id, instance.id
                    session.commit()
                binding = post('/runtime-bindings', {'agent_instance_id': instance_id,
                    'environment_id': env['id'], 'backend': 'openshell-cli', 'backend_target_id': target}, 201)
                def deploy(network, label):
                    desired = post('/policies', {'name': '独立验收-' + label, 'selector': {'agent_ids': [asset_id]},
                        'network': network, 'enforcement_mode': 'block'}, 201)
                    change = post('/change-requests', {'policy_id': desired['id'], 'idempotency_key': str(uuid.uuid4())}, 201)
                    review = client.get('/api/v1/change-requests/' + change['id'] + '/review', headers=reviewer)
                    assert review.status_code == 200
                    post('/change-requests/' + change['id'] + '/review-decision',
                        {'schema_version': 'change-review-decision/v1', 'decision': 'approve',
                         'review_digest': review.json()['review_digest']}, identity=reviewer)
                    with (out / (label + '-browser.log')).open('wb') as log:
                        subprocess.run(['python3', str(ROOT / 'scripts/enterprise-experience/deployment-live-browser-worker.py'),
                            '--endpoint', endpoint, '--change', change['id'], '--environment', env['id'],
                            '--binding', binding['id'], '--target', target, '--out', str(out / (label + '-browser'))],
                            check=True, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                    browser_result = json.loads((out / (label + '-browser/result.json')).read_text())
                    assert browser_result['passed'] and browser_result['post_count'] == 1
                    body, submission = browser_result['request'], browser_result['submission']
                    checks[label + '_browser_real_submit_and_refresh'] = True
                    result[label + '_submission'] = submission
                    assert submission['deployment_status'] == 'effective', 'deployment lacks verified config readback'
                    again = post('/deployment-submissions', body)
                    assert again == submission, 'idempotent retry changed the submission'
                    history = client.get('/api/v1/change-requests/' + change['id'] + '/execution', headers=headers)
                    assert history.status_code == 200 and len(history.json()['deployments']) == 1
                    row = history.json()['deployments'][0]
                    assert row['id'] == submission['deployment_id'] and row['verification_level'] == 'config_readback'
                    checks[label + '_real_deployment_readback_and_no_replay'] = True
                    return submission
                def network_probe(expected):
                    command = ('printf "SIQ_PROBE_START\\n"; '
                        '/usr/bin/curl --silent --show-error --fail --max-time 12 '
                        '--output /dev/null --write-out "%{http_code}" https://example.com/; '
                        'rc=$?; printf "\\nSIQ_CURL_RC=%s\\n" "$rc"; exit "$rc"')
                    response = cli('sandbox', 'exec', '--name', target, '--no-tty', '--timeout', '20', '--',
                        '/bin/sh', '-c', command, timeout=25)
                    match = re.search(r'SIQ_PROBE_START\s+(\d{3})\s+SIQ_CURL_RC=(\d+)', response.stdout.decode())
                    assert match and int(match[2]) == response.returncode, 'probe command completion not independently identified'
                    code = match[1]
                    forbidden = response.returncode == 22 and bool(re.search(
                        rb'curl: \(22\) (?:The requested URL returned error: 403|CONNECT tunnel failed, response 403)',
                        response.stderr))
                    result.setdefault('network_probes', []).append({'expected': expected,
                        'exit_code': response.returncode, 'http_code': code if code.isdigit() and len(code) == 3 else None,
                        'explicit_http_403': forbidden,
                        'stdout_digest': sha(response.stdout), 'stderr_digest': sha(response.stderr)})
                    if expected == 'deny':
                        assert forbidden, 'negative probe must be explicit HTTP 403, not an unrelated execution failure'
                    return response.returncode == 0 and code == '200'
                allow = deploy([{'endpoint': 'example.com:443', 'effect': 'allow', 'binary_paths': ['/usr/bin/curl']}], 'allow')
                assert network_probe('allow'), 'allowed public probe did not succeed'
                checks['allowed_request_succeeds'] = True
                allowed_policy = backend.read_effective_policy(target)
                deny = deploy([], 'deny')
                assert not network_probe('deny'), 'same request was not refused after revocation'
                denied_logs = cli('logs', target, '--source', 'sandbox', '-n', '100')
                assert denied_logs.returncode == 0, 'cannot inspect sandbox denial observations'
                text = denied_logs.stdout.decode('utf-8', 'replace').lower()
                result['denial_log_digest'] = sha(denied_logs.stdout)
                result['denial_log_matching_lines'] = sum('example.com' in line and
                    any(term in line for term in ('deny', 'denied', 'block', 'reject')) for line in text.splitlines())
                checks['same_request_refused_after_revocation'] = True
                post('/deployments/' + deny['deployment_id'] + '/rollback', {})
                restored = backend.read_effective_policy(target)
                assert restored.policy_digest == allowed_policy.policy_digest, 'rollback did not restore exact prior policy'
                assert network_probe('allow_after_rollback'), 'restored allowance did not recover behavior'
                checks['exact_rollback_and_allowed_behavior_recovered'] = True
                result['restored_revision'] = restored.revision
                result['restored_policy_digest'] = policy_digest(restored.policy)
                # Restore the original deny-all policy through the earlier deployment receipt.
                # A later revision makes old receipt rollback invalid; deletion below is the
                # authoritative cleanup, not an unsafe forced rollback over intervening work.
                result['first_deployment_id'] = allow['deployment_id']
            result['passed'] = True
        finally:
            if attempted:
                present = names(catalog())
                if target in present:
                    cli('sandbox', 'delete', target, timeout=30)
                for _ in range(20):
                    after = catalog()
                    if target not in names(after):
                        break
                    time.sleep(.25)
                checks['owned_sandbox_deleted'] = target not in names(after)
                checks['other_sandbox_catalog_unchanged'] = names(after) == names(before)
            checks['original_gateway_metadata_unchanged'] = sha(metadata.read_bytes()) == original_metadata
            result['passed'] = result['passed'] and all(checks.values())
            result['cli_traces'] = traces
            (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            assert checks.get('owned_sandbox_deleted'), 'owned sandbox cleanup not confirmed'
        print(json.dumps({'passed': result['passed'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()
