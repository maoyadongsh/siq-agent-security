"""Reject copied fault evidence tampering; never mutate measured files."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from native_runtime_faults import checks
from personal_onboarding_authority import require
from verify_native_runtime_faults import joins, verify


def strict(raw, evidence):
    result = joins(raw, evidence)
    require(all(checks(raw['runtime_check_observation']).values()), 'fault acceptance differs')
    return result


def review(run, anchor):
    baseline = verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    spec = importlib.util.spec_from_file_location('fault_negative_evidence', source)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    raw = json.loads((run / 'cases/personal-onboarding-B2/result.json').read_text())
    strict(raw, evidence)
    probes = []
    for name in ('signed-revision', 'wrong-terminal', 'revoke-other-grant', 'borrow-recovery-receipt',
                 'evaluator-kill-as-timeout', 'business-grant-changed', 'premature-timeout'):
        altered = copy.deepcopy(raw)
        o = altered['runtime_check_observation']
        if name == 'signed-revision':
            next(iter(o['records'].values()))['actor_id'] = 'other-operator'
        elif name == 'wrong-terminal':
            o['variants']['timeout']['terminal'] = copy.deepcopy(o['variants']['recovery']['terminal'])
        elif name == 'revoke-other-grant':
            o['variants']['grant-revoked']['grant_after_revoke']['grant']['grant_id'] = 'another-grant'
        elif name == 'borrow-recovery-receipt':
            o['variants']['recovery']['terminal']['receipt_ids'][0] = raw['receipts']['receipts'][0]['receipt_id']
        elif name == 'evaluator-kill-as-timeout':
            o['variants']['timeout']['intervention_cleanup'] = True
        elif name == 'business-grant-changed':
            original = o['business_grants'][0]['grant_id']
            next(g for g in o['variants']['recovery']['grants']['grants'] if g['grant_id'] == original)['status'] = 'revoked'
        else:
            o['variants']['timeout']['elapsed_seconds'] = 1
        try:
            strict(altered, evidence)
        except (ValueError, InvalidSignature) as error:
            probes.append({'mutation': name, 'rejected': True, 'error_type': type(error).__name__})
        else:
            raise ValueError('modified evidence accepted: ' + name)
    return {'baseline': baseline, 'negative_probes': probes, 'passed': True,
            'scope': 'offline copied evidence, not additional product attacks'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
