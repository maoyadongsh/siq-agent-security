"""Verify held TCP boundary and original application signed effects offline."""
import argparse
import json
from pathlib import Path

import verify_business_routing as base
from business_routing_edges import score, validate_protocol


def verify(root, anchor):
    p = json.loads((root / 'protocol.json').read_text())
    validate_protocol(p)
    base.score = score
    result = base.verify(root, anchor)
    for unit in p['allocation']:
        path = root / 'cases' / unit['unit_id']
        raw = json.loads((path / 'result.json').read_text())
        events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
        records = [e['record'] for e in events if e['event'] == 'tcp_boundary_observed']
        if records != [raw['transport_observation']]:
            raise ValueError('TCP observation differs from events')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.root, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
