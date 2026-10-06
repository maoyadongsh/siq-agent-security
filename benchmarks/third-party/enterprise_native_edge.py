"""Native Edge + native Hermes connector against the same candidate API."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from common import clean_environment, sha256, write_json

CASES = {'native_enrollment': 200, 'native_scan': 200, 'native_scan_status': 200, 'native_candidates': 200, 'native_evidence': 200}
ASSERTIONS = ['native_cli_success', 'native_private_state', 'native_device_binding', 'native_scan_delivered', 'native_asset_evidence', 'native_source_unchanged']
ASSET_NAME = 'enterprise-native-fixture'
CONFIG = b'model:\n  default: no-model-call\nprovider: local\nplatform_toolsets:\n  - name: file\n'


def evaluate(o):
    asset = o['asset']
    return {
        'native_cli_success': o['register']['exit_code'] == 0 and o['tasks']['exit_code'] == 0,
        'native_private_state': o['state_mode'] == 0o600,
        'native_device_binding': len(o['device_rows']) == 1 and o['device_rows'][0][1] == o['device_identity'] and o['device_rows'][0][2] == o['environment_id'] and o['device_rows'][0][3] == o['secret_sha256'],
        'native_scan_delivered': o['scan_status']['id'] == o['scan']['task_id'] and o['scan_status']['status'] == 'delivered' and o['scan_status']['payload']['target_device_identity'] == o['device_identity'] and o['scan_status']['payload']['scope'] == o['scope'],
        'native_asset_evidence': asset['name'] == ASSET_NAME and asset['framework'] == 'hermes' and bool(o['asset_evidence_ids']) and bool(o['evidence_rows']) and set(o['asset_evidence_ids']) == {r[0] for r in o['evidence_rows']} == {e['id'] for e in o['evidence']} and all(r[1] == o['device_identity'] and r[2] == o['source_before'] and r[3] for r in o['evidence_rows']),
        'native_source_unchanged': o['source_before'] == o['source_after'] == hashlib.sha256(CONFIG).hexdigest(),
    }


def run(request, sql, check, events, out, auth, environment, base_url, build):
    o = {}

    def record(name, value):
        o[name] = value
        events.add('native_enterprise_observation', name=name, value=value)
        return value

    root = Path(tempfile.mkdtemp(prefix='siq-enterprise-edge-'))
    record('ephemeral_root', str(root))
    home = root / 'home'
    profile = home / '.hermes/profiles' / ASSET_NAME
    profile.mkdir(parents=True)
    source = profile / 'config.yaml'
    source.write_bytes(CONFIG)
    binaries = root / 'bin'
    binaries.mkdir()
    for item in build['builds']:
        target = binaries / ('edge-agent' if item['module'] == 'edge/agent' else 'hermes-connector')
        if sha256(Path(item['binary'])) != item['sha256']:
            raise ValueError('native binary identity changed')
        shutil.copy2(item['binary'], target)
    env = {**clean_environment(), 'HOME': str(home), 'SIQ_EDGE_STATE_DIR': str(root / 'state'), 'SIQ_CONNECTOR_BIN_DIR': str(binaries)}

    def command(name, args, secret=None):
        result = subprocess.run([str(binaries / 'edge-agent'), *args], input=secret, capture_output=True, text=True, timeout=45, env=env, cwd=root, check=False)
        (root / (name + '.stdout')).write_text(result.stdout)
        (root / (name + '.stderr')).write_text(result.stderr)
        return record(name, {'exit_code': result.returncode, 'stdout_sha256': hashlib.sha256(result.stdout.encode()).hexdigest(), 'stderr_sha256': hashlib.sha256(result.stderr.encode()).hexdigest()})

    try:
        enrollment = request('native_enrollment', 'POST', f"/api/v1/environments/{environment['id']}/edge-enrollment", auth, {})
        command('register', ['register', '--control-plane', base_url, '--environment', environment['id'], '--enrollment-code-stdin'], enrollment['code'] + '\n')
        state_path = root / 'state/state.json'
        state = json.loads(state_path.read_text())
        record('state_mode', os.stat(state_path).st_mode & 0o777)
        record('device_identity', state['device_identity'])
        record('environment_id', environment['id'])
        record('secret_sha256', hashlib.sha256(state['secret'].encode()).hexdigest())
        record('device_rows', sql('SELECT id,device_identity,environment_id,secret_hash FROM edge_agent WHERE device_identity=%s', (state['device_identity'],)))
        scope = record('scope', {'roots': [str(profile)], 'include': ['config.yaml'], 'max_files': 10, 'max_bytes': 4096})
        record('source_before', sha256(source))
        scan = record('scan', request('native_scan', 'POST', '/api/v1/scans', auth, {'environment_id': environment['id'], 'connector': 'hermes', 'target_device_identity': state['device_identity'], 'scope': scope}))
        command('tasks', ['tasks'])
        record('scan_status', request('native_scan_status', 'GET', '/api/v1/scans/' + scan['task_id'], auth))
        assets = record('assets', request('native_candidates', 'GET', '/api/v1/candidates', auth))
        asset = record('asset', next(x for x in assets if x['name'] == ASSET_NAME))
        record('asset_evidence_ids', sql('SELECT evidence_ids FROM agent_asset WHERE id=%s', (asset['id'],))[0][0])
        record('evidence', request('native_evidence', 'GET', '/api/v1/agents/' + asset['id'] + '/evidence', auth))
        record('evidence_rows', sql('SELECT evidence_id,collector_id,content_hash,signature FROM evidence WHERE collector_id=%s ORDER BY evidence_id', (state['device_identity'],)))
        record('source_after', sha256(source))
        for name, value in evaluate(o).items():
            check(name, value, {'source': 'native-enterprise-observations.json', 'predicate': name})
    finally:
        shutil.move(str(root), str(out / 'native-edge-private'))
        record('ephemeral_root_removed', not root.exists())
        write_json(out / 'native-enterprise-observations.json', o)
