"""Preserve old browser scoring while verifying an interrupted activity navigation."""
import argparse
import copy
import json
from pathlib import Path

import verify_personal_runtime_browser as original
from personal_onboarding_authority import require

original_joins = original.verify_joins


def partial_joins(o, evidence):
    if 'activity_reference' not in o or 'activity_detail' in o:
        return original_joins(o, evidence)
    reduced = copy.deepcopy(o)
    reduced.pop('activity_reference')
    result = original_joins(reduced, evidence)
    reference = o['activity_reference']
    require(reference['check_id'] == o['passed']['check_id'] and reference['instance_id'] == o['instance_id'], 'partial reference targets another check')
    receipts, _ = evidence.verify_receipt_bundles([o['receipts']])
    for rid in o['passed']['receipt_ids']:
        record = receipts[rid][0]
        require(all(record[k] == reference['activity']['binding'][k] for k in
                    ('chain_id', 'platform', 'session_id', 'agent_id', 'task_id', 'intent_id', 'intent_digest')), 'partial activity binding differs')
    result['activity_detail_not_captured'] = True
    result['scope'] = 'available signature and reference checks only; missing detail not synthesized; original unknown unchanged'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    original.verify_joins = partial_joins
    result = original.verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
