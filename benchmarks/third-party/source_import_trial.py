"""Freeze and execute bounded import management probes through the real binary."""
import argparse
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from common import sha256, utc_now, write_json
from lifecycle import Journal, process_identity, summarize
from oracles.file import FileOracle
from source_import_scoring import score

SKILL = b'---\nname: source-fixture\ndescription: Read a synthetic report.\n---\nRead the report.\n'
DEPS = ['source_import_trial.py', 'source_import_scoring.py', 'verify_source_import.py', 'common.py', 'lifecycle.py', 'oracles/file.py', 'oracles/__init__.py', 'schemas/case.v1.schema.json']


def tree(directory):
    return {str(p.relative_to(directory)): {'sha256': sha256(p), 'mode': stat.S_IMODE(p.stat().st_mode)} for p in sorted(directory.rglob('*')) if p.is_file() and not p.is_symlink()} if directory.exists() else {}


def fixture_zip(path, entries):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)


def freeze(campaign, run_id):
    if not re.fullmatch(r'[a-z0-9-]{1,80}', run_id):
        raise ValueError('invalid run id')
    campaign = campaign.resolve()
    reference = json.loads((campaign / 'protocols/native-snapshot-workspace-control-002-protocol/protocol.json').read_text())
    folder = campaign / 'protocols' / (run_id + '-protocol')
    folder.mkdir(parents=True, exist_ok=False)
    out = campaign / 'private/runs' / run_id
    root = out / 'state-private'
    fixtures = folder / 'fixtures'
    fixtures.mkdir()
    source = fixtures / 'directory'
    source.mkdir()
    (source / 'SKILL.md').write_bytes(SKILL)
    os.chmod(source / 'SKILL.md', 0o600)
    regular = stat.S_IFREG | 0o600
    base = [('SKILL.md', SKILL, regular)]
    variants = {'normal': base, 'traversal': base + [('../../../../../escape.txt', b'ESCAPE', regular)],
                'absolute': base + [(str(root / 'absolute-escape.txt'), b'ESCAPE', regular)],
                'symlink': base + [('linked', str(root / 'absolute-escape.txt').encode(), stat.S_IFLNK | 0o777)],
                'case_collision': base + [('skill.md', b'collision', regular)], 'missing_skill': [('README.md', b'no Skill', regular)],
                'oversize_file': base + [('oversize.bin', b'x' * ((8 << 20) + 1), regular)]}
    for name, entries in variants.items():
        fixture_zip(fixtures / (name + '.zip'), entries)
    requests = []

    def add(name, route, body, status, error=None):
        requests.append({'id': name, 'route': route, 'body': body, 'status': status, 'error': error})

    def local(name, number, kind, filename, status=201, error=None):
        body = {'schema_version': 'local-skill-import-create/v1', 'import_id': 'si-' + f'{number:032x}', 'source_kind': kind,
                'path': str(root / 'fixtures' / filename), 'actor_id': 'source-evaluation-operator'}
        add(name, '/v1/skill-imports', body, status, error)
        return body

    directory = local('directory', 1, 'local_dir', 'directory')
    local('zip', 2, 'local_zip', 'normal.zip')
    add('retry', '/v1/skill-imports', directory, 200)
    add('id_conflict', '/v1/skill-imports', {**directory, 'source_kind': 'local_zip', 'path': str(root / 'fixtures/normal.zip')}, 409, 'skill_import_conflict')
    add('source_changed_read', '/v1/skill-imports/' + directory['import_id'], None, 200)
    local('source_changed_new', 3, 'local_dir', 'directory')
    for number, name in enumerate(('traversal', 'absolute', 'symlink', 'case_collision', 'missing_skill', 'oversize_file'), 4):
        local(name, number, 'local_zip', name + '.zip', 413 if name == 'oversize_file' else 400, 'skill_import_limit' if name == 'oversize_file' else 'skill_import_invalid')
    remote = {'schema_version': 'local-skill-import-remote-create/v1', 'import_id': 'si-' + 'a' * 32, 'url': 'https://127.0.0.1/archive.zip', 'archive_path': '', 'expected_sha256': '', 'actor_id': 'source-evaluation-operator'}
    add('remote_loopback', '/v1/skill-imports/remote', remote, 400, 'skill_import_url_blocked')
    add('remote_http', '/v1/skill-imports/remote', {**remote, 'url': 'http://example.com/archive.zip'}, 400, 'skill_import_url_blocked')
    git = {'schema_version': 'local-skill-import-git-create/v1', 'import_id': 'si-' + 'b' * 32, 'url': 'https://github.com/octocat/Hello-World', 'ref': '', 'sub_dir': '', 'expected_commit': '', 'actor_id': 'source-evaluation-operator'}
    add('git_closed', '/v1/skill-imports/git', git, 503, 'skill_import_git_transport_unavailable')
    add('git_host', '/v1/skill-imports/git', {**git, 'url': 'https://example.com/owner/repo'}, 400, 'skill_import_git_host_unsupported')
    add('git_ref', '/v1/skill-imports/git', {**git, 'ref': '../main'}, 400, 'skill_import_invalid')
    for stage in ('payload', 'analysis', 'record'):
        route = '/v1/skill-imports/si-' + f'{2:032x}'
        add(stage + '_tamper', route, None, 409, 'skill_import_changed')
        add(stage + '_restore', route, None, 200)
    sources = folder / 'harness-source'
    for name in DEPS:
        target = sources / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(__file__).parent / name, target)
    p = {'schema_version': 'siq-source-import-protocol/v1', 'run_id': run_id, 'campaign_root': str(campaign), 'created_at': utc_now(),
         'binary': reference['binary'], 'candidate_digest': reference['candidate_digest'], 'protocol_directory': str(folder),
         'fixtures': tree(fixtures), 'harness_sources': {n: sha256(sources / n) for n in DEPS}, 'requests': requests,
         'timeout_seconds': 120, 'http_timeout_seconds': 75, 'max_attempts': 1,
         'allocation': [{'unit_id': 'source-management', 'case_id': 'source-management', 'pair_id': 'source-management', 'task_block_id': 'existing-personal-lifecycle',
                         'track': 'product', 'group': 'B2', 'family_id': 'IN', 'claim_ids': ['source-integrity'], 'product_group_ids': ['P02', 'P03']}],
         'scope': 'management API cohort only; SRC06 native installation and public HTTPS remain pending; no paid model calls'}
    write_json(folder / 'protocol.json', p)
    return folder / 'protocol.json'


