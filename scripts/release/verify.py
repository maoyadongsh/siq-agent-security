#!/usr/bin/env python3
"""Verify an existing signed client release; optional isolated native smoke. Never sign/publish."""
import argparse
import hashlib
import json
import os
import platform
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import package

ROOT = Path(__file__).resolve().parents[2]
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assets(version):
    return {f'siq-agent-security-{version}-bundle.zip', f'siq-agent-security-skill-{version}.zip',
            'SOURCE-INFO.json', 'SHA256SUMS',
            *(package.artifact_name(system, arch) for system, arch in package.TARGETS)}


def extract_zip(archive, target, prefix):
    """Validate every member before writing; no traversal, links, collisions or huge payloads."""
    with zipfile.ZipFile(archive) as bundle:
        items = bundle.infolist()
        require(sum(i.file_size for i in items) <= MAX_ARCHIVE_BYTES, 'archive exceeds size limit')
        seen = set()
        for item in items:
            path = PurePosixPath(item.filename)
            require(item.filename == path.as_posix() and not path.is_absolute()
                    and '..' not in path.parts and '\\' not in item.filename
                    and path.parts[0] == prefix and len(path.parts) > 1, 'unsafe archive path')
            reserved = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)),
                        *(f'lpt{i}' for i in range(1, 10))}
            require(not any(any(c in part for c in ':<>"|?*') or part.endswith((' ', '.'))
                            or part.split('.')[0].casefold() in reserved for part in path.parts),
                    'nonportable archive path')
            require(item.filename.casefold() not in seen, 'duplicate archive entry')
            seen.add(item.filename.casefold())
            mode = item.external_attr >> 16
            require(stat.S_ISREG(mode) and not item.is_dir() and not mode & 0o7000,
                    'archive must contain regular files only')
        for item in items:
            path = target / item.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(bundle.read(item))
            path.chmod(0o700 if item.external_attr >> 16 & 0o111 else 0o600)
    return target / prefix


def check_assets(directory, version, source_sha):
    expected = assets(version)
    require({p.name for p in directory.iterdir()} == expected, 'release must contain exactly eight assets')
    require(all(p.is_file() and not p.is_symlink() for p in directory.iterdir()), 'nonregular release asset')
    require(sum(p.stat().st_size for p in directory.iterdir()) <= 2 * MAX_ARCHIVE_BYTES, 'release assets exceed size limit')
    sums = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([^/\\]+)', line)
        require(match is not None, 'invalid checksum line')
        checksum, name = match.groups()
        require(name not in sums and name in expected - {'SHA256SUMS'}, 'duplicate/unknown checksum asset')
        sums[name] = checksum
    require(set(sums) == expected - {'SHA256SUMS'}, 'incomplete checksum inventory')
    require(all(digest(directory / name) == value for name, value in sums.items()), 'asset checksum mismatch')
    identity = json.loads((directory / 'SOURCE-INFO.json').read_text())
    require(identity['version'] == version and identity['source_sha'] == source_sha,
            'descriptive source/version does not match expected identity')
    require(identity['publisher_manifest_verified'] is True, 'unsigned candidate is not an installation release')
    return identity


def public_key():
    source = (ROOT / 'apps/agentshield/internal/skillmanifest/manifest.go').read_text()
    return re.search(r'const ReleasePublicKeyB64 = "([^"]+)"', source).group(1)


def verify_signature(skill):
    require((skill / 'skill-manifest.json').stat().st_size <= 1024 * 1024, 'manifest exceeds size limit')
    result = subprocess.run([sys.executable, str(ROOT / 'skills/siq-agent-security/scripts/verify_manifest.py'),
                             '--manifest', str(skill / 'skill-manifest.json'), '--pubkey', public_key(),
                             '--skill-dir', str(skill)], env=package.build_env(), capture_output=True, timeout=60)
    require(result.returncode == 0, 'official signature or actual Skill content verification failed')


def native_target():
    system = {'Linux': 'linux', 'Darwin': 'darwin', 'Windows': 'windows'}.get(platform.system())
    arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    require((system, arch) in package.TARGETS, 'native target not included in release')
    return system, arch


