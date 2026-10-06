"""Freeze real risk disposition concurrency and expiry races."""
import argparse
import json
from pathlib import Path

import enterprise_risk_trial as base
import governance_trial
from common import sha256, write_json
from enterprise_risk import CASES as OLD_CASES
from enterprise_risk_race import ASSERTIONS, CASES


def freeze(campaign, protocol_id, candidate):
    base.freeze(campaign, protocol_id, candidate)
    path = campaign / 'protocols' / protocol_id / 'protocol.json'
    p = json.loads(path.read_text())
    for case in OLD_CASES:
        del p['expected_status'][case]
    p['expected_status'].update(CASES)
    p['risk_assertions'] = ASSERTIONS
    p['risk_race_profile'] = True
    p['scope'] = 'Native asset -> real risk HTTP disposition races and real overlapping expiry workers with explicit PostgreSQL lock barriers'
    p['limits'] = ['author issuer and owned PostgreSQL fixtures, not customer IdP or external witness',
                   'five forced overlap groups, not natural concurrency frequency or throughput',
                   'real API lifecycle prepares fresh findings; no SQL finding state resets',
                   'expiry function subprocesses, not full worker scheduling or notification coverage',
                   'first rule creation concurrency not included']
    for name in ('enterprise_risk_race.py', 'enterprise_risk_race_trial.py'):
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
