"""Post-run raw command/receiver joins and negative evidence checks."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from enterprise_authority import VARIANTS, evaluate
from review_enterprise_chain import require
from review_enterprise_chain import review as review_chain


def review(run):
    base = review_chain(run)
    o = json.loads((run / 'backend-observations.json').read_text())
    require(all(evaluate(o).values()), 'authority checks failed')
    rows = [json.loads(s) for s in (run / 'events.jsonl').read_text().splitlines()]
    observed = {e['name']: e for e in rows if e['event'] == 'backend_observation'}
    root = run / 'backend-private'
    raw = [json.loads(s) for s in (root / 'events.jsonl').read_text().splitlines()]
    starts = {e['command_id']: e for e in raw if e['event'] == 'command_start'}
    ends = {e['command_id']: e for e in raw if e['event'] == 'command_end'}

    def capture(command_id, stream):
        value = (root / (command_id + '.' + stream)).read_bytes()
        require(hashlib.sha256(value).hexdigest() == ends[command_id][stream + '_sha256'], 'raw output digest differs')
        return value.decode()

    policies = {}
    for name in o:
        if not name.startswith('authority_') or not name.endswith(('_before_backend', '_after_backend')):
            continue
        candidates = [e for e in ends.values() if e['monotonic_ns'] < observed[name]['monotonic_ns']
                      and starts[e['command_id']]['argv'][-4:] == ['policy', 'get', o['effect_applied']['target'], '--full']]
        require(bool(candidates), 'no prior readback command')
        end = max(candidates, key=lambda e: e['monotonic_ns'])
        require(end['exit_code'] == 0 and capture(end['command_id'], 'stdout') == o[name]['raw_stdout'], 'raw policy readback differs')
        policies[name] = end['command_id']
    effects = {}
    for variant in VARIANTS:
        name = 'authority_rollback_' + variant
        r = o[name + '_effect']
        calls = [e for e in starts.values() if 'sandbox' in e['argv'] and 'exec' in e['argv'] and e['argv'][-1].endswith(r['business_path'])]
        require(len(calls) == 1, 'business execution not unique')
        call = calls[0]
        end = ends[call['command_id']]
        require(end['exit_code'] == r['exit_code'] and capture(call['command_id'], 'stdout') == r['stdout']
                and capture(call['command_id'], 'stderr') == r['stderr'], 'business raw output differs')
        logs = [e for e in starts.values() if e['argv'] == ['docker', 'logs', r['receiver_id']] and e['monotonic_ns'] > end['monotonic_ns']]
        require(bool(logs), 'no receiver log capture')
        log = min(logs, key=lambda e: e['monotonic_ns'])
        require(capture(log['command_id'], 'stdout') == r['receiver_stdout'], 'receiver raw log differs')
        controls = [e for e in starts.values() if e['argv'][:3] == ['docker', 'exec', r['receiver_id']] and r['control_path'] in e['argv'][-1]]
        require(len(controls) == 1 and ends[controls[0]['command_id']]['exit_code'] == r['control_exit_code'] == 0, 'health control differs')
        require(observed[name + '_after_backend']['monotonic_ns'] < controls[0]['monotonic_ns'] < call['monotonic_ns'] < end['monotonic_ns']
                < log['monotonic_ns'] < observed[name + '_effect']['monotonic_ns'], 'effect ordering differs')
        effects[name] = {'business_command': call['command_id'], 'receiver_command': log['command_id'], 'health_command': controls[0]['command_id'],
                         'exit_code': r['exit_code'], 'healthy': True, 'business_deliveries': 0}
    mutations = {
        'duplicate_accepted': lambda x: x.update(authority_duplicate_binding={'id': 'new'}),
        'impact_overclaimed': lambda x: x['authority_impact'].update(shared_runtime_occupants='all_known'),
        'wrong_registered_asset': lambda x: x['authority_impact']['registered_subject'].update(asset_id='other'),
        'state_mutated': lambda x: x['authority_preview_empty_after_state'].update(deployments=[['invented', 'effective']]),
        'backend_mutated': lambda x: x['authority_preview_shared_after_backend'].update(revision='invented'),
        'stale_preview_accepted': lambda x: x.update(authority_changed_submit={'id': 'invented'}),
        'fault_not_injected': lambda x: x.update(authority_preview_wrong_asset_catalog=copy.deepcopy(x['operator_assignment'])),
        'authority_not_restored': lambda x: x.update(authority_rollback_restored_sha256='invented'),
        'receiver_unhealthy': lambda x: x['authority_rollback_removed_effect'].update(control_exit_code=1),
        'other_receiver': lambda x: x['authority_rollback_removed_effect'].update(receiver_id='invented'),
        'audit_missing': lambda x: x.update(authority_rollback_removed_audit_after=x['authority_rollback_removed_audit_before']),
        'delivered_despite_denial': lambda x: x['authority_rollback_removed_effect'].update(receiver_stdout=x['authority_rollback_removed_effect']['receiver_stdout'].rstrip('\n') + '\n' + json.dumps({'path': x['authority_rollback_removed_effect']['business_path']})),
    }
    rejected = {}
    for name, mutate in mutations.items():
        altered = copy.deepcopy(o)
        mutate(altered)
        rejected[name] = not all(evaluate(altered).values())
    require(all(rejected.values()), 'false authority protection accepted')
    return {'base_chain': base, 'authority_readback_command_joins': policies, 'authority_effect_command_joins': effects,
            'actual_evidence_negative_rejections': rejected,
            'scope': 'author raw-command review after execution, not external witnessing or network packet capture'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    print(json.dumps(review(args.run), ensure_ascii=False, indent=2))
