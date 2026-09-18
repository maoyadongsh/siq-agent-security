#!/usr/bin/env python3
"""Supplement LC05 on an explicitly selected retained B01 test-release state.

Only systemd's ownership-verified runtime unit receives SIGKILL; never target
an arbitrary PID or a persistent/daily unit. Preserve data and unregister at end.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from installed_user_service_driver import InstalledUserServiceDriver, sha256_file


def run(args):
    os.umask(0o077)
    args.out.mkdir(parents=True, mode=0o700, exist_ok=False)
    d = InstalledUserServiceDriver(str(args.state), args.port)
    checks = {}
    failure = None
    unit = None
    owned_binary = None

    def check(name, ok):
        checks[name] = bool(ok)
        if not ok:
            raise AssertionError(name)

    try:
        d.install(str(args.manifest), str(args.binary), port=args.port)
        d.set_current_cli(str(args.binary))
        before = d.identity()
        unit = before['unit_name']
        owned_binary = before['running_binary_path']
        source = args.state / unit
        props = d.unit_properties(unit, ['FragmentPath', 'DropInPaths', 'UnitFileState', 'MainPID'])
        check('runtime_owned_unit', props['UnitFileState'] in ('linked-runtime', 'enabled-runtime')
              and props['DropInPaths'] == '' and Path(props['FragmentPath']).resolve() == source.resolve()
              and Path(before['running_binary_path']).is_relative_to(args.state)
              and props['MainPID'] == before['main_pid'])
        admin = d.pair(before['running_binary_path'])
        code, grants = d.api('GET', '/v1/grants', token=admin)
        check('revoked_authority_present', code == 200 and any(g['status'] == 'revoked' for g in grants['grants']))
        config_hash = sha256_file(args.state / 'config.json')
        # systemd resolves the current main process for this exact owned unit;
        # do not race a naked PID lookup against PID reuse.
        subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=main', '--signal=KILL', '--', unit],
                       capture_output=True, timeout=15, check=True)
        # The signed unit intentionally uses Restart=no. Recovery is an
        # explicit product command, not automatic systemd restart.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if d.unit_properties(unit, ['MainPID'])['MainPID'] == '0':
                break
            time.sleep(0.1)
        check('killed_main_exited', d.unit_properties(unit, ['MainPID'])['MainPID'] == '0')
        d.service_start(owned_binary)
        deadline = time.monotonic() + 30
        after = None
        while time.monotonic() < deadline:
            try:
                observed = d.identity()
                if observed['main_pid'] not in ('0', before['main_pid']) and observed['active_state'] == 'active':
                    after = observed
                    break
            except (OSError, RuntimeError, ValueError):
                time.sleep(0.2)
        check('explicit_product_start_recovers_new_main_pid', after is not None)
        check('same_instance_candidate_and_configuration', all(after[k] == before[k] for k in
              ('state_directory_id', 'unit_name', 'binary_digest', 'running_binary_path', 'version', 'port'))
              and sha256_file(args.state / 'config.json') == config_hash)
        code, _ = d.api('GET', '/v1/grants', token=admin)
        check('old_admin_session_rejected', code == 401)
        renewed = d.pair(after['running_binary_path'])
        code, retained = d.api('GET', '/v1/grants', token=renewed)
        check('all_grant_signatures_revisions_and_revocation_retained', code == 200 and retained == grants)
    except (OSError, RuntimeError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as exc:
        failure = type(exc).__name__
    finally:
        if unit:
            try:
                d.teardown(owned_binary)
                checks['owned_unit_unregistered_data_retained'] = d.load_state(unit) == 'not-found' and args.state.is_dir()
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                checks['owned_unit_unregistered_data_retained'] = False
                failure = type(exc).__name__
    report = {'schema_version': 'closure-b01-crash-review/v1', 'recorded_at': datetime.now(UTC).isoformat(),
              'passed': failure is None and bool(checks) and all(checks.values()), 'error_type': failure,
              'checks': checks, 'binary_sha256': sha256_file(args.binary), 'trust_layer': 'test_release',
              'boundary': 'same retained test instance; no full-machine reboot, login-autostart or official-release claim'}
    path = args.out / 'report.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    (args.out / 'SHA256SUMS').write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '  report.json\n')
    print(json.dumps({'passed': report['passed'], 'checks': len(checks), 'error_type': failure}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.state = args.state.resolve(strict=True)
    raise SystemExit(run(args))
