"""Bounded provider format diagnosis using an unchanged, synthetic original planner request."""
import argparse
import copy
import hashlib
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

from business_routing_transport import forward
from common import canonical, safe_path, sha256, utc_now, write_json


def request_for(p, mode):
    body = copy.deepcopy(p['original_request'])
    if mode == 'text':
        body.pop('response_format')
    elif mode == 'json_schema':
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'model-task-plan-v2', 'strict': True, 'schema': p['schema']}}
    elif mode != 'json_object':
        raise ValueError('unknown format')
    return body


def load_contract(p):
    candidate = Path(p['candidate_root'])
    for name, digest in p['candidate_sources'].items():
        if sha256(safe_path(candidate, name)) != digest:
            raise ValueError('candidate source differs')
    sys.path.insert(0, str(candidate / 'apps/secure-agent'))
    module = importlib.import_module('secure_agent.contracts')
    if Path(module.__file__).resolve() != candidate / 'apps/secure-agent/secure_agent/contracts.py':
        raise ValueError('wrong candidate contract import')
    return module


def evaluate(contract, row):
    result = {'http_ok': row.get('status') == 200, 'json_valid': False, 'contract_valid': False,
              'contract_error': None, 'usage': None, 'finish_reason': None}
    if row.get('response') is None:
        return result
    try:
        envelope = json.loads(row['response'])
        result['usage'] = envelope.get('usage')
        choice = envelope['choices'][0]
        result['finish_reason'] = choice.get('finish_reason')
        parsed = contract.strict_json(choice['message']['content'])
        result['json_valid'] = True
        contract.TaskPlan.parse(parsed)
        result['contract_valid'] = True
    except contract.AgentError as exc:
        result['contract_error'] = str(exc)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        result['contract_error'] = type(exc).__name__
    return result


def run(protocol, out):
    p = json.loads(protocol.read_text())
    for name, digest in p['harness_sources'].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError('harness differs')
    contract = load_contract(p)
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_json(out / 'protocol.json', p)
    deadline = time.monotonic() + p['limits']['total_seconds']
    rows = []
    for unit in p['allocation']:
        request = request_for(p, unit['mode'])
        row = {'unit': unit, 'request': request, 'request_sha256': hashlib.sha256(canonical(request)).hexdigest(),
               'started_ns': time.monotonic_ns(), 'status': None, 'response': None, 'error_type': None, 'attempted': False}
        remaining = deadline - time.monotonic()
        if remaining <= 2:
            row['error_type'] = 'total_deadline_exhausted'
        else:
            row['attempted'] = True
            try:
                row['status'], response = forward(p['upstream'], canonical(request), min(p['limits']['request_seconds'], remaining - 2))
                row['response'] = response.decode()
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                row['error_type'] = type(exc).__name__
        row['finished_ns'] = time.monotonic_ns()
        row['score'] = evaluate(contract, row)
        write_json(out / (unit['unit_id'] + '.json'), row)
        rows.append(row)
        print(json.dumps({'unit': unit['unit_id'], **row['score']}), flush=True)
    summary = {'allocated': len(rows), 'attempted': sum(r['attempted'] for r in rows),
               'contract_valid': sum(r['score']['contract_valid'] for r in rows),
               'no_product_execution': True, 'no_business_utility_claim': True,
               'scope': 'six paired synthetic provider requests, exploratory diagnosis; not independent confirmation or task success'}
    write_json(out / 'summary.json', summary)
    write_json(out / 'manifest.json', {'schema_version': 'siq-step-format-diagnosis/v1', 'artifacts': {f.name: sha256(f) for f in out.iterdir() if f.is_file()}})
    return summary


def verify(out, anchor):
    if sha256(out / 'manifest.json') != anchor:
        raise ValueError('anchor differs')
    m = json.loads((out / 'manifest.json').read_text())
    for name, digest in m['artifacts'].items():
        if sha256(safe_path(out, name)) != digest:
            raise ValueError('artifact differs')
    p = json.loads((out / 'protocol.json').read_text())
    contract = load_contract(p)
    rows = []
    for unit in p['allocation']:
        r = json.loads((out / (unit['unit_id'] + '.json')).read_text())
        if r['unit'] != unit or r['request'] != request_for(p, unit['mode']) or r['score'] != evaluate(contract, r):
            raise ValueError('format allocation/request/score differs')
        if r['request_sha256'] != hashlib.sha256(canonical(r['request'])).hexdigest() or r['finished_ns'] <= r['started_ns']:
            raise ValueError('request identity or timing differs')
        rows.append(r)
    summary = json.loads((out / 'summary.json').read_text())
    if (summary['allocated'], summary['attempted'], summary['contract_valid']) != (len(rows), sum(r['attempted'] for r in rows), sum(r['score']['contract_valid'] for r in rows)):
        raise ValueError('summary differs')
    if len(rows) > p['limits']['max_requests'] or rows[-1]['finished_ns'] - rows[0]['started_ns'] > (p['limits']['total_seconds'] + 2) * 10**9:
        raise ValueError('budget differs')
    return {'checked_at': utc_now(), **summary, 'by_mode': {mode: [r['score'] for r in rows if r['unit']['mode'] == mode] for mode in ('json_object', 'text', 'json_schema')}, 'manifest_sha256': anchor}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.protocol, args.out)
