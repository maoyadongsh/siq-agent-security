"""Supplementary latest-revision binding and tamper checks without business reruns."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from personal_onboarding_authority import require
from verify_native_personal_runtime_check import verify, verify_runtime


def strict_runtime(raw, evidence):
    result = verify_runtime(raw, evidence)
    stages = raw['runtime_check_observation']['stages']
    for records, view in (('records_before_drift', 'terminal'), ('records_after_restore', 'after_restore')):
        latest = max(stages[records].values(), key=lambda r: r['revision'])
        require(latest['result'] == stages[view], 'HTTP readback is not latest signed revision')
    return result


def review(run, anchor):
    baseline = verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    spec = importlib.util.spec_from_file_location('runtime_check_tamper_evidence', source)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    raw = json.loads((run / 'cases/personal-onboarding-B2/result.json').read_text())
    strict_runtime(raw, evidence)
    negatives = []
    for mutation in ('revision-signature', 'activity-other-task', 'foreign-instance', 'temporary-grant-binding',
                     'partial-receipt-list', 'restored-old-pass', 'chain-prefix-truncation'):
        changed = copy.deepcopy(raw)
        obs = changed['runtime_check_observation']
        s = obs['stages']
        if mutation == 'revision-signature':
            next(iter(s['records_before_drift'].values()))['actor_id'] = 'other-operator'
        elif mutation == 'activity-other-task':
            s['activity']['activity']['binding']['task_id'] = 'other-task'
        elif mutation == 'foreign-instance':
            obs['instance_id'] = 'hi-' + '0' * 32
        elif mutation == 'temporary-grant-binding':
            binding = next(b for b in s['bindings_after']['items'] if b['intent_id'].startswith('rci-'))
            binding['grant_ref']['grant_id'] = 'other-grant'
        elif mutation == 'partial-receipt-list':
            s['terminal']['receipt_ids'].pop()
        elif mutation == 'restored-old-pass':
            s['after_restore'] = copy.deepcopy(s['terminal'])
        else:
            s['receipts']['receipts'].pop(0)
        try:
            strict_runtime(changed, evidence)
        except (ValueError, InvalidSignature) as error:
            negatives.append({'mutation': mutation, 'rejected': True, 'error_type': type(error).__name__})
        else:
            raise ValueError('tampered cross-stage evidence accepted: ' + mutation)
    return {'baseline': baseline, 'latest_signed_revision_bound': True, 'negative_probes': negatives,
            'passed': True, 'scope': 'offline mutated copies only; no new runtime attacks or model calls'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
