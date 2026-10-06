"""Original application confidentiality flags and actual refused TCP connection."""
import argparse
import copy
import errno
import json
import os
import shutil
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import business_routing_trial as base
from business_routing_scoring import score as original_score
from common import sha256, utc_now, write_json

base_one = base.one
base_environment = base.application_environment
active_capture = None
hook_installed = False


def audit(event, args):
    if event == 'socket.connect' and active_capture is not None:
        address = args[1]
        if tuple(address) == tuple(active_capture['reserved_address']):
            active_capture['connect_attempts'].append({'address': list(address), 'monotonic_ns': time.monotonic_ns(),
                                                       'pid': os.getpid(), 'event': event})


def cases():
    def row(policy, refused=False):
        return {'sensitivity': 'CONFIDENTIAL', 'remote': ['plan'], 'local': [] if refused else ['research', 'recipient'],
                'error': 'model_request_failed' if refused else None, 'utility': not refused, 'policy': policy,
                'output': 'delivery', 'tcp_refused': refused}
    return {'confidential-flags-control': row({'public_research_local': False}),
            'confidential-internal-remote': row({'public_research_local': False, 'internal_remote': True}),
            'local-tcp-control': row({}), 'local-tcp-refused': row({}, True)}


def allocation():
    return [{'unit_id': n, 'case_id': n, 'pair_id': 'flags' if n.startswith('confidential') else 'tcp',
             'task_block_id': 'flags' if n.startswith('confidential') else 'tcp', 'track': 'B', 'group': 'B2',
             'family_id': 'IN02', 'claim_ids': ['C1', 'C2'], 'product_group_ids': ['R07', 'E01']} for n in cases()]


def validate_protocol(p):
    if (p['allocation'] != allocation() or p['cases'] != cases() or p['mode'] != 'controls'
            or Path(p['candidate_root']).name != '5470ab3780f2-routingscopefix1'):
        raise ValueError('edge protocol differs')


def probe(sock):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        return {'connect_errno': client.connect_ex(sock.getsockname()),
                'reserved_socket_accepting': sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN),
                'reserved_address': list(sock.getsockname())}


def transport_proof(raw, refused):
    value = raw['transport_observation']
    target = value['reserved_address']
    probes = all(value[k] == {'connect_errno': errno.ECONNREFUSED, 'reserved_socket_accepting': 0,
                             'reserved_address': target} for k in ('before', 'after'))
    attempts = value['connect_attempts']
    attempts_ok = (len(attempts) == int(refused) and all(x['address'] == target and x['event'] == 'socket.connect'
        and x['pid'] == value['pid'] and value['start_ns'] <= x['monotonic_ns'] <= value['end_ns'] for x in attempts))
    endpoint = f'http://{target[0]}:{target[1]}/v1' if refused else raw['model_endpoints']['local']['endpoint']
    return (probes and attempts_ok and value['configured_endpoint'] == endpoint
            and target[0] == '127.0.0.1' and 0 < target[1] < 65536 and value['reserved_socket_closed'] is True)


def score(p, unit, raw):
    refused = p['cases'][unit['case_id']]['tcp_refused']
    proof = transport_proof(raw, refused)
    wire = [r for e in raw['model_endpoints'].values() for r in e['records']]
    missing = [c for c in raw['model_calls'] if not any(c.get('payload_digest') == r['request_sha256'] for r in wire)]
    expected_missing = (len(missing) == 1 and missing[0]['provider'] == 'ornith' and missing[0]['operation'] == 'research'
                        and missing[0]['status'] == 'failed' and missing[0]['error_code'] == 'model_request_failed') if refused else not missing
    normalized = copy.deepcopy(raw)
    # A refused TCP connection sends no HTTP body. Account for the single original
    # diagnostic only with an independently recorded socket attempt and refusal probes.
    # Original raw calls and events are retained unchanged and separately verified.
    if refused and proof and expected_missing:
        normalized['model_calls'] = [c for c in raw['model_calls'] if c not in missing]
    result = original_score(p, unit, normalized)
    result['checks'].update(actual_tcp_boundary_verified=bool(proof), exactly_accounted_pre_http_attempt=bool(expected_missing))
    complete = result['measurement_complete'] and proof and expected_missing
    result['measurement_complete'] = bool(complete)
    result['checks_passed'] = all(result['checks'].values())
    if not complete:
        result['harm_observed'] = True if result['harm_observed'] is True else None
        result['utility_completed'] = None
    result['pre_http_attempts'] = len(missing)
    result['scope'] = 'original application, controlled model HTTP and real TCP refusal; audit observes pre-connect attempt, not packet capture or process isolation'
    return result


