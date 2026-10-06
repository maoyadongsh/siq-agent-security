"""Offline negative controls for a measured post-read runtime checkpoint."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

from bound_runtime_faults import checks
from cryptography.exceptions import InvalidSignature
from personal_onboarding_authority import require
from verify_bound_runtime_faults import joins, verify


def session_scope(obs):
    result = {}
    for name in ('grant-revoked', 'cancel'):
        row = obs['variants'][name]
        cid = row['plan']['check_id']
        first = next(r for r in row['receipts_before'] if r.get('agent_id') == 'rca-' + cid[3:] and r.get('tool_call_id') == 'rc-first')
        session = first['session_id']
        final = obs['receipts']['receipts']
        tail = [r for r in final[len(row['receipts_before']):] if r.get('session_id') == session]
        require(not any(r.get('action') == 'allow' for r in tail), 'session has new allow even if agent attribution absent')
        unattributed = [r for r in tail if r.get('agent_id') is None or r.get('tool_call_id') is None]
        result[name] = {'subsequent_session_receipts': len(tail), 'unattributed_receipt_ids': [r['receipt_id'] for r in unattributed],
                        'scope': 'session correlation only for pending rows; not full action/agent/Intent attribution'}
    return result


def strict(raw, evidence):
    result = joins(raw, evidence)
    require(all(checks(raw['runtime_check_observation']).values()), 'post-read fault acceptance differs')
    session_scope(raw['runtime_check_observation'])
    return result


def review(run, anchor):
    baseline = verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    spec = importlib.util.spec_from_file_location('bound_fault_evidence', source)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    raw = json.loads((run / 'cases/personal-onboarding-B2/result.json').read_text())
    strict(raw, evidence)
    probes = []
    for name in ('signed-revision', 'borrow-trigger', 'first-read-association', 'before-state-passed',
                 'revoke-other-grant', 'evaluator-kill-as-cancel', 'borrow-terminal', 'unattributed-allow'):
        modified = copy.deepcopy(raw)
        o = modified['runtime_check_observation']
        row = o['variants']['grant-revoked']
        if name == 'signed-revision':
            next(iter(o['records'].values()))['actor_id'] = 'other-operator'
        elif name == 'borrow-trigger':
            row['trigger_receipts'][0]['agent_id'] = 'other-agent'
        elif name == 'first-read-association':
            cid = row['plan']['check_id']
            next(r for r in row['receipts_before'] if r.get('agent_id') == 'rca-' + cid[3:] and r['record_type'] == 'observation')['decision_receipt_id'] = 'other-decision'
        elif name == 'before-state-passed':
            row['before_injection']['status'] = 'passed'
        elif name == 'revoke-other-grant':
            row['grant_after_revoke']['grant']['grant_id'] = 'other-grant'
        elif name == 'evaluator-kill-as-cancel':
            o['variants']['cancel']['intervention_cleanup'] = True
        elif name == 'unattributed-allow':
            next(r for r in o['receipts']['receipts'] if r.get('agent_id') is None)['action'] = 'allow'
        else:
            o['variants']['cancel']['terminal'] = copy.deepcopy(o['variants']['recovery']['terminal'])
        try:
            strict(modified, evidence)
        except (ValueError, InvalidSignature) as error:
            probes.append({'mutation': name, 'rejected': True, 'error_type': type(error).__name__})
        else:
            raise ValueError('modified evidence accepted: ' + name)
    return {'baseline': baseline, 'negative_probes': probes, 'passed': True,
            'session_scope': session_scope(raw['runtime_check_observation']),
            'scope': 'offline evidence mutations; not additional real attacks'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
