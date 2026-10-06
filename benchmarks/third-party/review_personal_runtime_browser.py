"""Offline tamper controls for complete actual browser and signed API evidence."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

import verify_personal_runtime_browser as original_verifier
from cryptography.exceptions import InvalidSignature
from personal_onboarding_authority import require
from personal_runtime_browser_trial import score
from verify_personal_runtime_browser import PROJECTION_FIELDS, verify_projection

original_joins = original_verifier.verify_joins


def verify_joins(o, evidence):
    receipts, _ = evidence.verify_receipt_bundles([o['receipts']])
    selected = [receipts[rid][0] for rid in o['passed']['receipt_ids']]
    verify_projection(o['activity_detail']['receipts'], selected)
    # Future protocols have the corrected projection comparator. Historical
    # 003 is verified only with its separately frozen supplementary tool.
    result = original_joins(o, evidence)
    result['activity_projection_fields_verified'] = list(PROJECTION_FIELDS)
    return result


def strict(o, evidence):
    result = verify_joins(o, evidence)
    require(score(o)['all_passed'], 'browser/API acceptance differs')
    return result


def review(run, anchor):
    previous = original_verifier.verify_joins
    original_verifier.verify_joins = verify_joins
    try:
        baseline = original_verifier.verify(run, anchor)
    finally:
        original_verifier.verify_joins = previous
    p = json.loads((run / 'protocol.json').read_text())
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    spec = importlib.util.spec_from_file_location('browser_runtime_tamper_evidence', source)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    original = json.loads((run / 'browser-observations.json').read_text())
    strict(original, evidence)
    probes = []
    for name in ('signed-revision', 'activity-task-swap', 'borrowed-receipt', 'different-unknown-reason',
                 'UI-false-verified', 'revive-old-pass', 'duplicate-browser-start',
                 'projection-action', 'projection-sequence'):
        o = copy.deepcopy(original)
        if name == 'signed-revision':
            next(iter(o['records'].values()))['actor_id'] = 'other-operator'
        elif name == 'activity-task-swap':
            o['activity_reference']['activity']['binding']['task_id'] = 'other-task'
        elif name == 'borrowed-receipt':
            o['activity_detail']['receipts'][0]['receipt_id'] = 'other-receipt'
        elif name == 'different-unknown-reason':
            o['security_view']['actual_result']['reason_code'] = 'intent_missing'
        elif name == 'UI-false-verified':
            o['stages']['activity-detail']['text'] = '结果核验通过'
        elif name == 'revive-old-pass':
            o['restored'] = copy.deepcopy(o['passed'])
        elif name == 'projection-action':
            o['activity_detail']['receipts'][0]['action'] = 'deny'
        elif name == 'projection-sequence':
            o['activity_detail']['receipts'].reverse()
        else:
            o['browser']['responses'].append(copy.deepcopy(next(r for r in o['browser']['responses'] if r['path'] == '/v1/runtime-checks/start' and r['status'] == 202)))
        try:
            strict(o, evidence)
        except (ValueError, InvalidSignature) as error:
            probes.append({'mutation': name, 'rejected': True, 'error_type': type(error).__name__})
        else:
            raise ValueError('tampered browser evidence accepted: ' + name)
    return {'baseline': baseline, 'negative_probes': probes, 'passed': True,
            'scope': 'offline copied evidence, not additional runtime attacks or model trials'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
