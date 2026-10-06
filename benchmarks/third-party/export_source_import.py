"""Verify and export an explicit allowlist; never copy private daemon state."""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import sha256, write_json
from lifecycle import process_state


def export(campaign, run_id, anchor, allow_failed=False):
    if not re.fullmatch(r'[a-z0-9-]{1,80}', run_id):
        raise ValueError('invalid run id')
    campaign = campaign.resolve()
    run = campaign / 'private/runs' / run_id
    protocol = json.loads((run / 'protocol.json').read_text())
    name = {'remote-source-import': 'verify_remote_source_import.py', 'source-budget': 'verify_source_budget.py', 'source-path-slots': 'verify_source_limits.py'}.get(protocol.get('profile'), 'verify_source_import.py')
    verifier = campaign / 'protocols' / (run_id + '-protocol') / 'harness-source' / name
    checked = subprocess.run([sys.executable, str(verifier), str(run), '--expected-manifest-sha256', anchor], capture_output=True, text=True, timeout=30, check=True)
    verification = json.loads(checked.stdout)
    if not verification['all_passed'] and not allow_failed:
        raise ValueError('complete passing export expected; preserve failed private run separately')
    names = ('protocol.json', 'journal.jsonl', 'http.jsonl', 'result.json', 'score.json', 'summary.json', 'manifest.json')
    private = run / 'state-private'
    secrets = set()
    for p in (private / 'state').rglob('*'):
        if p.is_file() and ('token' in p.name or 'seed' in p.name):
            value = p.read_bytes().strip()
            if len(value) >= 16:
                secrets.add(value)
    log = (private / 'daemon.log').read_text()
    for match in re.finditer(r'admin pairing code \(single use, 5 min\): (\S+)', log):
        secrets.add(match[1].encode())
    for name in names:
        content = (run / name).read_bytes()
        if any(value in content for value in secrets) or b'Bearer ' in content or b'PRIVATE KEY-----' in content:
            raise ValueError('private material detected; export stopped')
    result = json.loads((run / 'result.json').read_text())
    environment = None
    if protocol.get('network_environment') == 'container_doh_dns':
        environment_path = campaign / 'reports' / (run_id + '-container-environment.json')
        environment = json.loads(environment_path.read_text())
        if environment['run_id'] != run_id or environment['image_id'] != protocol['container_image'] or not all(environment.get(k) is True for k in ('owned_containers_absent', 'owned_network_absent', 'host_processes_absent')):
            raise ValueError('container cleanup not verified')
        state = 'container_namespace_pid; outer container/network cleanup verified separately'
    else:
        state = process_state(result['daemon_identity'])
        if state == 'alive':
            raise ValueError('daemon still alive')
    target = campaign / 'data' / run_id
    target.mkdir(parents=True, exist_ok=False)
    for name in names:
        shutil.copy2(run / name, target / name)
    if sha256(target / 'manifest.json') != anchor:
        raise ValueError('export identity differs')
    review = {'verified': verification, 'exported_files': list(names), 'manifest_sha256': anchor,
              'known_private_values_checked': len(secrets), 'private_value_matches': 0, 'recorded_daemon_state': state,
              'container_environment_sha256': sha256(environment_path) if environment else None,
              'scope': 'exact allowlist export, author-run evidence, private state and daemon logs excluded'}
    write_json(campaign / 'reports' / (run_id + '-export-review.json'), review)
    return review


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--allow-failed', action='store_true')
    args = parser.parse_args()
    print(json.dumps(export(args.campaign, args.run_id, args.expected_manifest_sha256, args.allow_failed)))
