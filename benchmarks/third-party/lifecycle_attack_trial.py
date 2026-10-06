"""Freeze a real Hermes install/update/remove journey with independent raw observations."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from common import safe_path, sha256, utc_now, write_json
from lifecycle import Journal, process_identity, summarize
from lifecycle_attack_scoring import expected_checks, score
from lifecycle_attacks import run as run_attacks
from process_resources import identity, members


def host_identity(root, cli):
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '--', '*.py', 'pyproject.toml', 'uv.lock'], text=True).splitlines()
    return {'root': str(root), 'head': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
            'source_hashes': {n: sha256(root / n) for n in sorted(set(names)) if (root / n).is_file()},
            'cli': str(cli), 'cli_sha256': sha256(cli), 'python_sha256': sha256(root / 'venv/bin/python'),
            'scope': 'public installed Hermes CLI; current checkout identity, not upstream release certification'}


def execute(path):
    p = json.loads(path.read_text())
    for name, digest in p['harness_sources'].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError('native evaluator source changed')
    candidate = Path(p['candidate_root'])
    for name, digest in p['candidate_sources'].items():
        if sha256(safe_path(candidate, name)) != digest:
            raise ValueError('candidate fixture source changed')
    if sha256(Path(p['binary'])) != p['candidate_digest'] or host_identity(Path(p['host']['root']), Path(p['host']['cli'])) != p['host']:
        raise ValueError('native host or product identity changed')
    if os.getpgrp() != os.getpid():
        os.setsid()
    os.umask(0o077)
    out = Path(p['campaign_root']) / 'private/runs' / p['run_id']
    journal = Journal(out, p)
    root = out / 'state-private'
    root.mkdir(mode=0o700)
    spec = importlib.util.spec_from_file_location('native_update_fixture', candidate / 'scripts/personal-experience/r04-hermes-native-update-smoke.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    rows, model_rows, commands, tokens = [], [], [], set()
    lock = threading.Lock()
    phase = 'setup'

    def scrub(value):
        if isinstance(value, dict):
            return {k: '[REDACTED]' if k in ('code', 'session', 'nonce', 'token', 'credential', 'api_key') and isinstance(v, str) else scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            for token in tokens:
                if token:
                    value = value.replace(token, '[REDACTED]')
        return value

    def append(name, value, collection):
        with lock:
            value = scrub({'sequence': len(collection) + 1, 'phase': phase, 'monotonic_ns': time.monotonic_ns(), **value})
            collection.append(value)
            with (out / name).open('a') as stream:
                stream.write(json.dumps(value, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

    class Harness(fixture.Harness):
        final_receipts = None
        start_count = 0

        def start(self):
            super().start()
            self.start_count += 1
            write_json(out / f'daemon-start-{self.start_count}.json', {'daemon': identity(self.proc.pid), 'command_sha256': hashlib.sha256(Path(f'/proc/{self.proc.pid}/cmdline').read_bytes()).hexdigest()})

        def effects(self):
            target = Path(self.env['HERMES_HOME']) / 'skills/intent-fixture/SKILL.md'
            paths = {'target': target, 'profile': Path(self.env['HERMES_HOME']) / 'config.yaml', 'other_profile': self.root / 'hermes/config.yaml', 'source_v2': self.root / 'fixture-skill-v2/SKILL.md', 'unrelated_hook': Path(self.env['HERMES_HOME']) / 'plugins/third-party-owned/keep.txt', 'preserved_notes': self.root / 'preserved-user-notes.txt'}
            if getattr(self, 'source_identity', False):
                paths['source_clone'] = self.root / 'fixture-skill-clone/SKILL.md'
            return {k: sha256(f) if f.is_file() else None for k, f in paths.items()} | {'workspace': {str(f.relative_to(self.workspace)): sha256(f) for f in self.workspace.rglob('*') if f.is_file() and not f.is_symlink()}, 'target_tree': {str(f.relative_to(target.parent)): sha256(f) for f in target.parent.rglob('*') if f.is_file() and not f.is_symlink()}}

        def api(self, route, body=None, *, token=None, expected=200):
            bearer = self.admin if token is None else token
            if bearer:
                tokens.add(bearer)
            before = self.effects()
            req = urllib.request.Request(self.endpoint + route, headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + bearer} if bearer else {})}, data=json.dumps(body).encode() if body is not None else None)
            try:
                response = urllib.request.urlopen(req, timeout=10)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                payload = json.loads(response.read())
                for field in ('session', 'code', 'token', 'credential'):
                    if isinstance(payload.get(field), str):
                        tokens.add(payload[field])
                proof = {}
                if getattr(self, 'source_identity', False):
                    proof = {'request_nonce_sha256': hashlib.sha256(body['nonce'].encode()).hexdigest() if body and body.get('nonce') else None,
                             'response_nonce_sha256': hashlib.sha256(payload['challenge']['nonce'].encode()).hexdigest() if payload.get('challenge', {}).get('nonce') else None}
                append('http.jsonl', {'path': route, 'method': 'POST' if body is not None else 'GET', 'request': body,
                       **proof, 'status': response.status, 'expected_status': expected, 'response': payload, 'before': before, 'after': self.effects()}, rows)
                if response.status != expected:
                    raise ValueError('native fixture HTTP contract mismatch')
                return payload

        def command(self, argv, **kwargs):
            output = super().command(argv, **kwargs)
            append('commands.jsonl', {'argv': [str(v) for v in argv], 'stdout': output, 'exit_code': 0}, commands)
            return output

        def _native_read(self, call_id, marker, skill_name):
            nonlocal phase
            phase = call_id
            result = super()._native_read(call_id, marker, skill_name)
            append('native-results.jsonl', {'call_id': call_id, 'receipt': result, 'effects': self.effects()}, native_results)
            phase = 'update' if call_id == 'r04-v1-read' else 'removal'
            return result

        def stop(self):
            if self.proc is not None and self.proc.poll() is None:
                try:
                    self.final_receipts = self.receipts()
                except (OSError, ValueError, RuntimeError):
                    pass
            super().stop()

    args = SimpleNamespace(binary=Path(p['binary']), hermes_cli=Path(p['host']['cli']), installer_managed_profile=True,
                           remove_installed_skill=False, legacy_binary=None, raw_expiry_seconds=0, raw_dual_task=False)
    h = Harness(root, args)
    h.restart_mode = p.get("restart_mode", "graceful")
    h.source_integrity = p.get("source_integrity", False)
    h.source_identity = p.get("source_identity", False)
    hook = Path(h.env['HERMES_HOME']) / 'plugins/third-party-owned/keep.txt'
    hook.parent.mkdir(parents=True)
    hook.write_text('UNRELATED_PROFILE_FILE\n')

    def set_phase(name):
        nonlocal phase
        phase = name

    faults = []

    def inject(label, path, action):
        before = h.effects()
        object_before = sha256(path) if path.is_file() else None
        action()
        append('faults.jsonl', {'label': label, 'path': str(path), 'object_before': object_before, 'object_after': sha256(path) if path.is_file() else None, 'before': before, 'after': h.effects()}, faults)

    h.eval_phase, h.inject = set_phase, inject
    marker = 'NATIVE_READ_' + secrets.token_hex(24)
    (h.workspace / 'company-a/report.txt').write_text('fixture-visible-company-a\n' + marker + '\n')
    write_json(out / 'gold.json', {'read_marker': marker, 'restart_mode': h.restart_mode, 'source_integrity': h.source_integrity, 'source_identity': h.source_identity, 'report_sha256': sha256(h.workspace / 'company-a/report.txt'), 'expected_calls': ['r04-v1-read'], 'denied_calls': ['attack-expanded-write', 'attack-approved-candidate-write'], 'model': 'loopback deterministic tool-selection fixture', 'scope': 'real native tool invocation, not generative model safety'})
    native_results = []
    original_server = fixture.r01.ThreadingHTTPServer

    def recording_server(address, handler):
        class Recording(handler):
            def do_POST(self):
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2_000_000:
                    self.send_error(413)
                    return
                raw = self.rfile.read(size)
                append('model-requests.jsonl', {'path': self.path, 'body': json.loads(raw)}, model_rows)
                self.rfile = io.BytesIO(raw)
                super().do_POST()
        return original_server(address, Recording)

    fixture.r01.ThreadingHTTPServer = recording_server
    original_run = subprocess.run

    def native_run(argv, **kwargs):
        result = original_run(argv, **kwargs)
        append('native-processes.jsonl', {'argv': [str(v) for v in argv], 'exit_code': result.returncode,
               'stdout': (result.stdout or b'').decode(errors='replace'), 'stderr': (result.stderr or b'').decode(errors='replace')}, native_processes)
        return result

    fixture.r01.subprocess = SimpleNamespace(run=native_run)
    native_processes = []
    error, report = None, None
    journal.transition('lifecycle-attacks#1', 'started', execution_status='running', process_ref=process_identity())
    try:
        h.build()
        h.start()
        write_json(out / 'daemon.json', {'daemon': identity(h.proc.pid), 'command_sha256': hashlib.sha256(Path(f'/proc/{h.proc.pid}/cmdline').read_bytes()).hexdigest()})
        h.setup_authority()
        report = run_attacks(h, out)
        write_json(out / 'legacy-report.json', report)
    except Exception as exc:  # noqa: BLE001 -- preserve partial native execution and redact secrets
        error = {'type': type(exc).__name__, 'detail': scrub(str(exc))[:3000]}
    finally:
        h.stop()
    public_key = h.command([str(h.binary), 'pubkey']).strip()
    write_json(out / 'receipts.json', {'receipts': h.final_receipts or [], 'public_key': public_key})
    write_json(out / 'effects-final.json', h.effects())
    write_json(out / 'host-after.json', host_identity(Path(p['host']['root']), Path(p['host']['cli'])))
    cleanup = {'remaining_group_members': members(os.getpid(), exclude=(os.getpid(),)), 'daemon_stopped': h.proc is None}
    write_json(out / 'cleanup.json', cleanup)
    result = score(json.loads((out / 'gold.json').read_text()), rows, model_rows, h.final_receipts or [], h.effects(), json.loads((out / 'host-after.json').read_text()) == p['host'], cleanup, json.loads((out / 'crash.json').read_text()) if (out / 'crash.json').exists() else None)
    write_json(out / 'score.json', result)
    complete = error is None and set(result['checks']) == expected_checks(h.restart_mode == 'sigkill', h.source_integrity, h.source_identity) and not cleanup['remaining_group_members']
    status = 'fail' if any(v is False for v in result['checks'].values()) else 'pass' if complete else 'inconclusive'
    journal.transition('lifecycle-attacks#1', 'finished', execution_status='error' if error else 'completed',
                       measurement_status='determinate' if complete else 'indeterminate', assertion_status=status, error=error, tool_executed=True,
                       harm_observed=result['harm_observed'], harm_unknown_reason='native_journey_incomplete' if result['harm_observed'] is None else None,
                       harm_evidence_refs=['http.jsonl', 'effects-final.json'] if result['harm_observed'] is not None else [],
                       utility_completed=result['utility_completed'], utility_unknown_reason='native_read_pair_incomplete' if result['utility_completed'] is None else None,
                       utility_evidence_refs=['model-requests.jsonl', 'gold.json'] if result['utility_completed'] is not None else [], cleanup_confirmed=not cleanup['remaining_group_members'],
                       oracle={'source': 'native_model_requests_and_file_hashes', 'healthy': complete, 'coverage': 'full' if complete else 'partial',
                               'window_start': None, 'window_end': None, 'materials': ['gold.json', 'effects-final.json']},
                       event_trace_refs=['cleanup.json'])
    summary = summarize(journal.states)
    with (out / 'cases.jsonl').open('x') as stream:
        for row in journal.states.values():
            stream.write(json.dumps(row) + '\n')
    journal.close()
    write_json(out / 'summary.json', summary)
    names = [f.name for f in out.iterdir() if f.is_file()]
    write_json(out / 'manifest.json', {'schema_version': 'siq-lifecycle-attacks-manifest/v1', 'relationship': 'author_run',
               'artifacts': {name: sha256(out / name) for name in names}})
    print(json.dumps({**summary, 'legacy_checks': len(report['checks']) if report else 0, 'error_type': error['type'] if error else None,
                      'http': len(rows), 'model_requests': len(model_rows), 'manifest_sha256': sha256(out / 'manifest.json')}), flush=True)
    return summary['outcome_exit_code']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', type=Path)
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--restart-mode', choices=('graceful', 'sigkill'), default='sigkill')
    parser.add_argument('--candidate-root', type=Path)
    parser.add_argument('--source-integrity', action='store_true')
    parser.add_argument('--source-identity', action='store_true')
    args = parser.parse_args()
    if args.execute:
        return execute(args.execute)
    if not args.campaign or not args.run_id or not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', args.run_id):
        raise ValueError('fresh run ID required')
    campaign = args.campaign.resolve()
    p = json.loads((campaign / 'protocols/management-http-003-protocol/protocol.json').read_text())
    if args.candidate_root:
        p['candidate_root'] = str(args.candidate_root.resolve())
    candidate = Path(p['candidate_root'])
    for f in (candidate / 'scripts/personal-experience').glob('*.py'):
        p['candidate_sources'][str(f.relative_to(candidate))] = sha256(f)
    root = campaign / 'protocols' / (args.run_id + '-protocol')
    root.mkdir(parents=True, exist_ok=False)
    names = ['lifecycle_attack_trial.py', 'lifecycle_attack_scoring.py', 'lifecycle_attacks.py', 'source_identity_attacks.py', 'common.py', 'lifecycle.py', 'process_resources.py', 'schemas/case.v1.schema.json']
    for name in names:
        target = root / 'harness-source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parent / name, target)
    p.update(run_id=args.run_id, operation='lifecycle_attacks', frozen_at=utc_now(), host=host_identity(Path('/home/maoyd/siq/hermes-agent'), Path('/home/maoyd/.local/bin/hermes').resolve()),
             harness_sources={name: sha256(root / 'harness-source' / name) for name in names},
             allocation=[{'unit_id': 'lifecycle-attacks', 'case_id': 'P04.P05.hermes-native', 'pair_id': 'native-lifecycle', 'task_block_id': 'native-lifecycle',
                          'track': 'B', 'group': 'B2', 'family_id': 'P04', 'claim_ids': ['C6'], 'product_group_ids': ['P04', 'P05']}],
             limits={'http_seconds': 10, 'native_process_seconds': 90, 'native_model_run_budget': 45, 'model': 'loopback_fixture_no_paid_calls',
                     'scope': 'owned HOME/profile; real local Hermes public CLI; no same-UID isolation claim'})
    p.pop('signed_intent_verification', None)
    p['independent_scoring'] = True
    p['restart_mode'] = args.restart_mode
    p['source_integrity'] = args.source_integrity
    p['source_identity'] = args.source_identity
    p['post_remove_native'] = False
    write_json(root / 'protocol.json', p)
    write_json(root / 'local-anchor.json', {'sha256': sha256(root / 'protocol.json')})
    result = subprocess.run([sys.executable, str(root / 'harness-source/lifecycle_attack_trial.py'), '--execute', str(root / 'protocol.json')], capture_output=True, text=True, check=False)
    write_json(campaign / 'reports' / (args.run_id + '-execution.json'), {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    print(result.stdout, end='')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
