#!/usr/bin/env python3
"""Check native source setup in temporary state; no publisher signing or host installation."""
import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import package

ROOT = Path(__file__).resolve().parents[2]


def require(ok, phase):
    if not ok:
        raise ValueError(phase)


def native_target():
    system = {'Linux': 'linux', 'Darwin': 'darwin', 'Windows': 'windows'}.get(platform.system())
    arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    return f'{system}/{arch}'


def check(binary, target):
    require(native_target() == target, 'runner OS/architecture differs from requested target')
    source = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = bool(subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain']))
    skill = ROOT / 'skills/siq-agent-security'
    require(not (skill / 'skill-manifest.json').exists(), 'expected unsigned development Skill source')
    with tempfile.TemporaryDirectory(prefix='siq-source-smoke-') as temp:
        private = Path(temp).resolve()
        env = {**package.build_env(), 'SIQ_AGENT_SECURITY_BIN': str(binary),
               'SIQ_AGENT_SECURITY_STATE_DIR': str(private / 'state'),
               'SIQ_AGENT_SECURITY_STAGE_DIR': str(private / 'stage'),
               'SIQ_AGENT_SECURITY_REQUIRE_PINNED': '1', 'PYTHONUTF8': '1'}
        bootstrap = (['pwsh', '-NoProfile', '-NonInteractive', '-File', str(skill / 'scripts/bootstrap.ps1')]
                     if os.name == 'nt' else ['sh', str(skill / 'scripts/bootstrap.sh')])
        rejected = subprocess.run(bootstrap, env=env, capture_output=True, timeout=30)
        require(rejected.returncode != 0 and b'skill-manifest.json missing' in rejected.stderr,
                'source bootstrap did not reject missing manifest')
        require(not (private / 'state').exists() and not (private / 'stage').exists(),
                'unsigned bootstrap modified state/staging')
        result = subprocess.run([str(binary), 'admit', str(skill)], env=env, capture_output=True, timeout=60)
        require(result.returncode == 0 and json.loads(result.stdout)['verdict'] == 'admit_with_conditions',
                'self-built binary rejected current Skill source')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        log = private / 'private.log'
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            for mode in ('start', 'serve'):
                # Admission and the two startup routes have separate private state.
                env['SIQ_AGENT_SECURITY_STATE_DIR'] = str(private / mode)
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    port = sock.getsockname()[1]
                if mode == 'serve':
                    initialized = subprocess.run([str(binary), 'init', '--port', str(port)], env=env,
                                                 stdout=stream, stderr=stream, timeout=30)
                    require(initialized.returncode == 0, 'explicit initialization failed')
                process = subprocess.Popen([str(binary), mode, '--port', str(port)], env=env,
                                           stdout=stream, stderr=stream)
                try:
                    for _ in range(150):
                        require(process.poll() is None, f'{mode} exited before readiness')
                        try:
                            with opener.open(f'http://127.0.0.1:{port}/healthz', timeout=1) as response:
                                require(response.status == 200, 'unhealthy service')
                            break
                        except OSError:
                            time.sleep(0.2)
                    else:
                        raise ValueError(f'{mode} readiness timed out')
                    require((Path(env['SIQ_AGENT_SECURITY_STATE_DIR']) / 'config.json').is_file(),
                            'startup did not initialize configuration')
                    for action in ('status', 'pair'):
                        result = subprocess.run([str(binary), action, '--port', str(port)], env=env,
                                                stdout=stream, stderr=stream, timeout=20)
                        require(result.returncode == 0, f'{mode}: {action} failed')
                    remote_env = {**env, 'SSH_CONNECTION': 'fixture-only-not-a-login-target',
                                  'DISPLAY': '', 'WAYLAND_DISPLAY': ''}
                    guided = subprocess.run([str(binary), 'ui'], env=remote_env,
                                            capture_output=True, timeout=20)
                    require(guided.returncode == 0, f'{mode}: SSH UI guidance failed')
                    forwarding = f'-L 127.0.0.1:{port}:127.0.0.1:{port}'.encode()
                    require(forwarding in guided.stdout and b'fixture-only' not in guided.stdout,
                            f'{mode}: unsafe or missing SSH guidance')
                    printed = subprocess.run([str(binary), 'ui', '--print'], env=remote_env,
                                             capture_output=True, timeout=20)
                    require(printed.returncode == 0 and printed.stdout == f'http://127.0.0.1:{port}/\n'.encode(),
                            f'{mode}: print-only URL compatibility failed')
                    with opener.open(f'http://127.0.0.1:{port}/overview', timeout=5) as response:
                        require(response.status == 200 and b'<html' in response.read().lower(), 'missing console')
                    stopped = subprocess.run([str(binary), 'stop', '--confirm-stop'], env=env,
                                             stdout=stream, stderr=stream, timeout=45)
                    require(stopped.returncode == 0, f'{mode}: graceful stop failed')
                    process.wait(timeout=20)
                    require(process.returncode == 0, f'{mode}: service exited unsuccessfully')
                finally:
                    # Only the exact foreground Go child created here. No shell, task or service manager.
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
    return {'schema_version': 'siq-skill-source-smoke/v1', 'source_sha': source, 'source_dirty': dirty,
            'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'target': target, 'binary_sha256': package.digest(binary),
            'skill_document_sha256': hashlib.sha256((skill / 'SKILL.md').read_bytes()).hexdigest(),
            'unsigned_source_bootstrap_refused_without_writes': True, 'self_admission': 'admit_with_conditions',
            'fresh_start_status_pair_console_stop': 'passed', 'init_serve_status_pair_console_stop': 'passed',
            'ssh_ui_guidance_and_print_only': 'passed',
            'scope': 'source build setup in isolated state; not a signed installation package, host integration, desktop or background service acceptance',
            'published': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--target', choices=[f'{s}/{a}' for s, a in package.TARGETS], required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.report.exists() and not args.report.is_symlink(), 'report must be new')
        require(os.name != 'nt' or shutil.which('pwsh'), 'Windows smoke requires PowerShell Core')
        result = check(args.binary.resolve(strict=True), args.target)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'result': 'passed', 'target': args.target, 'scope': result['scope']}))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'source setup verification failed: {exc}\n')


if __name__ == '__main__':
    main()
