"""Owned Windows unmarked-to-v2 journey. Review before one actual execution.
Never import or execute this file for static validation; use ast.parse.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time

SOURCE_COMMITS = {
    'old': 'ff99317450784c9563f5b6a2308c98e8262df98d',
    'new': 'b321a5d807e05c6b2d002a856a357711b9202203',
}
MAX_FILE = 128 << 20
MAX_TOTAL = 2 << 30
MAX_ENTRIES = 10000
MAINTENANCE = {'service-control', 'adapter-write', 'client-releases', 'client-snapshots'}
MARKER = 'state-format.json'
JOURNAL = 'state-migration-v2'
HEX = re.compile(r'[0-9a-f]{64}\Z')


class StopJourney(Exception):
    pass


def require(ok, code):
    if not ok:
        raise StopJourney(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path, directory=False):
    """Reject every existing reparse ancestor; no filesystem mutation."""
    path = Path(path)
    require(path.is_absolute(), 'absolute_path_required')
    for item in [path, *path.parents]:
        s = item.lstat()
        require(not (getattr(s, 'st_file_attributes', 0) & 0x400), 'reparse_rejected')
        require(not stat.S_ISLNK(s.st_mode), 'link_rejected')
        if item != path or directory:
            require(stat.S_ISDIR(s.st_mode), 'ordinary_directory_required')
        else:
            require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, 'single_link_file_required')
    return path.lstat()


def read_file(path, limit=MAX_FILE):
    before = ordinary(path)
    require(before.st_size <= limit, 'file_budget_exceeded')
    with path.open('rb') as f:
        opened = os.fstat(f.fileno())
        require(os.path.samestat(before, opened), 'read_identity_changed')
        data = f.read(limit + 1)
    after = ordinary(path)
    require(os.path.samestat(before, after) and len(data) == before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns, 'read_changed')
    return data


def new_json(path, obj):
    ordinary(path.parent, True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def object_json(raw):
    def pairs(items):
        d = {}
        for k, v in items:
            require(k not in d, 'duplicate_json_key')
            d[k] = v
        return d
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
    require(type(value) is dict, 'json_object_required')
    return value


def snapshot(root):
    ordinary(root, True)
    result = {}
    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        ordinary(directory, True)
        for child in sorted(directory.iterdir(), key=lambda x: x.name):
            require(len(result) < MAX_ENTRIES, 'snapshot_entry_budget')
            info = child.lstat()
            isdir = stat.S_ISDIR(info.st_mode)
            ordinary(child, isdir)
            rel = child.relative_to(root).as_posix()
            # Python mode is retained; Go Windows mode is readonly-derived.
            go_mode = (0o444 if getattr(info, 'st_file_attributes', 0) & 1 else 0o666) | (0o111 if isdir else 0)
            row = {'directory': isdir, 'mode': stat.S_IMODE(info.st_mode),
                   'go_mode': go_mode, 'size': 0, 'sha256': ''}
            if isdir:
                pending.append(child)
            else:
                data = read_file(child)
                total += len(data)
                require(total <= MAX_TOTAL, 'snapshot_byte_budget')
                row.update(size=len(data), sha256=digest(data))
            result[rel] = row
    return dict(sorted(result.items()))


def safe_id(value):
    require(type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value), 'invalid_business_id')
    return value


def bytes_equal(a, b):
    # Actual byte comparison, beyond the before/after hash checks.
    sa, sb = ordinary(a), ordinary(b)
    require(sa.st_size == sb.st_size <= MAX_FILE, 'backup_size_mismatch')
    with a.open('rb') as x, b.open('rb') as y:
        require(os.path.samestat(sa, os.fstat(x.fileno())) and os.path.samestat(sb, os.fstat(y.fileno())), 'backup_open_identity')
        while True:
            bx, by = x.read(65536), y.read(65536)
            require(bx == by, 'backup_bytes_mismatch')
            if not bx:
                break
    require(os.path.samestat(sa, ordinary(a)) and os.path.samestat(sb, ordinary(b)), 'backup_final_identity')


class Journey:
    def __init__(self, args):
        require(os.name == 'nt', 'native_windows_required')
        self.root = Path(os.path.abspath(args.private_root))
        ordinary(self.root, True)
        require(not any(self.root.iterdir()), 'fresh_empty_private_root_required')
        self.binary = {'old': Path(os.path.abspath(args.old_binary)), 'new': Path(os.path.abspath(args.new_binary))}
        self.hashes = {'old': args.old_sha256, 'new': args.new_sha256}
        for role in self.binary:
            require(HEX.fullmatch(self.hashes[role]), 'invalid_expected_binary_sha')
            require(self.binary[role].is_relative_to(self.root.parent)
                    and not self.binary[role].is_relative_to(self.root), 'binary_outside_private_build_parent')
            require(digest(read_file(self.binary[role])) == self.hashes[role], 'binary_sha_mismatch')
        self.state = self.root / 'state'
        self.raw = self.root / 'raw'
        self.records = self.root / 'records'
        self.fixture = self.root / 'fixture-skill'
        self.phase = 'setup'
        self.old_closed = False
        self.steps = []
        self.claims = {}
        for name in ['raw', 'records', 'fixture-skill', 'home', 'localappdata', 'appdata', 'tmp']:
            path = self.root / name
            path.mkdir(mode=0o700)
            ordinary(path, True)
        # State itself is created only by the real old CLI.
        systemroot = os.environ.get('SystemRoot') or os.environ.get('SYSTEMROOT')
        require(bool(systemroot), 'systemroot_required')
        self.env = {
            'SystemRoot': systemroot, 'WINDIR': systemroot,
            'PATH': str(Path(systemroot) / 'System32'),
            'USERPROFILE': str(self.root / 'home'), 'HOME': str(self.root / 'home'),
            'APPDATA': str(self.root / 'appdata'), 'LOCALAPPDATA': str(self.root / 'localappdata'),
            'TEMP': str(self.root / 'tmp'), 'TMP': str(self.root / 'tmp'),
            'SIQ_AGENT_SECURITY_STATE_DIR': str(self.state),
        }
        require(set(k for k in self.env if k.startswith(('SIQ_', 'AGENTSHIELD_'))) == {'SIQ_AGENT_SECURITY_STATE_DIR'}, 'environment_policy')
        self.result = {'schema': 'windows-unmarked-migration-journey/v1', 'status': 'partial',
                       'source_commits': SOURCE_COMMITS, 'source_provenance': 'externally verified build record; harness verifies binary SHA only',
                       'binary_sha256': self.hashes, 'platform': 'native_windows',
                       'private_root_acl': 'caller-created and externally verified; this harness checks ordinary empty directory only',
                       'zero_write_semantics': 'equal state snapshots at command boundaries; not a trace proving absence of transient lock I/O',
                       'steps': self.steps, 'claims': self.claims, 'fixture_retained': True,
                       'old_executed_after_migration_started': False, 'siq_service_started': False}

    def save_snapshot(self, label):
        value = snapshot(self.state)
        new_json(self.records / (label + '.snapshot.json'), value)
        return value

    def no_marker(self):
        require(not os.path.lexists(self.state / MARKER), 'old_state_marker_not_absent')

    def command(self, label, role, argv, success=True):
        self.phase = label
        require(not (role == 'old' and self.old_closed), 'old_binary_after_upgrade_prohibited')
        require(digest(read_file(self.binary[role])) == self.hashes[role], 'binary_changed_before_command')
        row = {'label': label, 'binary_role': role, 'command': argv[0], 'spawned': False,
               'expected_exit': 'zero' if success else 'nonzero', 'exit_code': None,
               'timeout': False, 'kill_attempted': False, 'kill_error': None,
               'waited_and_reaped': False, 'wait_error': None, 'validation_complete': False,
               'raw': {}, 'deadline_seconds': 30, 'cleanup_reserve_seconds': 5}
        row['deadline_semantics'] = 'monotonic process wait plus cleanup budget; excludes pre/post hashing and snapshots; no absolute OS-call preemption guarantee'
        self.steps.append(row)
        paths = {s: self.raw / (label + '.' + s + '.bin') for s in ['stdout', 'stderr']}
        started = time.monotonic()
        proc = None
        try:
            with paths['stdout'].open('xb') as out, paths['stderr'].open('xb') as err:
                proc = subprocess.Popen([str(self.binary[role]), *argv], cwd=self.root,
                                        env=self.env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                        close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
                row['spawned'] = True
                try:
                    proc.wait(timeout=max(0.001, started + 25 - time.monotonic()))
                    row['waited_and_reaped'] = True
                except subprocess.TimeoutExpired:
                    row['timeout'] = True
                    row['kill_attempted'] = True
                    try:
                        proc.kill()  # Held process only; never taskkill/tree/unknown PID.
                    except Exception as error:
                        row['kill_error'] = type(error).__name__
                    try:
                        remaining = started + 30 - time.monotonic()
                        require(remaining > 0, 'command_cleanup_budget_exhausted')
                        proc.wait(timeout=remaining)
                        row['waited_and_reaped'] = True
                    except Exception as error:
                        row['wait_error'] = type(error).__name__
                row['exit_code'] = proc.returncode
        except Exception as error:
            row['process_error'] = type(error).__name__
            if proc is not None and not row['waited_and_reaped']:
                if proc.poll() is None:
                    row['kill_attempted'] = True
                    try:
                        proc.kill()
                    except Exception as cleanup_error:
                        row['kill_error'] = type(cleanup_error).__name__
                try:
                    remaining = started + 30 - time.monotonic()
                    require(remaining > 0, 'command_cleanup_budget_exhausted')
                    proc.wait(timeout=remaining)
                    row['waited_and_reaped'] = True
                except Exception as cleanup_error:
                    row['wait_error'] = type(cleanup_error).__name__
                row['exit_code'] = proc.returncode
            raise
        finally:
            row['elapsed_seconds'] = time.monotonic() - started
            for stream, path in paths.items():
                if path.exists():
                    try:
                        data = read_file(path)
                        row['raw'][stream] = {'role': label + '_' + stream, 'bytes': len(data), 'sha256': digest(data),
                                             'complete': row['waited_and_reaped'], 'relative_file': path.relative_to(self.root).as_posix()}
                    except Exception as error:
                        row.setdefault('raw_errors', {})[stream] = type(error).__name__
            if os.path.lexists(self.state):
                try:
                    self.save_snapshot(label + '-after-command')
                    row['snapshot_saved'] = True
                    if role == 'old':
                        self.no_marker()
                        row['marker_absent'] = True
                except Exception as error:
                    row['snapshot_error'] = str(error) if isinstance(error, StopJourney) else type(error).__name__
        require(row['waited_and_reaped'] and not row['timeout'] and not row['kill_attempted'], 'command_not_natural_complete')
        require(not row.get('raw_errors') and set(row['raw']) == {'stdout', 'stderr'}, 'raw_capture_incomplete')
        require('snapshot_error' not in row, 'post_command_snapshot_failed')
        require((row['exit_code'] == 0) if success else (row['exit_code'] != 0), 'unexpected_cli_exit')
        require(digest(read_file(self.binary[role])) == self.hashes[role], 'binary_changed_after_command')
        stdout, stderr = (read_file(paths[s], 8 << 20) for s in ['stdout', 'stderr'])
        row['validation_complete'] = True
        return stdout, stderr

    def execute(self):
        raw, _ = self.command('01-old-init', 'old', ['init'])
        initialized = object_json(raw)
        require(initialized.get('status') == 'initialized', 'old_init_result')
        instance = object_json(read_file(self.state / 'local-instance.json', 65536))
        require(instance.get('schema_version') == 'local-client-instance/v1'
                and HEX.fullmatch(instance.get('instance_id', ''))
                and initialized.get('instance_id') == instance['instance_id'], 'old_instance_binding')
        require(HEX.fullmatch(initialized.get('state_directory_id', '')), 'old_directory_binding')
        object_json(read_file(self.state / 'config.json', 65536))
        raw, _ = self.command('02-old-pubkey', 'old', ['pubkey'])
        require(len(base64.b64decode(raw.strip(), validate=True)) == 32, 'public_key_shape')
        skill = b'---\nname: windows-unmarked-fixture\ndescription: Read a harmless local migration fixture.\n---\nRead-only prose for an owned compatibility fixture.\n'
        with (self.fixture / 'SKILL.md').open('xb') as f:
            f.write(skill)
        raw, _ = self.command('03-old-admit', 'old', ['admit', str(self.fixture)])
        admission = object_json(raw)
        admission_id = safe_id(admission.get('admission_id'))
        raw, _ = self.command('04-old-grant', 'old', ['grant', admission_id, '--platform', 'hermes', '--subject', 'windows-unmarked-owned-fixture'])
        created = object_json(raw)
        grant_id = safe_id(created.get('grant', {}).get('grant_id'))
        raw, _ = self.command('05-old-revoke', 'old', ['grant', 'revoke', grant_id])
        revoked = object_json(raw)
        require(revoked.get('grant', {}).get('status') == 'revoked'
                and revoked['grant']['grant_id'] == grant_id
                and type(revoked.get('state_revision')) is int and revoked['state_revision'] > 0, 'old_revoke_result')
        self.no_marker()
        original = self.save_snapshot('06-original-unmarked')
        require(not any('serve.lock' in PurePosixPath(k).name for k in original), 'unexpected_remaining_lock')
        require(not any(k == JOURNAL or k.startswith(JOURNAL + '/') for k in original), 'old_migration_directory_unexpected')
        self.claims.update(real_unmarked_old_business_created=True, old_marker_absent_after_each_command=True,
                           old_revoked_state_revision=revoked['state_revision'], historical_entries=len(original))
        self.old_closed = True  # Permanent before any new binary touches this state.
        raw, _ = self.command('07-new-status-before', 'new', ['state-status'])
        diagnosis = object_json(raw)
        require(diagnosis.get('compatible') is True and diagnosis.get('status') == 'legacy_unversioned'
                and diagnosis.get('format_version') == 0, 'new_unmarked_diagnosis')
        self.no_marker()
        require(snapshot(self.state) == original, 'status_before_modified_state')
        self.claims['pre_migration_status_zero_state_writes'] = True
        raw, _ = self.command('08-new-migrate', 'new', ['state-migrate', '--confirm'])
        migration = object_json(raw)
        require(migration.get('status') == 'migrated' and migration.get('format_version') == 2, 'migration_result')
        after = self.save_snapshot('09-migrated')
        require(all(after.get(k) == v for k, v in original.items()), 'historical_entry_modified')
        added = set(after) - set(original)
        require(all(k == MARKER or k in MAINTENANCE or k == JOURNAL or k.startswith(JOURNAL + '/') for k in added), 'unexpected_migration_addition')
        require(not os.path.lexists(self.state / 'logs/migration-plan.json'), 'active_barrier_not_removed')
        marker_raw = read_file(self.state / MARKER, 4096)
        marker = object_json(marker_raw)
        require(marker.get('schema') == 'state-format/v2' and marker.get('format_version') == 2
                and marker.get('min_reader') == marker.get('min_writer') == 2
                and marker.get('instance_id') == instance['instance_id']
                and marker.get('state_directory_id') == initialized['state_directory_id'], 'v2_binding')
        plan_raw = read_file(self.state / JOURNAL / 'plan.json', 8 << 20)
        plan = object_json(plan_raw)
        require(plan.get('schema') == 'state-migration-plan/v1' and plan.get('source_marker_sha256') == 'absent'
                and plan.get('target') == marker and plan.get('instance_id') == marker['instance_id']
                and plan.get('state_directory_id') == marker['state_directory_id'], 'plan_source_absent_binding')
        entries = plan.get('entries')
        require(type(entries) is list and len(entries) <= MAX_ENTRIES, 'plan_entries_shape')
        mapped = {}
        for entry in entries:
            rel = entry['path']
            require(type(rel) is str and rel not in mapped and chr(92) not in rel and ':' not in rel
                    and not rel.startswith('/') and all(x not in ['', '.', '..'] for x in rel.split('/')), 'plan_path_invalid')
            require(set(entry) == {'path', 'mode', 'directory', 'size', 'sha256'}, 'plan_entry_keys')
            mapped[rel] = entry
        require(list(mapped) == sorted(mapped) and set(original).issubset(mapped), 'plan_manifest_set')
        require(set(mapped) - set(original) <= MAINTENANCE, 'plan_added_nonmaintenance')
        backup = snapshot(self.state / JOURNAL / 'backup')
        require(set(backup) == set(mapped), 'backup_manifest_not_exact')
        for rel, entry in mapped.items():
            live = after[rel]
            for row in [live, backup[rel]]:
                require(row['directory'] == entry['directory'] and row['go_mode'] == entry['mode']
                        and row['size'] == entry['size'] and row['sha256'] == entry['sha256'], 'plan_backup_entry_mismatch')
            if rel not in original:
                require(entry['directory'] is True and entry['size'] == 0 and entry['sha256'] == '', 'maintenance_not_empty_directory')
            if not entry['directory']:
                bytes_equal(self.state / rel, self.state / JOURNAL / 'backup' / rel)
        done = object_json(read_file(self.state / JOURNAL / 'done.json', 4096))
        checkpoint = object_json(read_file(self.state / JOURNAL / 'backup.done.json', 4096))
        require(done == {'schema': 'state-migration-done/v1', 'plan_sha256': digest(plan_raw), 'marker_sha256': digest(marker_raw)}
                and checkpoint == {'plan_sha256': digest(plan_raw)}, 'completion_hash_binding')
        require(migration.get('backup_entries') == len(entries), 'backup_result_count')
        self.claims.update(migrated_to_v2=True, historical_entries_unchanged=True,
                           source_marker_binding='absent', backup_entries=len(entries),
                           complete_backup_verified=True, backup_live_file_bytes_equal=True,
                           marker_instance_and_original_directory_bound=True, archived_plan_sha256=digest(plan_raw))
        raw, _ = self.command('10-new-repeat-migrate', 'new', ['state-migrate', '--confirm'])
        require(object_json(raw).get('status') == 'up_to_date' and snapshot(self.state) == after, 'repeat_not_zero_write')
        raw, _ = self.command('11-new-status-after', 'new', ['state-status'])
        status = object_json(raw)
        require(status.get('compatible') is True and status.get('status') == 'ok'
                and status.get('format_version') == 2 and snapshot(self.state) == after, 'v2_status_not_zero_write')
        _, stderr = self.command('12-new-revoke-rejected', 'new', ['grant', 'revoke', grant_id], success=False)
        require(b'revoked' in stderr and snapshot(self.state) == after, 'revoke_not_revoked_zero_write')
        require(read_file(self.fixture / 'SKILL.md') == skill, 'fixture_content_changed')
        self.claims.update(repeat_up_to_date_zero_state_writes=True, v2_status_zero_state_writes=True,
                           already_revoked_rejected_zero_state_writes=True,
                           old_binary_never_invoked_after_upgrade_boundary=True)
        self.result['status'] = 'passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--old-binary', required=True)
    parser.add_argument('--old-sha256', required=True)
    parser.add_argument('--new-binary', required=True)
    parser.add_argument('--new-sha256', required=True)
    args = parser.parse_args()
    journey = None
    try:
        journey = Journey(args)
        journey.execute()
    except Exception as error:
        code = str(error) if isinstance(error, StopJourney) else type(error).__name__
        if journey is None:
            # Never write through an unvalidated root or expose arbitrary error text.
            print(json.dumps({'status': 'not_run', 'stage': 'preflight', 'error_code': code}))
            return 1
        journey.result.update(status='fail', partial=bool(journey.steps), failure_stage=journey.phase, error_code=code)
    finally:
        if journey is not None:
            journey.result['all_spawned_commands_reaped'] = all(s['waited_and_reaped'] for s in journey.steps if s['spawned'])
            try:
                new_json(journey.root / 'journey-result.private.json', journey.result)
            except Exception as error:
                journey.result.update(status='fail', summary_write_error=type(error).__name__)
    print(json.dumps({'status': journey.result['status'], 'steps': len(journey.steps),
                      'failure_stage': journey.result.get('failure_stage'), 'retained': True}))
    return 0 if journey.result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
