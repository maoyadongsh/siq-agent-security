#!/usr/bin/env python3
"""Read a published release, verify immutable assets, write a new receipt; never publish/edit."""
import argparse
import datetime
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import package
import verify

REPO = 'maoyadongsh/siq-agent-security'


def environment():
    env = package.build_env()
    env.pop('GITHUB_TOKEN', None)  # Repository documented keyring authentication, not stale inherited token.
    return env


def gh(*args):
    result = subprocess.run(['gh', *args], env=environment(), capture_output=True, timeout=240)
    verify.require(result.returncode == 0, 'GitHub read/download failed; no publication mutation attempted')
    return result.stdout


def api(path):
    return json.loads(gh('api', f'repos/{REPO}/{path}'))


def check_metadata(release, reference, version, source_sha):
    tag = f'siq-agent-security-v{version}'
    verify.require(release['tag_name'] == tag and release['draft'] is False, 'wrong tag or draft release')
    verify.require(release['html_url'] == f'https://github.com/{REPO}/releases/tag/{tag}', 'unexpected release URL')
    verify.require(len(release['assets']) == 8 and {a['name'] for a in release['assets']} == verify.assets(version),
                   'unexpected remote asset inventory')
    verify.require(all(a['state'] == 'uploaded' for a in release['assets']), 'incomplete asset upload')
    verify.require(reference['type'] == 'commit' and reference['sha'] == source_sha, 'tag source differs from expected commit')


def readback(local, version, source_sha):
    package.validate_inputs(source_sha, version)
    verify.verify(local, version, source_sha)  # Local reference must already be independently verifiable.
    tag = f'siq-agent-security-v{version}'
    release = api(f'releases/tags/{tag}')
    reference = api(f'git/ref/tags/{tag}')['object']
    for _ in range(3):
        if reference['type'] != 'tag':
            break
        reference = api(f'git/tags/{reference["sha"]}')['object']
    check_metadata(release, reference, version, source_sha)
    latest = api('releases/latest')
    with tempfile.TemporaryDirectory(prefix='siq-release-readback-') as temp:
        root = Path(temp)
        root.chmod(0o700)
        remote = root / 'assets'
        gh('release', 'download', tag, '--repo', REPO, '--dir', str(remote))
        report = verify.verify(remote, version, source_sha)
        for name in verify.assets(version):
            verify.require((remote / name).read_bytes() == (local / name).read_bytes(), 'remote asset differs from local verified reference')
        url = f'https://github.com/{REPO}/releases/download/{tag}/SHA256SUMS'
        with urllib.request.urlopen(url, timeout=60) as response:
            verify.require(response.read(65537) == (local / 'SHA256SUMS').read_bytes(), 'public checksum download differs')
        # Check the actual signed URL and staging path for this host without executing the downloaded program.
        skill = verify.extract_zip(remote / f'siq-agent-security-skill-{version}.zip', root / 'skill', 'siq-agent-security')
        system, arch = verify.native_target()
        result = subprocess.run([sys.executable, str(verify.ROOT / 'skills/siq-agent-security/scripts/verify_manifest.py'),
                                 '--manifest', str(skill / 'skill-manifest.json'), '--pubkey', verify.public_key(),
                                 '--skill-dir', str(skill), '--fetch-artifact', '--stage-to', str(root / 'staged')],
                                env=environment(), capture_output=True, timeout=180)
        verify.require(result.returncode == 0, 'signed public URL download/staging failed')
        staged = Path(result.stdout.decode().strip())
        verify.require(staged.resolve().is_relative_to(root) and staged.is_file(), 'unexpected verifier staging output')
        verify.require(staged.read_bytes() == (local / package.artifact_name(system, arch)).read_bytes(), 'staged binary differs')
    return {'schema_version': 'siq-release-readback/v1', 'version': version, 'tag_source_sha': source_sha,
            'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'release_url': release['html_url'], 'published': True, 'prerelease': release['prerelease'],
            'is_latest': latest['tag_name'] == tag, 'remote_assets_equal_local_verified_reference': True,
            'official_signature_and_all_pins_verified': True, 'public_checksum_download': 'passed',
            'signed_url_download_and_staging': {'target': f'{system}/{arch}', 'result': 'passed'},
            'native_installation': 'not_run; readback never starts a service', 'assets': report['assets']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-dir', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        verify.require(not args.report.exists() and not args.report.is_symlink(), 'report exists; choose a new record')
        report = readback(args.reference_dir.resolve(), args.version, args.source_sha)
        verify.write_report(args.report, report)
        print(json.dumps({'result': 'passed', 'version': args.version, 'assets_verified': len(report['assets'])}))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'release readback failed: {exc}\n')


if __name__ == '__main__':
    main()
