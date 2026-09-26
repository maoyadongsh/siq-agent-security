#!/usr/bin/env python3
"""Real loopback Gateway -> Control API -> native Edge/Connector acceptance.

All identities, databases and scanned files are synthetic private fixtures.
No sibling imports, production accounts, live configurations or model calls.
"""
import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway', type=Path, required=True)
    parser.add_argument('--edge', type=Path, required=True)
    parser.add_argument('--connector-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--serve', action='store_true', help='Use unified Linux service instead of manual tasks')
    parser.add_argument('--recover-registration', action='store_true',
                        help='Simulate unavailable finalized local state, then recover through the real API')
    parser.add_argument('--consent', action='store_true',
                        help='Issue/confirm a synthetic plan and verify signed scope denial')
    parser.add_argument('--initial-scan', action='store_true',
                        help=('Verify initial-scan API and replay using native describe '
                              'plus manual native task execution'))
    parser.add_argument('--untrusted-skill-bundle', dest='skill_sources', action='store_true',
                        help='Verify unsigned unstaged skill collection is refused, with no upload')
    args = parser.parse_args()
    if args.initial_scan and not args.consent:
        parser.error('--initial-scan requires --consent')
    if args.skill_sources and not args.initial_scan:
        parser.error('--untrusted-skill-bundle requires --initial-scan and --consent')
    if args.serve and args.consent:
        parser.error('Synthetic consent fixture has no signed release; '
                     'measured serve requires a separate signed-bundle scenario')
    if args.out.exists():
        raise SystemExit('Refusing to overwrite evidence')
    gateway = args.gateway.resolve()
    checks = {}
    processes = []
    result = {'schema_version': 'siq.gateway-edge-smoke/v1', 'passed': False,
              'unified_service': args.serve,
              'registration_recovery': args.recover_registration,
              'discovery_consent': args.consent,
              'initial_scan': args.initial_scan,
              'untrusted_skill_bundle': args.skill_sources,
              'publisher_release_verified': False,
              'recorded_at': datetime.now(UTC).isoformat(),
              'harness_sha256': digest(Path(__file__)),
              'scope': ('Real HTTP, native binaries, isolated SQLite and synthetic dev identities; '
                        'not production IAM or deployment.'),
              'checks': checks, 'edge_sha256': digest(args.edge),
              'connector_sha256': digest(args.connector_dir / 'hermes-connector'),
              'api_source_sha256': {str(p.relative_to(ROOT)): digest(p)
                  for p in sorted((ROOT / 'apps/control-api/app').rglob('*.py'))
                  if '__pycache__' not in p.parts},
              'gateway_source_sha256': {p: digest(gateway / p) for p in
                  ('src/siq_gateway/main.py', 'src/siq_gateway/edge.py')}}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix='siq-gateway-edge-') as raw, tempfile.TemporaryFile() as logs:
        root = Path(raw)
        fixture_home = root / 'home'
        profile = fixture_home / '.hermes/profiles/fixture'
        profile.mkdir(parents=True)
        (profile / 'config.yaml').write_text('model: synthetic-model\ntoolsets:\n  - file\n')
        (profile / 'SOUL.md').write_text('Synthetic acceptance role.\n')
        skill_root = profile / 'skills'
        skill_file = skill_root / 'fixture-skill' / 'SKILL.md'
        if args.skill_sources:
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text('---\nname: fixture-skill\nallowed-tools: read_file\n---\nSynthetic only.\n')
            result['directory_sha256'] = digest(args.connector_dir / 'directory-connector')
        api_port, gateway_port = port(), port()
        while api_port == gateway_port:
            gateway_port = port()
        api_url, gateway_url = f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{gateway_port}'
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL', 'TZ')}
        env.update({'HOME': str(fixture_home), 'SIQ_AS_DEV': '1', 'SIQ_AS_ALLOW_SQLITE': '1',
                    'SIQ_AS_DATABASE_URL': f'sqlite:///{root}/api.db',
                    'SIQ_AS_SIGNING_KEY_FILE': str(root / 'signing.seed'),
                    'SIQ_AS_ENFORCEMENT_BACKEND': 'fake',
                    'SIQ_EDGE_STATE_DIR': str(root / 'edge-state'),
                    'SIQ_CONNECTOR_BIN_DIR': str(args.connector_dir.resolve())})
        if args.consent:
            architecture = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64'}[platform.machine()]
            # Catalog is explicitly synthetic; no publisher signature or staging
            # verification is claimed by this consent-only scenario.
            catalog = root / 'install-catalog.json'
            catalog.write_text(json.dumps({
                'schema_version': 'enterprise-install-catalog/v1',
                'control_plane_origin': gateway_url, 'allowed_service_modes': ['user'],
                'releases': [{'target_arch': architecture, 'release_version': '0.4.0-test',
                    'release_manifest_sha256': '0' * 64, 'connectors': [{
                        'id': 'hermes', 'version': '0.1.0',
                        'artifact_sha256': digest(args.connector_dir / 'hermes-connector'),
                        'protocol_version': 'connector-protocol.v1',
                        'scope': {'roots': ['~/.hermes/profiles/*'], 'include': ['config.yaml', 'SOUL.md']}}]}]}))
            catalog.chmod(0o600)
            if args.skill_sources:
                value = json.loads(catalog.read_text())
                value['releases'][0]['connectors'].append({
                    'id': 'directory', 'version': '0.1.0',
                    'artifact_sha256': digest(args.connector_dir / 'directory-connector'),
                    'protocol_version': 'connector-protocol.v1',
                    'scope': {'roots': [str(skill_root)], 'include': ['SKILL.md']}})
                catalog.write_text(json.dumps(value))
            env['SIQ_AS_INSTALL_CATALOG_FILE'] = str(catalog)
        gw_env = {k: v for k, v in env.items() if not k.startswith('SIQ_')}
        gw_env.update({'SIQ_GW_DB_URL': f'sqlite:///{root}/gateway.db',
                       'SIQ_GW_JWT_SECRET': 'synthetic-fixture-key-at-least-32-bytes',
                       'SIQ_GATEWAY_EMBEDDED_WORKERS': '0', 'SIQ_AGENT_SECURITY_URL': api_url})
        headers = {'X-Dev-Tenant-Id': 'fixture-a', 'X-Dev-User-Id': 'fixture-admin',
                   'X-Dev-Roles': 'platform_operator,agent_owner'}

        def api(path, body=None, expected=200, custom=None, base=gateway_url):
            request = urllib.request.Request(base + path, headers={
                'Content-Type': 'application/json', **(headers if custom is None else custom)},
                data=None if body is None else json.dumps(body).encode())
            try:
                response = opener.open(request, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                assert response.status == expected, f'{path}: status {response.status}, expected {expected}'
                return json.load(response)

        def command(arguments, code=None, success=True):
            run = subprocess.run([str(args.edge.resolve()), *arguments], env=env,
                                 input=code, capture_output=True, text=True, timeout=30, check=False)
            assert (run.returncode == 0) == success, f'Edge {arguments[0]} unexpected exit'
            if code:
                assert code.strip() not in run.stdout + run.stderr
            return run

        def start(repo, python, module, listen, process_env):
            proc = subprocess.Popen([str(python), '-m', 'uvicorn', module, '--host', '127.0.0.1',
                                     '--port', str(listen), '--log-level', 'error', '--no-access-log'],
                                    cwd=repo, env=process_env, stdout=logs, stderr=logs)
            processes.append(proc)
            for _ in range(100):
                assert proc.poll() is None, f'{module}: process exited'
                try:
                    api('/health', base=f'http://127.0.0.1:{listen}', custom={})
                    return
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(.1)
            raise RuntimeError('readiness timeout')

        try:
            start(ROOT / 'apps/control-api', ROOT / 'apps/control-api/.venv/bin/python',
                  'app.main:app', api_port, env)
            start(gateway, gateway / '.venv/bin/python', 'siq_gateway.main:app', gateway_port, gw_env)
            prefix = '/api/agent-security/v1'
            api('/edge/v1/tasks', custom={}, expected=401)
            api('/edge/v2/tasks', custom={}, expected=404)
            checks['anonymous_denied_and_unknown_version_not_spa'] = True
            owned = api(prefix + '/environments', {'name': 'synthetic-dgx', 'mode': 'discovery'}, 201)
            other_headers = {**headers, 'X-Dev-Tenant-Id': 'fixture-b'}
            other = api(prefix + '/environments', {'name': 'synthetic-other'}, 201, custom=other_headers)
            api(prefix + f'/environments/{owned["id"]}/onboarding', custom=other_headers, expected=404)
            checks['cross_tenant_environment_denied'] = True
            enrollment = api(prefix + f'/environments/{owned["id"]}/edge-enrollment', {})['code']
            register_args = ['register', '--control-plane', gateway_url, '--enrollment-code-stdin']
            if args.consent:
                register_args.extend(['--environment', owned['id']])
            command(register_args, enrollment + '\n')
            state_file = root / 'edge-state/state.json'
            state = json.loads(state_file.read_text())
            assert state['environment_id'] == owned['id']
            state_hash = digest(state_file)
            command(['register', '--control-plane', gateway_url, '--enrollment-code-stdin'],
                    enrollment + '\n', success=False)
            assert digest(state_file) == state_hash
            api('/edge/v1/register', {'enrollment_code': enrollment,
                'device_identity': 'synthetic-replay', 'public_key_pem': state['public_key_pem'],
                'version': '0.1.0'}, expected=401, custom={})
            checks['native_registration_identity_preserved_and_code_replay_denied'] = True
            if args.recover_registration:
                # Only our synthetic temporary state is moved. This simulates
                # unavailable finalized state, not packet-level response loss.
                old_state = state
                state_file.rename(root / 'edge-state/original-state.private')
                command(['recover-registration', '--control-plane', gateway_url,
                         '--environment', owned['id']])
                state = json.loads(state_file.read_text())
                assert state['device_identity'] == old_state['device_identity']
                assert state['signer_seed'] == old_state['signer_seed']
                assert state['environment_id'] == owned['id']
                assert state['secret'] != old_state['secret']
                old_headers = {'Authorization': 'Bearer ' + old_state['secret'],
                               'X-Edge-Identity': old_state['device_identity']}
                api('/edge/v1/heartbeat', {'version': 'fixture'}, custom=old_headers, expected=401)
                checks['native_signed_registration_recovery_and_old_credential_denied'] = True
            device_headers = {'Authorization': 'Bearer ' + state['secret'], 'X-Edge-Identity': state['device_identity']}
            if args.consent:
                plan = api(prefix + f'/environments/{owned["id"]}/install-plans', {
                    'schema_version': 'enterprise-install-request/v1', 'target_arch': architecture,
                    'service_mode': 'user',
                    'connectors': ['hermes', 'directory'] if args.skill_sources else ['hermes']})
                plan_file = root / 'confirmed-plan.json'
                plan_file.write_text(json.dumps(plan))
                command(['confirm-discovery-plan', '--plan', str(plan_file), '--tenant', 'fixture-a',
                         '--confirm-plan-sha256', digest(plan_file)])
                state = json.loads(state_file.read_text())
                assert state['discovery_plan']['plan_id'] == plan['plan_id']
                checks['api_plan_confirmed_by_native_edge'] = True
            heartbeat = subprocess.Popen([str(args.edge.resolve()), 'serve' if args.serve else 'heartbeat'],
                                         env=env, stdout=logs, stderr=logs)
            processes.append(heartbeat)
            route = prefix + f'/environments/{owned["id"]}/onboarding'
            for _ in range(100):
                assert heartbeat.poll() is None
                status = api(route)
                if status['devices'][0]['status'] == 'online':
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('heartbeat not observed')
            checks['native_heartbeat_read_back'] = True
            foreign_task = api(prefix + '/scans', {'environment_id': other['id'], 'connector': 'hermes',
                                'scope': {'roots': ['~/.hermes/profiles/*']}}, 200, custom=other_headers)['task_id']
            assert not any(t['id'] == foreign_task for t in api('/edge/v1/tasks', custom=device_headers))
            checks['device_does_not_receive_other_environment_tasks'] = True
            if args.initial_scan:
                # Only the explicitly supplied test connector executes, inside
                # the synthetic home. This is not publisher/stage verification.
                probe = subprocess.run([str((args.connector_dir / 'hermes-connector').resolve()), '--serve'],
                    input=json.dumps({'id': 'describe-fixture', 'op': 'describe', 'params': {}}) + '\n',
                    env=env, text=True, capture_output=True, timeout=10, check=False)
                assert probe.returncode == 0, 'native description failed'
                described = json.loads(probe.stdout)
                assert described['ok'] and described['id'] == 'describe-fixture'
                caps = described['result']
                assert caps['version'] == plan['connectors'][0]['version']
                inventory = {
                    'inventory_schema': 'enterprise-installed-capabilities/v1',
                    'protocol_version': 'connector-protocol.v1',
                    'connectors': ['hermes'], 'connector_versions': {'hermes': caps['version']},
                    'data_categories': caps['data_categories']}
                if args.skill_sources:
                    described_directory = subprocess.run(
                        [str((args.connector_dir / 'directory-connector').resolve()), '--serve'],
                        input=json.dumps({'id': 'directory-fixture', 'op': 'describe', 'params': {}}) + '\n',
                        env=env, text=True, capture_output=True, timeout=10, check=True)
                    directory = json.loads(described_directory.stdout)
                    assert directory['ok'] and directory['id'] == 'directory-fixture'
                    assert 'skill_manifest_ancestry_v2' in directory['result']['objects']
                    assert directory['result']['version'] == plan['connectors'][1]['version']
                    inventory.update(inventory_schema='enterprise-installed-capabilities/v2',
                        connectors=['hermes', 'directory'],
                        connector_versions={'hermes': caps['version'], 'directory': directory['result']['version']},
                        connector_task_types={'hermes': ['scan'], 'directory': ['scan', 'skill_scan']})
                api('/edge/v1/heartbeat', {'version': 'fixture', 'capabilities': inventory}, custom=device_headers)
                first_request = {
                    'schema_version': 'edge-initial-scan/v2' if args.skill_sources else 'edge-initial-scan/v1',
                    'plan': plan}
                initial = api('/edge/v1/initial-scan', first_request, custom=device_headers)
                replay = api('/edge/v1/initial-scan', first_request, custom=device_headers)
                assert initial['replay'] is False and replay['replay'] is True
                assert len(initial['task_ids']) == (2 if args.skill_sources else 1)
                assert initial['task_ids'] == replay['task_ids']
                task = initial['task_ids'][0]
                fetched = api('/edge/v1/tasks', custom=device_headers)
                selected = next(t for t in fetched if t['id'] == task)
                assert selected['payload']['target_device_identity'] == state['device_identity']
                assert selected['payload']['scope'] == plan['connectors'][0]['scope']
                checks['native_describe_and_plan_bound_initial_scan_replay'] = True
            else:
                task = api(prefix + '/scans', {'environment_id': owned['id'], 'connector': 'hermes',
                           'scope': {'roots': ['~/.hermes/profiles/*'],
                                     'include': ['config.yaml', 'SOUL.md']}})['task_id']
            denied_task = None
            if args.consent:
                (profile / 'unconfirmed.yaml').write_text('synthetic unconfirmed content')
                denied_task = api(prefix + '/scans', {'environment_id': owned['id'], 'connector': 'hermes',
                    'scope': {'roots': ['~/.hermes/profiles/*'], 'include': ['unconfirmed.yaml']}})['task_id']
            if args.serve:
                command(['tasks'], success=False)
                checks['manual_runner_rejected_while_service_active'] = True
                for _ in range(450):
                    assert heartbeat.poll() is None, 'unified service exited'
                    observed = api(route)
                    good_done = any(s['id'] == task and s['status'] == 'delivered' for s in observed['scans'])
                    denied_done = denied_task is None or any(
                        s['id'] == denied_task and s['status'] == 'failed' for s in observed['scans'])
                    if good_done and denied_done:
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('service task polling timeout')
            else:
                execution = command(['tasks'])
                if args.skill_sources:
                    # Collection failures deliberately expose only the public
                    # recovery category, not the nested verifier diagnostic.
                    assert 'skill_execution_unconfirmed' in execution.stderr
                    remaining = api('/edge/v1/tasks', custom=device_headers)
                    skill_task = initial['task_ids'][1]
                    assert any(t['id'] == skill_task for t in remaining)
                    # Task wire intentionally omits persistence status. Inspect
                    # only this harness's synthetic database for the negative proof.
                    denied = subprocess.run([str(ROOT / 'apps/control-api/.venv/bin/python'), '-c',
                        ('import sys; from app.db import init_db,session_scope; from app.config import load_settings\n'
                        'from app.models import EdgeTask,SkillUploadReceipt\n'
                        'init_db(load_settings())\n'
                        'with session_scope() as s:\n'
                        ' assert s.get(EdgeTask,sys.argv[1]).status == "pending"\n'
                         ' assert s.get(SkillUploadReceipt,sys.argv[1]) is None\n'), skill_task],
                        cwd=ROOT / 'apps/control-api', env=env, capture_output=True, timeout=15, check=False)
                    assert denied.returncode == 0, 'untrusted skill task changed upload or completion state'
            status = api(route)
            scan = next(s for s in status['scans'] if s['id'] == task)
            assert scan['status'] == 'delivered' and scan['candidate_count'] > 0 and status['evidence_count'] > 0
            assert scan['device_identity'] == state['device_identity']
            checks['native_connector_signed_upload_and_receipt_read_back'] = True
            # Read the actual native upload through the Gateway. Expectations
            # come from synthetic input paths/bytes, never from response hashes.
            tree = api(prefix + '/framework-role-inventory?environment_id=' + owned['id'])
            assert tree['schema_version'] == 'enterprise-framework-role-inventory/v2'
            assert len(tree['items']) == 1 and tree['next_cursor'] is None
            asset_id = tree['items'][0]['asset_id']
            view = api(prefix + f'/agents/{asset_id}/framework-source')
            assert tree['items'][0]['framework_source'] == view
            assert view['schema_version'] == 'enterprise-framework-source-view/v2'
            assert view['status'] == 'historical_reported_source'
            assert view['source']['framework'] == 'hermes'
            assert view['source']['instance_key'] == hashlib.sha256(str(profile).encode()).hexdigest()
            assert view['source']['config_sha256'] == digest(profile / 'config.yaml')
            assert view['effective_permissions'] is None and view['runtime_status'] == 'unverified'
            history = api(prefix + f'/agents/{asset_id}/configuration-observations')
            assert history['schema_version'] == 'enterprise-role-configuration-history/v2'
            assert len(history['items']) == 1 and history['next_cursor'] is None
            snapshot = history['items'][0]
            assert snapshot['status'] == 'recorded_snapshot'
            configuration = snapshot['configuration']
            assert configuration['task_id'] == task
            assert configuration['framework_source']['config_sha256'] == digest(profile / 'config.yaml')
            roots = configuration['skill_source_roots']
            assert roots == {'schema_version': 'enterprise-role-skill-roots/v2',
                'basis': 'hermes_profile_layout', 'status': 'layout_candidate',
                'roots': [{'kind': 'profile_skills',
                           'locator_sha256': hashlib.sha256(str(profile / 'skills').encode()).hexdigest()}]}
            for suffix, version in (
                ('skill-installation-sources', 'enterprise-role-skill-sources-view/v2'),
                (f'configuration-observations/{snapshot["observation_id"]}/skill-installation-sources',
                 'enterprise-role-skill-snapshot-comparison/v2'),
            ):
                comparison = api(prefix + f'/agents/{asset_id}/{suffix}')
                assert comparison['schema_version'] == version
                assert comparison['status'] == 'historical_comparison'
                assert comparison['next_cursor'] is None
                assert comparison['items'] == []
                assert comparison['effective_permissions'] is None
                api(prefix + f'/agents/{asset_id}/{suffix}', custom=other_headers, expected=404)
            checks['native_hermes_v2_provenance_history_and_layout_readback'] = True
            if args.skill_sources:
                checks['unstaged_unsigned_skill_collector_denied_without_upload_or_completed_receipt'] = True
            if args.consent:
                assert next(s for s in status['scans'] if s['id'] == denied_task)['status'] == 'failed'
                audit_headers = {**headers, 'X-Dev-Roles': headers['X-Dev-Roles'] + ',auditor'}
                events = api(prefix + '/audit-events?action=edge.task.receipt', custom=audit_headers)
                denied_event = next(e for e in events if e['resource_id'] == denied_task)
                assert denied_event['summary']['error_code'] == 'discovery_scope_denied'
                assert denied_event['summary']['candidate_count'] == 0
                assert denied_event['summary']['evidence_count'] == 0
                checks['signed_out_of_scope_task_denied_and_audited'] = True
            # This scenario checks online denial, not the management revoke API.
            # Inject revocation through an owner-process fixture in its isolated DB.
            revoke = subprocess.run([str(ROOT / 'apps/control-api/.venv/bin/python'), '-c',
                ('from app.db import init_db, session_scope; from app.config import load_settings\n'
                'from app.models import EdgeAgent, utcnow\n'
                'init_db(load_settings())\n'
                'with session_scope() as s:\n'
                 ' for device in s.query(EdgeAgent).all(): device.revoked_at = utcnow()\n')],
                cwd=ROOT / 'apps/control-api', env=env, capture_output=True, timeout=15, check=False)
            assert revoke.returncode == 0, 'revocation fixture failed'
            api('/edge/v1/heartbeat', {'version': 'fixture'}, custom=device_headers, expected=401)
            api('/edge/v1/tasks', custom=device_headers, expected=401)
            api('/edge/v1/batches', {}, custom=device_headers, expected=401)
            checks['revoked_device_rejected_online_after_fixture_revocation'] = True
            result['passed'] = True
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()  # Only this harness's isolated fixture processes.
                    proc.wait(timeout=5)
            result['fixture_processes_stopped'] = all(p.poll() is not None for p in processes)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open('x') as output:
                output.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()