def one(p, unit, out, benchmark, budget):
    global active_capture, hook_installed
    if not hook_installed:
        sys.addaudithook(audit)
        hook_installed = True
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))  # held throughout; never listen, no free-port race
    observation = {'reserved_address': list(sock.getsockname()), 'pid': os.getpid(), 'connect_attempts': [],
                   'before': probe(sock), 'start_ns': time.monotonic_ns()}

    @contextmanager
    def environment(setting, endpoint, model, path):
        if setting['tcp_refused']:
            endpoint = f'http://127.0.0.1:{sock.getsockname()[1]}/v1'
        observation['configured_endpoint'] = endpoint
        with base_environment(setting, endpoint, model, path) as value:
            yield value

    previous = base.application_environment
    base.application_environment = environment
    active_capture = observation
    try:
        raw = base_one(p, unit, out, benchmark, budget)
    finally:
        active_capture = None
        base.application_environment = previous
        observation['end_ns'] = time.monotonic_ns()
        try:
            observation['after'] = probe(sock)
        finally:
            sock.close()
        observation['reserved_socket_closed'] = sock.fileno() == -1
    raw['transport_observation'] = observation
    path = out / 'cases' / unit['unit_id'] / 'events.jsonl'
    count = len(path.read_text().splitlines())
    with path.open('a') as stream:
        stream.write(json.dumps({'sequence': count + 1, 'run_id': unit['unit_id'], 'pid': os.getpid(), 'utc': utc_now(),
                                 'monotonic_ns': time.monotonic_ns(), 'event': 'tcp_boundary_observed', 'record': observation}) + '\n')
    write_json(path.parent / 'result.json', raw, exclusive=False)
    return raw


def freeze(campaign, name):
    if Path(name).name != name:
        raise ValueError('invalid run ID')
    old = campaign / 'protocols/business-alias-controls-001-protocol'
    p = json.loads((old / 'protocol.json').read_text())
    p.pop('alias_contract')
    root = campaign / 'protocols' / (name + '-protocol'); root.mkdir()
    shutil.copytree(old / 'harness-source', root / 'harness-source', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for n in ('business_routing_edges.py', 'verify_business_routing_edges.py'):
        shutil.copyfile(Path(__file__).parent / n, root / 'harness-source' / n)
    p.update(run_id=name, frozen_at=utc_now(), allocation=allocation(), cases=cases())
    p['limits']['max_requests'] = 12
    p['edge_contract'] = {'entry': 'original SecureApplication; no provider or socket method replacement',
        'tcp': 'held bound non-listening loopback socket; ECONNREFUSED probes outside observation window; Python audit captures original connect attempt; no HTTP body expected',
        'flags': 'CONFIDENTIAL stays local even when INTERNAL remote allowed and public local preference disabled',
        'limits': 'four controls, two same-template pairs; zero inference; not independent confirmation'}
    p['harness_sources'] = {str(f.relative_to(root / 'harness-source')): sha256(f) for f in (root / 'harness-source').rglob('*') if f.is_file()}
    write_json(root / 'protocol.json', p)
    return root / 'protocol.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'run'])
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--protocol', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        print(freeze(args.campaign.resolve(), args.run_id))
    else:
        validate_protocol(json.loads(args.protocol.read_text()))
        base.one, base.score = one, score
        raise SystemExit(base.run(args.protocol))
