"""Freeze/run real enterprise exclusive-target and live-authority boundaries."""
import argparse
import json
from pathlib import Path

import enterprise_chain_trial
import governance_trial
from common import sha256, utc_now, write_json
from enterprise_authority import ASSERTIONS, CASES, VARIANTS


def freeze(campaign, protocol_id):
    enterprise_chain_trial.freeze(campaign, protocol_id)
    path = campaign / 'protocols' / protocol_id / 'protocol.json'
    p = json.loads(path.read_text())
    p['enterprise_authority_assertions'] = ASSERTIONS
    p['authority_variants'] = VARIANTS
    p['backend_assertions'] += ASSERTIONS
    p['expected_status'].update(CASES)
    p['scope'] += '; duplicate target binding refusal, honest registered-only impact, six invalid current authorities at preview and rollback, stale authorization digest refusal'
    p['limits'] += ['shared-target intersections are unimplemented; tests assert refusal, not shared sandbox isolation',
                    'operator file faults controlled sequentially; does not close last-check-to-write races or protect against service-UID administrator',
                    'rollback denial currently returns HTTP 502 plus audit; error code is not a business reachability oracle']
    p['frozen_at'] = utc_now()
    for name in ('enterprise_authority.py', 'enterprise_authority_trial.py'):
        (path.parent / 'harness-source' / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    p['harness_sources'] = {str(f.relative_to(path.parent / 'harness-source')): sha256(f) for f in (path.parent / 'harness-source').rglob('*') if f.is_file()}
    write_json(path, p, exclusive=False)
    write_json(path.parent / 'local-anchor.json', {'sha256': sha256(path)}, exclusive=False)
    print(json.dumps({'protocol': str(path), 'HTTP_allocation': len(p['expected_status']), 'authority_assertions': len(ASSERTIONS)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--protocol-id', required=True)
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.action == 'freeze':
        freeze(args.campaign.resolve(), args.protocol_id)
    else:
        raise SystemExit(governance_trial.run(args.campaign.resolve(), args.protocol_id, args.run_id))
