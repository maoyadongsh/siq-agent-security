"""Run research-owned live proofs with a separate, pinned SIQ authority.

No imports from the research repository; the owning project's CLI runs there.
Only this process's daemon is stopped. Logs/credentials remain in private/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def free(port):
    with socket.socket() as connection:
        return connection.connect_ex(('127.0.0.1', port)) != 0


def require_frozen_protocol(campaign, batch, research_root):
    """Reject missing or stale source freezes before creating owned resources."""
    security_root = Path(__file__).resolve().parents[2]
    path = campaign / 'protocols' / (batch + '.json')
    if path.is_symlink() or not path.is_file():
        raise ValueError('frozen protocol required before live startup')
    protocol = json.loads(path.read_text())
    sources = protocol.get('source_sha256')
    if protocol.get('batch') != batch or not isinstance(sources, dict) or not sources:
        raise ValueError('invalid frozen protocol identity or sources')
    launcher = 'benchmarks/third-party/research_permissions_run.py'
    if sources.get(launcher) != digest(Path(__file__)):
        raise ValueError('launcher is not frozen at current source digest')
    roots = (security_root, research_root.resolve())
    for name, expected in sources.items():
        source = Path(name) if name.startswith('/') else security_root / name
        if not any(source.resolve().is_relative_to(root) for root in roots):
            raise ValueError('frozen source outside owning repositories')
        if source.is_symlink() or not source.is_file() or digest(source) != expected:
            raise ValueError('frozen source missing or changed')
    return digest(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research-root', type=Path, required=True)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--relay-binary', type=Path)
    parser.add_argument('--relay-sha256')
    parser.add_argument('--batch', required=True)
    parser.add_argument('--suffix', required=True)
    parser.add_argument('--mode', choices=('business', 'agent', 'skill-install', 'skill-business', 'skill-withdrawal', 'skill-drift', 'skill-drift-authority', 'skill-drift-containment', 'tool-coverage', 'cross-company', 'business-revoke', 'skill-update', 'skill-replacement', 'relay-recovery', 'tool-utility'), required=True)
    parser.add_argument('--control', choices=('revoke-context', 'drift-installation', 'revoke-grant'))
    parser.add_argument('--task', choices=('connectivity', 'readonly-analysis', 'paired-analysis'), default='connectivity')
    args = parser.parse_args()
    if not re.fullmatch(r'research-permissions-[a-z0-9-]+', args.batch):
        raise ValueError('invalid batch')
    if not re.fullmatch(r'v[1-9][0-9]{0,3}', args.suffix):
        raise ValueError('invalid suffix')
    if digest(args.binary) != args.binary_sha256:
        raise ValueError('binary identity changed')
    protocol_sha256 = require_frozen_protocol(args.campaign, args.batch, args.research_root)
    if not all(free(port) for port in (47811, 18083, 47710)):
        raise ValueError('owned ports occupied')
    os.umask(0o077)
    private = args.campaign / 'private/runs' / args.batch
    private.mkdir(mode=0o700, parents=True, exist_ok=False)
    state = private / 'authority-state'
    state.mkdir(mode=0o700)
    # Read only public artifact references from the business authority record.
    binding = json.loads((args.research_root / 'var/openshell/secrets/agentshield-runtime-authority.json').read_text())
    if bool(args.relay_binary) != bool(args.relay_sha256):
        raise ValueError('relay override requires exact digest')
    if args.relay_binary:
        binding['relay_binary'] = str(args.relay_binary)
        binding['relay_sha256'] = args.relay_sha256
    relay = Path(binding['relay_binary'])
    if digest(relay) != binding['relay_sha256']:
        raise ValueError('relay identity changed')
    record = {'schema_version': 'siq.evaluation.research-permissions-run.v1',
              'batch': args.batch, 'mode': args.mode, 'passed': False,
              'pre_run_protocol_sha256': protocol_sha256,
              'scope': 'dedicated_real_research_deployment_synthetic_company',
              'binary_sha256': args.binary_sha256,
              'relay_sha256': binding['relay_sha256'], 'started_unix': time.time(),
              'checks': {}, 'secret_values_exported': False}
    environment = {k: os.environ[k] for k in ('HOME', 'PATH', 'LANG', 'XDG_RUNTIME_DIR', 'DOCKER_HOST') if k in os.environ}
    daemon_env = {**environment, 'SIQ_AGENT_SECURITY_STATE_DIR': str(state)}
    process = None
    try:
        with (private / 'authority-init.log').open('xb') as log:
            initialized = subprocess.run([str(args.binary), 'init', '--port', '47811'],
                                         env=daemon_env, stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=log, timeout=20, check=False)
        if initialized.returncode:
            raise RuntimeError('owned_daemon_init_failed')
        record['checks']['owned_daemon_initialized'] = True
        with (private / 'authority.log').open('xb') as log:
            process = subprocess.Popen([str(args.binary), 'serve', '--port', '47811', '--mode', 'block'],
                                       env=daemon_env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError('owned_daemon_exited')
            try:
                with opener.open('http://127.0.0.1:47811/healthz', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('owned_daemon_not_ready')
        record['checks']['owned_daemon_ready'] = True
        common = ['--recovery-file', str(state / 'admin-recovery.token'),
                  '--relay-binary', str(relay), '--relay-sha256', binding['relay_sha256'],
                  '--helper-image-ref', binding['helper_image_ref'],
                  '--helper-image-id', binding['helper_image_id']]
        command = [str(args.research_root / 'apps/api/.venv/bin/python'), '-m']
        if args.mode == 'business':
            command += ['scripts.openshell.prove_research_business_permissions', *common,
                        '--evidence-suffix', args.suffix, '--task', args.task]
            source = args.research_root / f'artifacts/openshell/flagship/ml02-business-api-e126-{args.suffix}.sanitized.json'
        elif args.mode == 'agent':
            command += ['scripts.openshell.prove_research_agent_permissions', *common,
                        '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'skill-install':
            command += ['scripts.openshell.research_permission_skills',
                        '--recovery-file', str(state / 'admin-recovery.token'),
                        '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'skill-business':
            command += ['scripts.openshell.prove_research_skill_business', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'tool-coverage':
            command += ['scripts.openshell.prove_research_tool_permissions', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'cross-company':
            command += ['scripts.openshell.prove_research_cross_company_permissions', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'business-revoke':
            command += ['scripts.openshell.prove_research_business_grant_revoke', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'skill-update':
            command += ['scripts.openshell.prove_research_skill_update_permissions', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'skill-replacement':
            command += ['scripts.openshell.prove_research_skill_replacement', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'relay-recovery':
            command += ['scripts.openshell.prove_research_relay_recovery', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'tool-utility':
            command += ['scripts.openshell.prove_research_tool_utility', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'skill-drift':
            command += ['scripts.openshell.prove_research_skill_drift', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'skill-drift-authority':
            command += ['scripts.openshell.prove_research_skill_drift_authority', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        elif args.mode == 'skill-drift-containment':
            command += ['scripts.openshell.prove_research_skill_drift_containment', *common,
                        '--evidence-suffix', args.suffix, '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        else:
            if args.control is None:
                raise RuntimeError('skill_withdrawal_control_required')
            command += ['scripts.openshell.prove_research_skill_withdrawal', *common,
                        '--control', args.control, '--evidence-suffix', args.suffix,
                        '--output', str(private / 'research-proof.json')]
            source = private / 'research-proof.json'
        if source.exists():
            raise RuntimeError('proof_output_preexists')
        proof_env = {**environment, 'PYTHONPATH': str(args.research_root / 'apps/api') + ':' + str(args.research_root)}
        with (private / 'proof.log').open('xb') as log:
            completed = subprocess.run(command, cwd=args.research_root, env=proof_env,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=1000, check=False)
        record['proof_exit_code'] = completed.returncode
        if source.exists():
            record['proof'] = json.loads(source.read_text())
            record['proof_sha256'] = digest(source)
            record['checks']['live_proof_passed'] = record['proof'].get('passed') is True
        else:
            record['checks']['proof_written'] = False
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        record['failure_type'] = type(exc).__name__
        if type(exc) is RuntimeError:
            record['failure_code'] = str(exc)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        record['checks']['owned_daemon_stopped'] = process is None or process.poll() is not None
        record['checks']['owned_authority_port_closed'] = free(47811)
        record['finished_unix'] = time.time()
        record['passed'] = not record.get('failure_type') and bool(record['checks'].get('live_proof_passed')) and all(record['checks'].values())
        destination = args.campaign / 'reports' / (args.batch + '.json')
        with destination.open('x') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        print(json.dumps({'report': str(destination), 'passed': record['passed'], 'checks': record['checks']}))
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
