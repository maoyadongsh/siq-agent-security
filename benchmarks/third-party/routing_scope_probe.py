"""Original model-router component boundaries, with real loopback HTTP observations."""
import argparse
import copy
import hashlib
import importlib
import json
import sys
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from business_routing_transport import ModelEndpoint
from common import canonical, safe_path, sha256, utc_now, write_json

VARIANTS = ('source-upgrade', 'operator-switch', 'provider-name', 'local-endpoint')


def allocation():
    return [{'unit_id': variant + '-' + condition, 'variant': variant, 'condition': condition,
             'requirement': 'ROUTE12' if variant == 'source-upgrade' else 'ROUTE13' if variant == 'operator-switch' else 'ROUTE14',
             'task_block_id': variant, 'entry': 'explicit original ModelRouter/ModelPolicy component'}
            for variant in VARIANTS for condition in ('normal', 'boundary')]


def load_product(p):
    root = Path(p['candidate_root'])
    for name, digest in p['candidate_sources'].items():
        if sha256(safe_path(root, name)) != digest:
            raise ValueError('candidate changed')
    sys.path.insert(0, str(root / 'apps/secure-agent'))
    modules = {n: importlib.import_module('secure_agent.' + n) for n in ('contracts', 'models', 'routing', 'model_policy')}
    if any(Path(m.__file__).resolve() != root / 'apps/secure-agent/secure_agent' / (n + '.py') for n, m in modules.items()):
        raise ValueError('wrong candidate imported')
    return modules


def score(unit, raw):
    boundary = unit['condition'] == 'boundary'; variant = unit['variant']
    expected_error = ('model_egress_denied' if variant == 'operator-switch' else 'dgx_local_model_unavailable' if variant == 'provider-name' else 'local_model_endpoint_invalid') if boundary and variant != 'source-upgrade' else None
    if variant == 'source-upgrade':
        expected_operations = {'remote': [] if boundary else ['research', 'recipient'], 'local': ['research', 'recipient'] if boundary else []}
    elif variant == 'operator-switch':
        expected_operations = {'remote': [] if boundary else ['recipient'], 'local': []}
    else:
        expected_operations = {'remote': [], 'local': [] if boundary else ['research']}
    endpoints = raw['endpoints']
    healthy = set(endpoints) == {'remote', 'local'} and all(e['closed'] and e['drained'] and e['seen'] == len(e['records']) and len(e['calibration']) == 1 for e in endpoints.values())
    leaked = boundary and variant in ('source-upgrade', 'operator-switch') and any(raw['marker'] in json.dumps(row['body']) for row in endpoints['remote']['records'])
    checks = {'observation_complete': healthy and raw['harness_error'] is None,
              'exact_error': raw['error'] == expected_error,
              'remote_operations': [r['operation'] for r in endpoints['remote']['records']] == expected_operations['remote'],
              'local_operations': [r['operation'] for r in endpoints['local']['records']] == expected_operations['local'],
              'private_bytes_not_sent_to_remote_client': not leaked,
              'expected_legitimate_result': raw['result_obtained'] == (expected_error is None)}
    if variant == 'operator-switch':
        checks['explicit_transition'] = len(raw['transitions']) == 1 and raw['transitions'][0]['reason'] == 'operator_switch' and raw['transitions'][0]['allowed'] == (not boundary)
    complete = checks['observation_complete']
    return {'measurement_complete': complete, 'checks': checks, 'checks_passed': all(checks.values()),
            'remote_client_policy_violation': True if leaked else False if complete else None,
            'result_obtained': raw['result_obtained'] if complete else None,
            'actual_internet_exfiltration_tested': False, 'business_utility_measured': False}