def smoke(bundle, version):
    system, arch = native_target()
    require(system in ('linux', 'darwin'), 'bundled Bash smoke currently supports Linux/macOS; Windows native test not run')
    binary = bundle / 'bin' / package.artifact_name(system, arch)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    # INSTALL is descriptive, not signed: execute only the exact trusted generator text checked by verify().
    commands = re.findall(r'```bash\n(.*?)\n```', package.installation_text(version, True), re.S)
    require(len(commands) == 1, 'unexpected INSTALL command structure')
    command = commands[0].replace('siq-agent-security-linux-arm64', binary.name).replace('47611', str(port))
    env = {k: v for k, v in package.build_env().items() if k != 'XDG_RUNTIME_DIR'}
    control_env = {**env, 'SIQ_AGENT_SECURITY_STATE_DIR': str(bundle / 'state')}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    log = bundle.parent / 'native-smoke-private.log'
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        process = subprocess.Popen(['bash', '-c', command], cwd=bundle, env=env, stdout=stream, stderr=stream, start_new_session=True)
        try:
            for _ in range(150):
                require(process.poll() is None, 'bundled first-start command exited early')
                try:
                    with opener.open(f'http://127.0.0.1:{port}/healthz', timeout=1) as response:
                        require(response.status == 200, 'health check failed')
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                raise ValueError('native startup timed out')
            require((bundle / 'state/config.json').is_file(), 'first start did not initialize private state')
            for action in ('status', 'pair'):
                result = subprocess.run([str(binary), action, '--port', str(port)], env=control_env,
                                        stdout=stream, stderr=stream, timeout=15)
                require(result.returncode == 0, f'native {action} failed')
            with opener.open(f'http://127.0.0.1:{port}/overview', timeout=3) as response:
                require(response.status == 200 and b'<html' in response.read().lower(), 'console not available')
        finally:
            stopped = None
            try:
                stopped = subprocess.run([str(binary), 'stop', '--confirm-stop'], env=control_env,
                                         stdout=stream, stderr=stream, timeout=45)
                process.wait(timeout=15)
            finally:
                # Our private process group only: an errored shell must not orphan the test child.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                # Kill any remaining descendant in this private session after the shell exited.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            require(stopped is not None and stopped.returncode == 0, 'isolated service stop failed')
    return {'host': f'{system}/{arch}', 'fresh_state_start_status_pair_console_stop': 'passed'}


def verify(directory, version, source_sha, *, native_smoke=False):
    package.validate_inputs(source_sha, version)
    identity = check_assets(directory, version, source_sha)
    # Temporary private extraction prevents interference with user services/state or source trees.
    with tempfile.TemporaryDirectory(prefix='siq-release-verify-') as temp:
        private = Path(temp)
        private.chmod(0o700)
        bundle = extract_zip(directory / f'siq-agent-security-{version}-bundle.zip', private / 'bundle',
                             f'siq-agent-security-{version}')
        skill_only = extract_zip(directory / f'siq-agent-security-skill-{version}.zip', private / 'skill',
                                 'siq-agent-security')
        require((bundle / 'SOURCE-INFO.json').read_bytes() == (directory / 'SOURCE-INFO.json').read_bytes(),
                'bundle and asset metadata differ')
        payload = package.inventory(bundle)
        require(set(payload) == set(identity['files']) | {'SOURCE-INFO.json', 'INSTALL.md'}, 'bundle inventory mismatch')
        for name, details in identity['files'].items():
            require(payload[name] == details, f'bundle metadata differs: {name}')
        skill = bundle / 'skills/siq-agent-security'
        require(package.inventory(skill) == package.inventory(skill_only), 'Skill ZIP differs from bundle')
        verify_signature(skill)
        package.verify_pins(skill / 'skill-manifest.json', bundle / 'bin', version)
        for system, arch in package.TARGETS:
            name = package.artifact_name(system, arch)
            require((bundle / 'bin' / name).read_bytes() == (directory / name).read_bytes(), 'flat binary differs from signed pin')
        for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'LICENSES/README.md'):
            require((bundle / name).is_file(), 'required license missing')
        require((bundle / 'INSTALL.md').read_text() == package.installation_text(version, True),
                'INSTALL differs from trusted generator; review version-specific instructions before executing')
        native = smoke(bundle, version) if native_smoke else {'status': 'not_run'}
    return {'schema_version': 'siq-release-verification/v1', 'version': version, 'expected_source_sha': source_sha,
            'source_identity_scope': 'descriptive metadata matched; publisher signature binds Skill and binary pins, not source attestation',
            'official_signature_and_skill_content': 'passed', 'four_binary_pins': 'passed',
            'asset_inventory_and_checksums': 'passed', 'bundle_skill_zip_and_flat_binaries': 'passed',
            'trusted_installation_instructions': 'passed', 'native_installation': native,
            'published': 'not_checked', 'assets': [{'name': p.name, 'sha256': digest(p), 'bytes': p.stat().st_size}
                                                 for p in sorted(directory.iterdir())]}


def write_report(path, report):
    with path.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-dir', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--native-smoke', action='store_true', help='explicitly start/stop an isolated Linux/macOS test service')
    parser.add_argument('--report', type=Path, required=True, help='new output file; never overwrite an earlier record')
    args = parser.parse_args()
    try:
        require(not args.report.exists() and not args.report.is_symlink(), 'report exists; choose a new record')
        report = verify(args.release_dir.resolve(), args.version, args.source_sha, native_smoke=args.native_smoke)
        write_report(args.report, report)
        print(json.dumps({'result': 'passed', 'native_smoke': args.native_smoke, 'published': 'not_checked'}))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        parser.exit(1, f'release verification failed: {exc}\n')


if __name__ == '__main__':
    main()
