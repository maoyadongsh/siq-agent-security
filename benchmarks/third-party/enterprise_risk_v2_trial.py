"""Freeze legal expiry/reopening lifecycle on the repaired terminal guard."""
import argparse
import json
from pathlib import Path

import enterprise_risk_trial as base
import governance_trial
from common import sha256, write_json
from enterprise_risk_v2 import ASSERTIONS, CASES


def freeze(campaign, protocol_id, candidate):
    base.freeze(campaign, protocol_id, candidate)
    path = campaign / 'protocols' / protocol_id / 'protocol.json'
    p = json.loads(path.read_text())
    p['expected_status'].update(CASES)
    p['risk_assertions'] = ASSERTIONS
    p['risk_lifecycle_v2'] = True
    p['scope'] += '; legal expiry-reopen before each further acceptance, current terminal refusal and complete audit/outbox lifecycle counts'
    p['limits'] += ['four actual deadline windows and twelve controlled reaper subprocesses; not scheduler latency or concurrency assurance',
                    'supersedes only the old reaccept-while-terminal harness step, never regrades old candidates or claims an unchanged protocol']
    for name in ('enterprise_risk_v2.py', 'enterprise_risk_v2_trial.py'):
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
