"""Recompute anchored native semantic cohorts and emit separate primary/secondary counts."""
import argparse
import json
from pathlib import Path

from common import write_json
from native_semantic_review import review as secondary_review
from verify_native_business import verify


def summarize(campaign, anchors):
    rows, details = [], {}
    for name, anchor in anchors.items():
        if Path(name).name != name:
            raise ValueError('invalid run ID')
        run = campaign / 'data' / name
        original = verify(run, anchor)
        protocol = json.loads((run / 'protocol.json').read_text())
        if protocol['profile'] not in ('semantic-briefing', 'semantic-support-v2'):
            raise ValueError('semantic profile required')
        secondary = secondary_review(run, anchor) if protocol['profile'] == 'semantic-briefing' else None
        for group in ('B0', 'B2'):
            units = [u for u in protocol['allocation'] if u['group'] == group]
            scores = [original['units'][u['unit_id']] for u in units]
            qualities = [s['semantic_quality'] for s in scores]
            evaluable = [q for q in qualities if q['report_schema_valid']]
            extra = [secondary['units'][u['unit_id']] for u in units] if secondary else None
            rows.append({'run_id': name, 'mode': protocol['mode'], 'profile': protocol['profile'],
                         'group': group, 'allocated': len(units),
                         'measurement_complete': sum(s['measurement_complete'] for s in scores),
                         'schema_valid_reports': len(evaluable),
                         'correct_values_in_schema_valid_reports': sum(q['claims_correct'] for q in evaluable),
                         'evaluable_claims': sum(q['claims_total'] for q in evaluable),
                         'schema_invalid_unscored_claims': sum(q['claims_total'] for q in qualities if not q['report_schema_valid']),
                         'all_values_correct_reports': sum(q['all_values_correct'] for q in qualities),
                         'primary_utility_completed': sum(s['utility_completed'] is True for s in scores),
                         'primary_utility_unknown': sum(s['utility_completed'] is None for s in scores),
                         'secondary_supported_utility': sum(s['measured_supported_utility'] is True for s in extra) if extra is not None else None,
                         'secondary_utility_unknown': sum(s['measured_supported_utility'] is None for s in extra) if extra is not None else None,
                         'private_read_proposals': sum(s['private_read_proposals'] for s in scores),
                         'private_read_denials': sum(s['private_read_denials'] for s in scores),
                         'known_harm': sum(s['harm_observed'] is True for s in scores),
                         'harm_unknown': sum(s['harm_observed'] is None for s in scores),
                         'all_owned_processes_cleaned': all(s['cleanup_confirmed'] for s in scores)})
        details[name] = {'manifest_sha256': anchor, 'signed_receipts': original['signed_receipts'],
                         'original_outcome_exit_code': original['outcome_exit_code'],
                         'model_budget': json.loads((run / 'summary.json').read_text())['model_budget'],
                         'task_block_ids': sorted({u['task_block_id'] for u in protocol['allocation']})}
    return {'schema_version': 'siq-native-semantic-summary/v1', 'runs': details, 'rows': rows,
            'scope': 'four distinct author-visible task blocks reused across variants/cohorts; claims within reports are correlated; original primary metrics and post-run secondary interpretation separated; no third-party certification'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run', action='append', required=True, help='run-id=externally recorded manifest SHA-256')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    pairs = [item.split('=', 1) for item in args.run]
    if any(len(pair) != 2 for pair in pairs) or len(dict(pairs)) != len(pairs):
        raise ValueError('invalid or repeated run')
    result = summarize(args.campaign, dict(pairs))
    write_json(args.out, result)
    print(json.dumps(result))
