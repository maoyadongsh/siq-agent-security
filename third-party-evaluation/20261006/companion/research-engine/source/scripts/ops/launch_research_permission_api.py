"""Launch a source-pinned local API using an existing private environment.

Protected mode selects the native per-request OpenShell backend. Rollback
mode restores the original environment choices without invoking a stale
historical source manifest. Neither mode creates grants or signs identities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROOT = Path(__file__).resolve().parents[2]


def private_json(path):
    if path.resolve(strict=True) != path:
        raise ValueError('api_environment_path_invalid')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or not 0 < info.st_size <= 1048576):
            raise ValueError('api_environment_file_unsafe')
        raw = os.read(fd, 1048577)
        current = path.stat(follow_symlinks=False)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
                current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) or len(raw) != info.st_size:
            raise ValueError('api_environment_file_changed')
        value = json.loads(raw)
    finally:
        os.close(fd)
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError('api_environment_schema_invalid')
    return value


def configured_environment(original, *, mode, port):
    if (mode not in {'protected', 'rollback'} or port not in {18081, 18083}
            or original.get('SIQ_BACKEND_HOST') != '127.0.0.1'
            or original.get('SIQ_BACKEND_PORT') != '18081'
            or original.get('SIQ_ENV', 'development').lower() in {'prod', 'production'}
            or original.get('SIQ_DEPLOYMENT_PROFILE', 'local').lower() in {'prod', 'production'}):
        raise ValueError('api_local_deployment_invalid')
    environment = dict(original)
    # Preserve the actual historical launcher's explicit overrides.
    environment.update(SIQ_OPENSHELL_REQUEST_BACKEND='legacy', SIQ_OPENSHELL_REQUEST_DEPLOYMENT='host')
    environment.pop('SIQ_OPENSHELL_REQUEST_CANDIDATE_IMAGE_RECORD', None)
    if mode == 'protected':
        environment.update(SIQ_OPENSHELL_REQUEST_BACKEND='qwen38',
            SIQ_OPENSHELL_DATA_CLASSIFICATION='confidential_local',
            SIQ_DEPLOYMENT_PROFILE='local', SIQ_ENV='development',
            SIQ_OPENSHELL_LOCAL_GRANT_ADMIN_ENABLED='1')
    environment.update(SIQ_BACKEND_PORT=str(port), PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=str(ROOT / 'apps/api') + ':' + str(ROOT))
    if port == 18083:
        # Staging startup does not take recovery ownership from the daily API.
        # Its unavailable recovery state is not counted as an execution pass.
        environment.update(SIQ_OPENSHELL_POOL_RECOVERY_ENABLED='0', SIQ_OPENSHELL_POOL_RECOVERY_REQUIRED='0',
            SIQ_PRIMARY_MARKET_RECONCILE_ON_STARTUP='0', SIQ_PRIMARY_MARKET_RECONCILE_PERIODIC='0')
    return environment


def validate_sources(manifest, expected):
    if not re.fullmatch('[a-f0-9]{64}', expected):
        raise ValueError('api_manifest_digest_invalid')
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('api_manifest_changed')
    value = json.loads(raw)
    sources = value.get('source_sha256')
    if value.get('schema_version') != 'siq.research-api-source-manifest.v1' or not isinstance(sources, dict) or not sources:
        raise ValueError('api_manifest_invalid')
    own_name = str(Path(__file__).resolve().relative_to(ROOT))
    if own_name not in sources or 'apps/api/main.py' not in sources:
        raise ValueError('api_manifest_entrypoint_missing')
    for name, digest in sources.items():
        path = ROOT / name
        if (Path(name).is_absolute() or not path.resolve().is_relative_to(ROOT) or path.is_symlink()
                or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError('api_frozen_source_changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment-reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--mode', choices=['protected', 'rollback'], required=True)
    parser.add_argument('--port', type=int, choices=[18081, 18083], default=18081)
    parser.add_argument('--private-log', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    validate_sources(args.manifest, args.manifest_sha256)
    original = private_json(args.environment_reference)
    environment = configured_environment(original, mode=args.mode, port=args.port)
    if args.check_only:
        print(json.dumps({'source_manifest_verified': True, 'private_environment_verified': True,
                          'mode': args.mode, 'port': args.port, 'secret_values_exported': False}))
        return 0
    os.umask(0o077)
    if args.private_log.parent.resolve(strict=True) != args.private_log.parent:
        raise ValueError('api_log_parent_invalid')
    fd = os.open(args.private_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        os.close(fd)
        raise ValueError('api_log_file_unsafe')
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    os.chdir(ROOT / 'apps/api')
    python = str(ROOT / 'apps/api/.venv/bin/python')
    os.execve(python, [python, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1',
                      '--port', str(args.port), '--no-access-log'], environment)


if __name__ == '__main__':
    raise SystemExit(main())
