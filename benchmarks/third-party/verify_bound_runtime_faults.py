"""Verify signed execution checkpoint, revocation/cancellation and recovery."""
import argparse
import json
from pathlib import Path

import bound_runtime_faults as bound
import verify_native_runtime_faults as parent
from personal_onboarding_authority import require

original_joins = parent.joins


def joins(raw, evidence):
    result = original_joins(raw, evidence)
    obs = raw['runtime_check_observation']
    final = obs['receipts']['receipts']
    measured = []
    for name in ('grant-revoked', 'cancel'):
        row = obs.get('variants', {}).get(name, {})
        if 'before_injection' not in row:
            continue
        cid = row['plan']['check_id']
        prefix = row['receipts_before']
        require(final[:len(prefix)] == prefix, 'pause API receipts not exact signed prefix')
        for receipt in row.get('trigger_receipts', []):
            require(receipt in final and receipt['agent_id'] == 'rca-' + cid[3:], 'trigger is not signed own receipt')
        records = [r for r in row['records_before'].values() if r['result']['check_id'] == cid]
        latest = max(records, key=lambda r: r['revision'])
        require(latest['result'] == row['before_injection'], 'pause API not latest signed checkpoint')
        if bound.stage_measured(row):
            require(latest['binding_id'] != '', 'checkpoint not attached')
            document = next(b for b in row['bindings']['items'] if b['binding_id'] == latest['binding_id'])
            first = next(r for r in prefix if r.get('agent_id') == 'rca-' + cid[3:] and r.get('tool_call_id') == 'rc-first' and r['record_type'] == 'decision')
            require(document['session_id'] == first['session_id'] and document['agent_id'] == first['agent_id'], 'first read belongs to different native binding')
            require(first['intent_id'] == latest['intent_id'] and first['intent_digest'] == latest['intent_digest'] and first['matched_grant_id'] == latest['grant_id'], 'first read authority differs')
            measured.append(name)
    return {**result, 'measured_after_first_read': measured}


def verify(run, anchor):
    parent.faults = bound
    parent.joins = joins
    return parent.verify(run, anchor)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
