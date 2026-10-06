"""Join deployed effects to actual CLI files and receiver logs; keep scope explicit."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from common import sha256
from enterprise_native_edge import CONFIG
from enterprise_native_edge import evaluate as native_score
from enterprise_runtime import evaluate as effect_score


def require(ok, message):
    if not ok:
        raise ValueError(message)


def review(run):
    o = json.loads((run / 'backend-observations.json').read_text())
    native = json.loads((run / 'native-enterprise-observations.json').read_text())
    require(all(effect_score(o).values()) and all(native_score(native).values()), 'specialized checks failed')
    events = [json.loads(s) for s in (run / 'events.jsonl').read_text().splitlines()]
    backend = run / 'backend-private'
    raw_events = [json.loads(s) for s in (backend / 'events.jsonl').read_text().splitlines()]
    starts = [e for e in raw_events if e['event'] == 'command_start']
    ends = {e['command_id']: e for e in raw_events if e['event'] == 'command_end'}
    output = {}
    for phase in ('before', 'applied', 'rolled_back'):
        r = o['effect_' + phase]
        calls = [e for e in starts if 'sandbox' in e['argv'] and 'exec' in e['argv'] and e['argv'][-1].endswith(r['business_path'])]
        require(len(calls) == 1, 'business execution is not unique')
        call = calls[0]
        end = ends[call['command_id']]
        stdout = (backend / (call['command_id'] + '.stdout')).read_bytes()
        stderr = (backend / (call['command_id'] + '.stderr')).read_bytes()
        require(end['exit_code'] == r['exit_code'] and stdout.decode() == r['stdout'] and stderr.decode() == r['stderr'], 'CLI projection differs')
        require(hashlib.sha256(stdout).hexdigest() == end['stdout_sha256'] and hashlib.sha256(stderr).hexdigest() == end['stderr_sha256'], 'CLI digest differs')
        log_calls = [e for e in starts if e['argv'] == ['docker', 'logs', r['receiver_id']] and e['monotonic_ns'] > end['monotonic_ns']]
        require(bool(log_calls), 'missing receiver log command')
        capture = min(log_calls, key=lambda e: e['monotonic_ns'])
        log_raw = (backend / (capture['command_id'] + '.stdout')).read_bytes()
        require(log_raw.decode() == r['receiver_stdout'] and hashlib.sha256(log_raw).hexdigest() == ends[capture['command_id']]['stdout_sha256'], 'receiver projection differs')
        before = next(e for e in events if e['event'] == 'backend_observation' and e['name'] == phase)
        after = next(e for e in events if e['event'] == 'backend_observation' and e['name'] == 'effect_' + phase)
        require(before['monotonic_ns'] < call['monotonic_ns'] < end['monotonic_ns'] < capture['monotonic_ns'] < after['monotonic_ns'], 'policy/effect ordering differs')
        output[phase] = {'command_id': call['command_id'], 'exit_code': r['exit_code'], 'stdout': r['stdout'], 'stderr': r['stderr'], 'receiver_command_id': capture['command_id'],
                         'receiver_stdout': log_raw.decode(), 'receiver_sha256': hashlib.sha256(log_raw).hexdigest(), 'policy_readback_before_execution': True}
    source = run / 'native-edge-private/home/.hermes/profiles/enterprise-native-fixture/config.yaml'
    require(sha256(source) == hashlib.sha256(CONFIG).hexdigest() == native['source_after'], 'archived native source differs')
    for name in ('register', 'tasks'):
        for stream in ('stdout', 'stderr'):
            require(sha256(run / 'native-edge-private' / (name + '.' + stream)) == native[name][stream + '_sha256'], 'native CLI capture differs')
    require(native['ephemeral_root_removed'] is True and not Path(native['ephemeral_root']).exists(), 'native temporary directory remains')
    require(o['operator_assignment']['assignments'][0]['asset_id'] == native['asset']['id'], 'different asset deployed')
    mutations = {
        'delivered_under_restriction': lambda x: x['effect_applied'].update(receiver_stdout=x['effect_applied']['receiver_stdout'].rstrip('\n') + '\n' + json.dumps({'path': x['effect_applied']['business_path']})),
        'receiver_unhealthy': lambda x: x['effect_applied'].update(control_exit_code=1),
        'false_cli_allow': lambda x: x['effect_applied'].update(exit_code=0),
        'wrong_return_body': lambda x: x['effect_before'].update(stdout='wrong'),
        'other_receiver': lambda x: x['effect_rolled_back'].update(receiver_id='borrowed'),
        'other_target': lambda x: x['effect_rolled_back'].update(target='borrowed'),
    }
    rejected = {}
    for name, mutate in mutations.items():
        altered = copy.deepcopy(o)
        mutate(altered)
        rejected[name] = not all(effect_score(altered).values())
    require(all(rejected.values()), 'false effect accepted')
    return {'raw_execution_receiver_joins': output, 'native_source_and_cli_hashes': True, 'native_asset_to_deployment_join': True, 'native_temp_removed': True,
            'negative_rejections': rejected, 'scope': 'post-run author-side raw material review; neither external witness nor packet capture; original frozen scoring unchanged'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    print(json.dumps(review(args.run)))