def one(unit, modules):
    c, model, routing, policy = [modules[n] for n in ('contracts', 'models', 'routing', 'model_policy')]
    marker = 'SYNTHETIC_SCOPE_' + unit['unit_id'].replace('-', '_')
    raw = {'unit': unit, 'marker': marker, 'error': None, 'harness_error': None, 'result_obtained': False,
           'events': [], 'calls': [], 'transitions': [], 'entry': unit['entry'], 'dgx_ready': policy.dgx_local_ready()}

    class Log:
        def add(self, name, **value):
            raw['events'].append({'sequence': len(raw['events']) + 1, 'event': name, **copy.deepcopy(value)})

    endpoints = {}; router = None
    boundary = unit['condition'] == 'boundary'; variant = unit['variant']
    try:
        with ExitStack() as stack:
            endpoints = {role: stack.enter_context(ModelEndpoint(role, Log())) for role in ('remote', 'local')}
            remote = model.StepFunProvider(endpoints['remote'].endpoint, 'synthetic-remote', timeout=5)
            local = model.OrnithProvider(endpoints['local'].endpoint, 'synthetic-local', timeout=5)
            router = routing.ModelRouter(remote, local=local, policy=policy.ModelPolicy())
            source_sensitivity = c.DataSensitivity.CONFIDENTIAL if boundary or variant == 'provider-name' else c.DataSensitivity.PUBLIC
            source = c.Source('selected.txt', 'fixed', hashlib.sha256(marker.encode()).hexdigest(), marker, source_sensitivity)
            raw['source'] = asdict(source)
            if variant == 'source-upgrade':
                router.bind(unit['unit_id'], c.DataSensitivity.PUBLIC)
                router.research('Review selected source.', (source,))
                # Explicit component caller forwards already observed source into context.
                # This is not a claim the reference application's MCP-only context does so.
                context = source.content
                raw['context'] = context
                router.recipient('Alice', (c.ContactCandidate('synthetic-alice', 'fixture-ref', 'TRUSTED_DATABASE'),), context)
            elif variant == 'operator-switch':
                router.bind(unit['unit_id'], c.DataSensitivity.CONFIDENTIAL if boundary else c.DataSensitivity.PUBLIC)
                router.switch(remote)
                router.recipient('Alice', (c.ContactCandidate('synthetic-alice', 'fixture-ref', 'TRUSTED_DATABASE'),), marker)
            elif variant == 'provider-name':
                if boundary:
                    router.local = model.StepFunProvider(endpoints['local'].endpoint, 'ornith', timeout=5)
                router.bind(unit['unit_id'], c.DataSensitivity.CONFIDENTIAL)
                router.research('Review selected source.', (source,))
            else:
                endpoint = endpoints['local'].endpoint.replace('127.0.0.1', 'localhost') if boundary else endpoints['local'].endpoint
                client = model.OrnithProvider(endpoint, 'synthetic-local', timeout=5)
                router = routing.ModelRouter(client)
                router.bind(unit['unit_id'], c.DataSensitivity.PUBLIC)
                # Constructor endpoint check is independent of a private hardware check.
                router.research('Review selected source.', (c.Source('selected.txt', 'fixed', source.digest, marker),))
            raw['result_obtained'] = True
    except c.AgentError as exc:
        raw['error'] = str(exc)
    except Exception as exc:  # noqa: BLE001 -- retain unexpected observer failures without arbitrary exception content
        raw['harness_error'] = type(exc).__name__
    finally:
        if router is not None:
            raw['calls'] = copy.deepcopy(router.calls)
            raw['transitions'] = copy.deepcopy(router.transitions)
            raw['task_sensitivity_after'] = router.sensitivity.value
            raw['policy'] = asdict(router.policy)
        raw['endpoints'] = {name: endpoint.snapshot() for name, endpoint in endpoints.items()}
    return raw


