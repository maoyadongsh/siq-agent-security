"""Freeze complete worker lifecycle including owned real HTTP notifications."""
import argparse
import json
from pathlib import Path

import enterprise_risk_trial as base
import governance_trial
from common import sha256, write_json
from enterprise_risk import CASES as OLD_CASES
from enterprise_risk_worker import ASSERTIONS, CASES


def freeze(campaign, protocol_id, candidate):
    base.freeze(campaign, protocol_id, candidate)
    path = campaign / 'protocols' / protocol_id / 'protocol.json'
    p = json.loads(path.read_text())
    for case in OLD_CASES:
        del p['expected_status'][case]
    p['expected_status'].update(CASES)
    p['risk_assertions'] = ASSERTIONS
    p['risk_worker_cycle'] = True
    p['scope'] = 'Native asset, full worker.once cycles in production API/PostgreSQL, active risk deduplication, real expiry, resolved recurrence, owned loopback webhook delivery'
    p['limits'] = ['author issuer and synthetic native configuration, not customer IdP or external witness',
                   'eight sequential full worker.once subprocesses, not continuous scheduling or concurrency',
                   'backend none: drift skipped; no policy enforcement or natural attack claims',
                   'real owned loopback webhook, not customer notification service or retry/failover guarantee',
                   'resolved fixture condition intentionally persists to verify recurrence; no real remediation claim']
    for name in ('enterprise_risk_worker.py', 'enterprise_risk_worker_trial.py'):
        (path.parent / 'harness-source' / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    p['harness_sources'] = {f.name: sha256(f) for f in (path.parent / 'harness-source').glob('*.py')}
    write_json(path, p, exclusive=False)
    write_json(path.parent / 'local-anchor.json', {'sha256': sha256(path)}, exclusive=False)
    print(json.dumps({'HTTP': len(p['expected_status']), 'risk_assertions': len(ASSERTIONS)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'run'])
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--protocol-id', required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--candidate', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'freeze':
        freeze(args.campaign.resolve(), args.protocol_id, args.candidate.resolve())
    else:
        raise SystemExit(governance_trial.run(args.campaign.resolve(), args.protocol_id, args.run_id))
