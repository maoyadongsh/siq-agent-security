#!/usr/bin/env python3
"""Collect actual DGX/environment facts; missing services remain unverified."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError('redirect rejected')


def probe(endpoint, path, key='', service=None):
    if not endpoint:
        return {'status': 'unconfigured'}
    parts = urlsplit(endpoint)
    if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment
            or (parts.scheme == 'http' and parts.hostname not in ('localhost', '127.0.0.1', '::1'))):
        return {'status': 'invalid_endpoint'}
    headers = {'Authorization': 'Bearer ' + key} if key else {}
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(Request(endpoint.rstrip('/') + path, headers=headers), timeout=5) as response:
            raw = response.read((1 << 20) + 1)
            if len(raw) > 1 << 20:
                return {'status': 'response_too_large'}
            payload = json.loads(raw)
            if service == 'siq' and (not isinstance(payload, dict) or payload.get('local_mode') is not True
                                      or payload.get('enforcement_mode') != 'block'):
                return {'status': 'service_contract_invalid'}
            if service in ('agent', 'web', 'fixtures') and (not isinstance(payload, dict)
                    or payload.get('service') != 'siq-hackathon-' + service or payload.get('status') != 'ready'):
                return {'status': 'service_contract_invalid'}
            models = [m['id'] for m in payload.get('data', []) if isinstance(m, dict) and isinstance(m.get('id'), str)] if isinstance(payload, dict) else []
            return {'status': 'reachable', 'http_status': response.status, 'models': models}
    except (URLError, OSError, ValueError):
        return {'status': 'unreachable'}


def collect():
    gpu = command(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader,nounits']) if shutil.which('nvidia-smi') else None
    version = command(['nvidia-smi', '--version']) if gpu else None
    cuda = re.search(r'CUDA Version\s*:\s*([^\n]+)', version or '')
    memory = read('/proc/meminfo') or ''
    ram = re.search(r'^MemTotal:\s+(\d+)\s+kB', memory, re.MULTILINE)
    product = read('/sys/devices/virtual/dmi/id/product_name')
    provider = os.environ.get('SIQ_MODEL_PROVIDER', 'stepfun')
    prefix = 'SIQ_' + provider.upper() if provider in ('stepfun', 'ornith') else 'SIQ_UNSUPPORTED'
    model = os.environ.get(prefix + '_MODEL')
    endpoint = os.environ.get(prefix + '_ENDPOINT')
    model_probe = probe(endpoint, '/models', os.environ.get(prefix + '_API_KEY', ''))
    model_probe.update(provider=provider, configured_model=model, key_present=bool(os.environ.get(prefix + '_API_KEY')),
                       inference_verification='unverified', model_digest='unverified')
    source = {}
    for directory in ('apps/secure-agent/secure_agent', 'skills/secure-research', 'skills/secure-report', 'skills/secure-delivery'):
        for file in sorted((ROOT / directory).rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts:
                source[str(file.relative_to(ROOT))] = hashlib.sha256(file.read_bytes()).hexdigest()
    services = {name: probe(os.environ.get(variable), route, service=name) for name, variable, route in (
        ('siq', 'SIQ_HACKATHON_SIQ_ENDPOINT', '/ui-config.json'),
        ('agent', 'SIQ_HACKATHON_AGENT_ENDPOINT', '/health'),
        ('web', 'SIQ_HACKATHON_WEB_ENDPOINT', '/web/health'),
        ('fixtures', 'SIQ_HACKATHON_FIXTURE_ENDPOINT', '/health'))}
    hardware_verified = product in ('NVIDIA_DGX_Spark', 'NVIDIA DGX Spark') and platform.machine() in ('aarch64', 'arm64') and bool(gpu)
    return {'schema_version': 'dgx-spark-environment/v1', 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'hardware': {'product': product, 'vendor': read('/sys/devices/virtual/dmi/id/sys_vendor'),
            'os': read('/etc/os-release'), 'kernel': platform.release(), 'architecture': platform.machine(),
            'gpu': gpu, 'cuda': cuda[1].strip() if cuda else None, 'ram_bytes': int(ram[1])*1024 if ram else None,
            'dgx_identity_verified': hardware_verified},
        'model': model_probe, 'services': services,
        'skills_present': all((ROOT / 'skills' / name / 'SKILL.md').is_file() for name in ('secure-research', 'secure-report', 'secure-delivery')),
        'fixtures_present': all((ROOT / 'demo/fixtures' / name).is_dir() for name in ('github', 'mcp', 'contacts', 'message-sink', 'effect-oracle', 'workspace')),
        'source_sha': command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']),
        'working_tree_dirty': bool(command(['git', '-C', str(ROOT), 'status', '--porcelain'])),
        'application_files_sha256': source,
        'deployment_verified': False,
        'limitations': ['Hardware identity is separate from model inference and complete deployment verification.',
                        'A reachable model listing is not a successful planning or end-to-end inference result.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('dgx-spark-environment.json'))
    parser.add_argument('--require-ready', action='store_true', help='fail until hardware, model and all service probes are ready')
    args = parser.parse_args()
    record = collect()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'report': str(args.out), 'dgx_identity_verified': record['hardware']['dgx_identity_verified'],
                      'model_status': record['model']['status'], 'deployment_verified': False}))
    ready = (record['hardware']['dgx_identity_verified'] and record['model']['provider'] in ('stepfun', 'ornith')
             and record['model']['configured_model'] in record['model'].get('models', [])
             and all(s['status'] == 'reachable' for s in record['services'].values()))
    return 0 if not args.require_ready or ready else 1


if __name__ == '__main__':
    raise SystemExit(main())