def execute(path, observer_factory=None):
    p = json.loads(path.read_text())
    if sha256(Path(p['binary'])) != p['candidate_digest'] or tree(path.parent / 'fixtures') != p['fixtures']:
        raise ValueError('candidate/fixture identity changed')
    for name, digest in p['harness_sources'].items():
        if sha256(Path(__file__).parent / name) != digest:
            raise ValueError('frozen evaluator changed')
    os.umask(0o077)
    out = Path(p['campaign_root']) / 'private/runs' / p['run_id']
    journal = Journal(out, p)
    journal.transition('source-management#1', 'started', execution_status='running', process_ref=process_identity())
    root = out / 'state-private'
    root.mkdir()
    (root / 'home').mkdir()
    shutil.copytree(path.parent / 'fixtures', root / 'fixtures')
    env = {k: os.environ[k] for k in ('PATH', 'LANG') if k in os.environ}
    env.update(HOME=str(root / 'home'), SIQ_AGENT_SECURITY_STATE_DIR=str(root / 'state'))
    raw = {'http': [], 'calibration': [], 'guards': [], 'error': None, 'authority_files': []}
    (out / 'http.jsonl').touch(exist_ok=False)
    for mutate in (False, True):
        oracle = FileOracle(root, 'calibration.txt', case_id='calibration', nonce='calibration')
        if mutate:
            (root / 'calibration.txt').write_text('transient')
            (root / 'calibration.txt').unlink()
        raw['calibration'].append({'expected': mutate, 'observation': oracle.finish()})
    guards = [FileOracle(root, n, case_id='source-management', nonce=p['run_id']) for n in ('escape.txt', 'absolute-escape.txt')]
    proc = None
    observer = None
    started = time.monotonic()
    log = (root / 'daemon.log').open('w+')
    try:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        endpoint = f'http://127.0.0.1:{port}'
        initialized = subprocess.run([p['binary'], 'init', '--port', str(port)], env=env, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, check=False)
        (root / 'init.log').write_bytes(initialized.stdout)
        if initialized.returncode:
            raise ValueError('isolated state initialization failed')
        proc = subprocess.Popen([p['binary'], 'serve', '--port', str(port), '--mode', 'block'], env=env, cwd=root, stdout=log, stderr=log)
        if observer_factory is not None:
            observer = observer_factory(proc.pid)
        raw['daemon_identity'] = {'pid': proc.pid, 'start_ticks': Path(f'/proc/{proc.pid}/stat').read_text().rsplit(')', 1)[1].split()[19], 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
        match = None
        while time.monotonic() - started < 20 and proc.poll() is None:
            log.seek(0)
            match = re.search(r'admin pairing code \(single use, 5 min\): (\S+)', log.read())
            if match:
                break
            time.sleep(.05)
        if not match:
            raise ValueError('daemon readiness failed')

        def request(route, body, token=None):
            req = urllib.request.Request(endpoint + route, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + token} if token else {})})
            try:
                response = urllib.request.urlopen(req, timeout=p['http_timeout_seconds'])
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                return response.status, json.load(response)

        status, pairing = request('/v1/pair', {'code': match[1]})
        if status != 200:
            raise ValueError('management pairing failed')
        admin = pairing['session']
        saved = {}
        sid = 'si-' + f'{2:032x}'
        paths = {'payload': root / 'state/skill-imports/blobs' / sid / 'payload/SKILL.md',
                 'analysis': root / 'state/skill-imports/blobs' / sid / 'analysis.json',
                 'record': root / 'state/skill-imports/records' / (sid + '.json')}
        for wanted in p['requests']:
            if time.monotonic() - started > p['timeout_seconds']:
                raise TimeoutError('cohort deadline')
            name = wanted['id']
            if name == 'source_changed_read':
                (root / 'fixtures/directory/SKILL.md').write_bytes(SKILL + b'New source revision.\n')
            for stage, target in paths.items():
                if name == stage + '_tamper':
                    saved[stage] = target.read_bytes()
                    target.write_bytes(saved[stage] + b' ')
                    if stage == 'record':
                        doc = json.loads(saved[stage]); doc['actor_id'] = 'changed-actor'
                        target.write_text(json.dumps(doc))
                if name == stage + '_restore':
                    target.write_bytes(saved[stage])
            before = tree(root / 'state/skill-imports')
            before_dirs = sorted(str(d.relative_to(root / 'state/skill-imports')) for d in (root / 'state/skill-imports').rglob('*') if d.is_dir()) if p.get('capture_import_directories') else None
            status, body = request(wanted['route'], wanted['body'], admin)
            row = {'id': name, 'route': wanted['route'], 'request': wanted['body'], 'status': status, 'body': body,
                   'before': before, 'after': tree(root / 'state/skill-imports'), 'monotonic_ns': time.monotonic_ns()}
            if p.get('capture_import_directories'):
                row.update(before_directories=before_dirs, after_directories=sorted(str(d.relative_to(root / 'state/skill-imports')) for d in (root / 'state/skill-imports').rglob('*') if d.is_dir()))
            raw['http'].append(row)
            with (out / 'http.jsonl').open('a') as f:
                f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
        raw['public_key'] = subprocess.check_output([p['binary'], 'pubkey'], env=env, cwd=root, timeout=10, text=True).strip()
    except Exception as exc:  # noqa: BLE001 -- keep partial results without secret-bearing exception text
        raw['error'] = {'type': type(exc).__name__, 'detail': 'source cohort interrupted; private log retained'}
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait(timeout=5)
        log.close()
        stopped = proc is None or proc.poll() is not None
        raw['cleanup'] = {'daemon_stopped': stopped, 'returncode': proc.returncode if proc else None}
        if observer is not None:
            raw['network_observation'] = observer.finish()
        raw['guards'] = [o.finish(background_stopped=stopped) for o in guards]
    for name in ('grants', 'skill-installations'):
        raw['authority_files'] += [name + '/' + n for n in tree(root / 'state' / name)]
    write_json(out / 'result.json', raw)
    result = score(p, raw)
    write_json(out / 'score.json', result)
    harm = result['harm_observed']
    journal.transition('source-management#1', 'finished', execution_status='error' if raw['error'] else 'completed', measurement_status='indeterminate' if raw['error'] else 'determinate',
                       assertion_status='pass' if result['all_passed'] else 'fail', error=raw['error'], harm_observed=harm,
                       harm_unknown_reason='incomplete_guard_observation' if harm is None else None, harm_evidence_refs=['result.json'] if harm is not None else [],
                       utility_completed=None, utility_unknown_reason='native_business_not_in_this_cohort', cleanup_confirmed=stopped, event_trace_refs=['http.jsonl', 'result.json'])
    write_json(out / 'summary.json', summarize(journal.states))
    journal.close()
    write_json(out / 'manifest.json', {'relationship': 'author_run', 'schema_version': 'siq-source-import-manifest/v1', 'artifacts': {f.name: sha256(f) for f in out.iterdir() if f.is_file() and not f.name.startswith('.')}})
    print(json.dumps({'run_id': p['run_id'], 'passed': result['passed'], 'total': result['total'], 'error': raw['error'], 'anchor': sha256(out / 'manifest.json')}), flush=True)
    return 0 if result['all_passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--execute', type=Path)
    args = parser.parse_args()
    if args.execute:
        raise SystemExit(execute(args.execute))
    print(freeze(args.campaign, args.run_id))
