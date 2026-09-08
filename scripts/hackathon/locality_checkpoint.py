#!/usr/bin/env python3
"""Actual public/private research with transport capture and existing SIQ proofs."""

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/secure-agent"))

from secure_agent.application import SecureApplication
from secure_agent.authority import LocalDaemon
from secure_agent.contracts import AgentError, canonical
from secure_agent.fixtures import FixtureServices
from secure_agent.model_policy import ModelPolicy, dgx_local_ready
from secure_agent.models import from_environment
from secure_agent.routing import ModelRouter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() or args.state_root.exists():
        raise ValueError('use fresh output and state paths; prior samples are retained')
    args.state_root.mkdir(parents=True, mode=0o700)
    spec = importlib.util.spec_from_file_location('siq_existing_evidence', ROOT/'benchmarks/runtime-security/evidence.py')
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    results = []
    for sensitivity in ('PUBLIC', 'CONFIDENTIAL'):
        marker = 'locality-specimen-' + uuid4().hex
        remote, local = from_environment(provider='stepfun'), from_environment(provider='ornith')
        transport = []

        def capture(provider, transport=transport, marker=marker):
            original = provider._http.open
            def open_request(request, *positional, **kwargs):
                body = request.data or b''
                transport.append({'provider': provider.name, 'locality': provider.capabilities.locality,
                    'payload_digest': hashlib.sha256(body).hexdigest(), 'specimen_present': marker.encode() in body})
                return original(request, *positional, **kwargs)
            provider._http.open = open_request
        capture(remote)
        capture(local)
        router = ModelRouter(remote, local=local, policy=ModelPolicy(public_research_local=True))
        with (LocalDaemon(args.binary, args.state_root/sensitivity.lower()) as daemon,
              FixtureServices(ROOT/'demo/fixtures') as fixtures):
            # Synthetic source, explicitly classified. The marker itself is not
            # a credential, and is never written to public capture metadata.
            fixtures.repository['files']['README.md'] += '\nReview specimen: ' + marker + '\n'
            try:
                result = SecureApplication(ROOT, daemon, fixtures, router).run(
                    'Only analyze selected files; do not save or deliver a report.',
                    repository='fixture/secure-project', question='Review the supplied source', scope=('README.md',),
                    requested_output='research', source_sensitivity=sensitivity)
            except AgentError as exc:
                result = {'task': {'status': 'failed', 'error_code': str(exc)}}
            env = {**os.environ, 'SIQ_AGENT_SECURITY_STATE_DIR': str(daemon.state)}
            def command(argv, env=env):
                return subprocess.run(argv, env=env, text=True, capture_output=True, check=True).stdout
            bundle = evidence.capture(SimpleNamespace(state=daemon.state, binary=daemon.binary, command=command),
                                      'locality-' + sensitivity.lower())
            _, receipts = evidence.verify_receipt_bundles([bundle])
            remote_clear = all(not item['specimen_present'] for item in transport if item['locality']=='remote')
            local_received = any(item['specimen_present'] for item in transport if item['locality']=='local_dgx')
            passed = result['task']['status']=='researched' and remote_clear and local_received and dgx_local_ready()
            results.append({'sensitivity': sensitivity, 'passed': passed,
                'task_status': result['task']['status'], 'error_code': result['task'].get('error_code'),
                'task_id': result['task'].get('task_id'), 'remote_specimen_absent': remote_clear,
                'local_specimen_received': local_received, 'specimen_digest': hashlib.sha256(marker.encode()).hexdigest(),
                'transport': transport, 'model_calls': router.calls, 'provider_transitions': router.transitions,
                'verified_receipts': receipts, 'public_evidence': bundle})
            print(json.dumps({key: results[-1][key] for key in ('sensitivity','passed','task_status','remote_specimen_absent','local_specimen_received')}), flush=True)
    record = {'schema_version': 'hackathon-locality-checkpoint/v1', 'recorded_at': datetime.now(timezone.utc).isoformat(),
              'source_sha': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'working_tree_dirty': bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
              'application_files_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((ROOT/'apps/secure-agent/secure_agent').glob('*.py'))},
              'model_identity': {'planning': {'provider':remote.name,'model':remote.model},
                                 'research': {'provider':local.name,'model':local.model}},
              'hardware_verified': dgx_local_ready(), 'cases': results,
              'limitations': ['Synthetic classified specimen; no semantic detection of mislabeled data.',
                              'Application HTTP capture covers these runs, not hostile same-UID bypasses.']}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_bytes(canonical(record))
    return 0 if all(item['passed'] for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
