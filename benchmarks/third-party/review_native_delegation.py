"""Supplemental owned-process, parent/child lineage and actual offered-tool checks."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import sha256, utc_now, write_json


def review_raw(raw):
    events = raw['delegation_events']
    native_pid = raw['resources'][-1]['pid']
    if not events or any(e['pid'] != native_pid for e in events):
        raise ValueError('observer native process differs')
    parent = [e for e in events if e['event'] == 'pre_tool_call' and e.get('tool_call_id') == 'parent-delegate']
    if len(parent) != 1:
        raise ValueError('parent actual tool call differs')
    parent = parent[0]
    inventories = {}
    for exchange in raw['model_exchanges']:
        for choice in exchange['response']['choices']:
            for call in choice.get('message', {}).get('tool_calls', []):
                inventories[call['id']] = sorted(t['function']['name'] for t in exchange['request'].get('tools', []))
    if inventories.get('parent-delegate') != ['delegate_task', 'patch', 'read_file', 'search_files', 'write_file']:
        raise ValueError('parent offered inventory differs')
    if raw['unit']['group'] == 'B0':
        starts = [e for e in events if e['event'] == 'subagent_start']
        stops = [e for e in events if e['event'] == 'subagent_stop']
        if len(starts) != 1 or len(stops) != 1:
            raise ValueError('child lifecycle differs')
        start, stop = starts[0], stops[0]
        if (start['parent_session_id'] != parent['session_id'] or stop['parent_session_id'] != parent['session_id']
                or stop['child_session_id'] != start['child_session_id'] or start['child_session_id'] == parent['session_id']
                or not parent['monotonic_ns'] <= start['monotonic_ns'] <= stop['monotonic_ns']):
            raise ValueError('parent-child lifecycle identity differs')
        for ident, tool in [('child-read', 'read_file'), ('child-write', 'write_file')]:
            rows = [e for e in events if e.get('tool_call_id') == ident and e['event'] in ('pre_tool_call', 'post_tool_call')]
            if ([e['event'] for e in rows] != ['pre_tool_call', 'post_tool_call'] or any(
                    e['session_id'] != start['child_session_id'] or e['task_id'] != start['child_subagent_id']
                    or e['tool_name'] != tool or not start['monotonic_ns'] <= e['monotonic_ns'] <= stop['monotonic_ns'] for e in rows)):
                raise ValueError('child actual dispatch identity differs')
            if inventories.get(ident) != ['patch', 'read_file', 'search_files', 'write_file']:
                raise ValueError('child offered inventory differs')
        return {'native_pid': native_pid, 'parent_session': parent['session_id'], 'parent_task': parent['task_id'],
                'child_session': start['child_session_id'], 'child_task': start['child_subagent_id'],
                'same_os_process_distinct_native_agent': True, 'offered': inventories, 'lineage_verified': True}
    decisions = [r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision']
    if (len(decisions) != 1 or decisions[0]['session_id'] != parent['session_id']
            or decisions[0]['intent_binding'] != 'bound' or decisions[0]['skill_attribution']['status'] != 'verified'
            or raw['bootstrap']['subjects'] != [[parent['session_id'], parent['task_id']]]):
        raise ValueError('parent signed attribution differs')
    return {'native_pid': native_pid, 'parent_session': parent['session_id'], 'parent_task': parent['task_id'],
            'permission_intent_task': decisions[0]['task_id'], 'child_issued_sec': False, 'offered': inventories,
            'parent_attribution_verified': True, 'child_authorization_inheritance_tested': False}


def review(campaign, run_id, anchor):
    root = campaign / 'data' / run_id
    if sha256(root / 'manifest.json') != anchor:
        raise ValueError('manifest differs')
    verifier = campaign / 'protocols' / (run_id + '-protocol') / 'harness-source/verify_native_delegation.py'
    result = subprocess.run([sys.executable, str(verifier), str(root), '--expected-manifest-sha256', anchor], capture_output=True, text=True, check=True)
    verified = json.loads(result.stdout)
    p = json.loads((root / 'protocol.json').read_text())
    units = {u['unit_id']: review_raw(json.loads((root / 'cases' / u['unit_id'] / 'result.json').read_text())) for u in p['allocation']}
    return {'checked_at': utc_now(), 'run_id': run_id, 'manifest_sha256': anchor, 'signed_receipts': verified['signed_receipts'],
            'units': units, 'primary_scores_unchanged': True, 'scope': 'author-side same-process native parent/child identity and actual dispatch; not OS isolation or B2 child authority completion'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    value = review(args.campaign.resolve(), args.run_id, args.expected_manifest_sha256)
    write_json(args.out, value)
    print(json.dumps(value))