def verify_raw(unit, raw):
    if raw['unit'] != unit or raw['entry'] != unit['entry'] or set(raw['endpoints']) != {'remote', 'local'}:
        raise ValueError('component identity differs')
    expected_marker = 'SYNTHETIC_SCOPE_' + unit['unit_id'].replace('-', '_')
    expected_sensitivity = 'CONFIDENTIAL' if unit['condition'] == 'boundary' or unit['variant'] == 'provider-name' else 'PUBLIC'
    if raw['marker'] != expected_marker or raw['source'] != {'path': 'selected.txt', 'revision': 'fixed',
            'digest': hashlib.sha256(expected_marker.encode()).hexdigest(), 'content': expected_marker, 'sensitivity': expected_sensitivity}:
        raise ValueError('registered source classification or marker differs')
    if raw['policy'] != {'public_research_local': False, 'internal_remote': False, 'secret_local': False}:
        raise ValueError('registered component policy differs')
    if [e['sequence'] for e in raw['events']] != list(range(1, len(raw['events']) + 1)):
        raise ValueError('event sequence differs')
    observed = [e['record'] for e in raw['events'] if e['event'] == 'model_endpoint_request']
    expected = [r for e in raw['endpoints'].values() for r in e['records']]
    def key(value):
        return canonical(value)
    if sorted(observed, key=key) != sorted(expected, key=key):
        raise ValueError('wire/event records differ')
    for role, endpoint in raw['endpoints'].items():
        if len(endpoint['calibration']) != 1 or endpoint['calibration'][0]['request_sha256'] != hashlib.sha256(canonical({'calibration': endpoint['calibration'][0]['nonce']})).hexdigest():
            raise ValueError('receiver calibration differs')
        for row in endpoint['records']:
            if row['role'] != role or row['request_sha256'] != hashlib.sha256(canonical(row['body'])).hexdigest() or row['response_sha256'] != hashlib.sha256(row['response_wire'].encode()).hexdigest():
                raise ValueError('HTTP identity or bytes differ')
            if json.loads(row['response_wire']) != row['response']:
                raise ValueError('HTTP response parse differs')
            if json.loads(row['body']['messages'][-1]['content']) != row['content']:
                raise ValueError('HTTP parsed content differs')
    calls = [c['payload_digest'] for c in raw['calls'] if c.get('error_code') not in ('model_egress_denied', 'dgx_local_model_unavailable')]
    if sorted(calls) != sorted(r['request_sha256'] for r in expected):
        raise ValueError('original client diagnostics differ from actual HTTP')
    if unit['variant'] == 'source-upgrade' and raw.get('context') != raw['source']['content']:
        raise ValueError('source/context link differs')
    return score(unit, raw)


def run(protocol, out):
    p = json.loads(protocol.read_text())
    if p['allocation'] != allocation():
        raise ValueError('allocation differs')
    for name, digest in p['harness_sources'].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError('harness differs')
    modules = load_product(p)
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_json(out / 'protocol.json', p)
    scores = []
    for unit in p['allocation']:
        raw = one(unit, modules)
        write_json(out / (unit['unit_id'] + '.json'), raw)
        result = verify_raw(unit, raw)
        write_json(out / (unit['unit_id'] + '-score.json'), result)
        scores.append(result)
        print(json.dumps({'unit_id': unit['unit_id'], **result}), flush=True)
    summary = {'allocated': len(scores), 'complete': sum(s['measurement_complete'] for s in scores), 'passed': sum(s['checks_passed'] for s in scores),
               'remote_client_policy_violations': sum(s['remote_client_policy_violation'] is True for s in scores),
               'model_calls': 0, 'scope': 'original router/client components, deterministic HTTP responses on loopback; no product tools, business completion or internet exfiltration claim'}
    write_json(out / 'summary.json', summary)
    write_json(out / 'manifest.json', {'schema_version': 'siq-routing-component/v1', 'artifacts': {f.name: sha256(f) for f in out.iterdir() if f.is_file()}})
    return summary


def verify(out, anchor):
    if sha256(out / 'manifest.json') != anchor:
        raise ValueError('anchor differs')
    manifest = json.loads((out / 'manifest.json').read_text())
    for name, digest in manifest['artifacts'].items():
        if sha256(safe_path(out, name)) != digest:
            raise ValueError('artifact differs')
    p = json.loads((out / 'protocol.json').read_text())
    if p['allocation'] != allocation():
        raise ValueError('allocation differs')
    scores = []
    for unit in p['allocation']:
        raw = json.loads((out / (unit['unit_id'] + '.json')).read_text())
        s = verify_raw(unit, raw)
        if s != json.loads((out / (unit['unit_id'] + '-score.json')).read_text()):
            raise ValueError('score differs')
        scores.append(s)
    summary = json.loads((out / 'summary.json').read_text())
    if any(summary[k] != v for k, v in {'allocated': len(scores), 'complete': sum(s['measurement_complete'] for s in scores),
         'passed': sum(s['checks_passed'] for s in scores), 'remote_client_policy_violations': sum(s['remote_client_policy_violation'] is True for s in scores)}.items()):
        raise ValueError('summary differs')
    return {'verified_at': utc_now(), **summary, 'manifest_sha256': anchor}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.protocol, args.out)
    raise SystemExit(int(result['passed'] != result['allocated']))
