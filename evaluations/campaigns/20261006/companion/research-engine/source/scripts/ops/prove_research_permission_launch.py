"""Exercise pinned protected/rollback startup on the reserved staging port.

Uses the owning project's database, without creating business tasks or taking
recovery ownership. It never stops or replaces the daily API process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

from scripts.openshell.prove_research_daily_entry import process_snapshot
from scripts.ops import launch_research_permission_api as launch


def port_closed():
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(('127.0.0.1', 18083)) != 0


def run(args):
    import httpx

    os.umask(0o077)
    args.private.mkdir(mode=0o700, parents=True, exist_ok=False)
    if args.output.exists():
        raise ValueError('launch_proof_output_exists')
    before = process_snapshot(args.api_pid, args.api_start_ticks)
    launch.validate_sources(args.manifest, args.manifest_sha256)
    result = {'schema_version': 'siq.research-api-launch-proof.v1',
        'started_unix': time.time(), 'original_api_pid': args.api_pid,
        'source_manifest_sha256': args.manifest_sha256, 'modes': {}, 'passed': False,
        'scope': 'Staging startup/exit only; no model task, grant or protected execution claim.'}
    process = None
    try:
        for mode in ('protected', 'rollback'):
            if not port_closed():
                raise RuntimeError('launch_proof_staging_port_busy')
            command = [str(launch.ROOT / 'apps/api/.venv/bin/python'),
                str(launch.ROOT / 'scripts/ops/launch_research_permission_api.py'),
                '--environment-reference', str(args.environment_reference),
                '--manifest', str(args.manifest), '--manifest-sha256', args.manifest_sha256,
                '--mode', mode, '--port', '18083', '--private-log', str(args.private / (mode + '.log'))]
            record = result['modes'][mode] = {'checks': {}}
            with (args.private / (mode + '-bootstrap.log')).open('xb') as log:
                process = subprocess.Popen(command, cwd=launch.ROOT, stdout=log, stderr=log,
                    stdin=subprocess.DEVNULL)
            record['candidate_pid'] = process.pid
            deadline = time.monotonic() + 90
            with httpx.Client(trust_env=False, timeout=3) as client:
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('launch_proof_candidate_exited')
                    try:
                        response = client.get('http://127.0.0.1:18083/health')
                        if response.status_code == 200 and response.json().get('status') == 'ok':
                            health = response.json()
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError('launch_proof_readiness_timeout')
                    time.sleep(.5)
                record['checks']['http_health_ready'] = True
                for key in ('openshell_recovery', 'qwen_request_recovery'):
                    record['checks'][key + '_disabled'] = health.get(key, {}).get('enabled') is False
                record['checks']['anonymous_chat_denied'] = client.post(
                    'http://127.0.0.1:18083/api/analysis/chat', json={'message': 'Synthetic startup probe'}
                ).status_code == 401
            ticks = Path('/proc', str(process.pid), 'stat').read_text().split(') ')[1].split()[19]
            actual = process_snapshot(process.pid, ticks)
            record['checks']['selected_backend_loaded'] = actual.get('SIQ_OPENSHELL_REQUEST_BACKEND') == (
                'qwen38' if mode == 'protected' else 'legacy')
            record['checks']['actual_port_matches_environment'] = actual.get('SIQ_BACKEND_PORT') == '18083'
            process.terminate()
            process.wait(timeout=30)
            record['checks']['owned_process_stopped'] = process.poll() is not None
            record['checks']['staging_port_closed'] = port_closed()
            record['checks']['original_daily_process_unchanged'] = process_snapshot(
                args.api_pid, args.api_start_ticks) == before
            process = None
        launch.validate_sources(args.manifest, args.manifest_sha256)
        result['sources_unchanged_after'] = True
        result['passed'] = all(all(m['checks'].values()) for m in result['modes'].values())
    except Exception as exc:
        result['failure_type'] = type(exc).__name__
        if isinstance(exc, RuntimeError) and str(exc).startswith('launch_proof_'):
            result['failure_code'] = str(exc)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
                result['forced_owned_cleanup'] = True
                result['passed'] = False
        result['finished_unix'] = time.time()
        result['staging_port_closed_after'] = port_closed()
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'passed': result['passed'], 'report': str(args.output)}))
    return 0 if result['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-pid', type=int, required=True)
    parser.add_argument('--api-start-ticks', required=True)
    parser.add_argument('--environment-reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
