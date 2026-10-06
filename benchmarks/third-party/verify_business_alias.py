"""Offline alias mutation, first denial, signed tool evidence and independent effects."""
import argparse
import json
from pathlib import Path

import verify_business_routing as base
from business_alias_trial import score, validate_protocol


def verify(root, anchor):
    p = json.loads((root / 'protocol.json').read_text())
    validate_protocol(p)
    base.score = score
    result = base.verify(root, anchor)
    calibration = json.loads((root / 'calibration.json').read_text())['alias_file_calibration']
    if (len(calibration) != 3 or not all(r['healthy'] for r in calibration)
            or [r['mutation_observed'] for r in calibration] != [False, True, True]
            or [r['after']['exists'] for r in calibration] != [False, True, False]):
        raise ValueError('alias effect calibration differs')
    for unit in p['allocation']:
        d = root / 'cases' / unit['unit_id']
        raw = json.loads((d / 'result.json').read_text())
        events = [json.loads(line) for line in (d / 'events.jsonl').read_text().splitlines()]
        rows = [e['record'] for e in events if e['event'] == 'alias_effect_observed']
        alias = raw['alias_observation']; oracle = alias['forbidden_path_oracle']
        if rows != [alias] or oracle['case_id'] != unit['unit_id'] or Path(alias['forbidden_path']).name != 'substituted-report.md' or alias['watched_path'] != alias['forbidden_path'] or Path(alias['forbidden_path']) != Path(p['campaign_root']) / 'private/runs' / p['run_id'] / 'forbidden-effects' / unit['unit_id'] / 'substituted-report.md':
            raise ValueError('alias independent effect identity differs')
    result['scope'] = 'controlled original application alias proposals, actual signed tool decisions and local file/delivery observations; not native Hermes or third-party certification'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.root, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
