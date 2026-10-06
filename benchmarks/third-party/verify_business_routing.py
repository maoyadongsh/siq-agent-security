"""Recompute original-application routing, actual HTTP observations and signed tool effects."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from business_routing_scoring import score
from common import canonical, safe_path, sha256
from lifecycle import project, summarize


def params_digest(params):
    encoded = canonical(params).decode()
    for text, escaped in (('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')):
        encoded = encoded.replace(text, escaped)
    return hashlib.sha256(encoded.encode()).hexdigest()


def verify(run, anchor):
    if sha256(run / 'manifest.json') != anchor:
        raise ValueError('manifest differs')
    manifest = json.loads((run / 'manifest.json').read_text())
    for name, digest in manifest['artifacts'].items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError('artifact differs')
    p, states, _, _ = project(run)
    if p['operation'] != 'original_application_model_routing':
        raise ValueError('routing protocol required')
    if 'application_candidate_source_digest' in p:
        digest = hashlib.sha256(json.dumps(p['candidate_sources'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != p['application_candidate_source_digest']:
            raise ValueError('application candidate identity differs')
    for field, root in [('candidate_sources', Path(p['candidate_root'])), ('harness_sources', Path(__file__).parent)]:
        if any(sha256(safe_path(root, name)) != digest for name, digest in p[field].items()):
            raise ValueError('frozen source differs: ' + field)
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    if sha256(source) != p['candidate_sources']['benchmarks/runtime-security/evidence.py']:
        raise ValueError('trusted verifier changed')
    spec = importlib.util.spec_from_file_location('routing_signatures', source)
    signatures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signatures)
    calibration = json.loads((run / 'calibration.json').read_text())
    if not calibration['passed'] or calibration['counts'] != [0, 1, 2] or len(calibration['wire']) != 2:
        raise ValueError('receiver calibration failed')
    for i, event in enumerate(calibration['wire']):
        body = 'evaluation receiver calibration ' + str(i)
        if event['status'] != 201 or event['payload_sha256'] != hashlib.sha256(body.encode()).hexdigest():
            raise ValueError('receiver calibration material differs')
    units, signed = {}, 0
    for unit in p['allocation']:
        prefix = 'cases/' + unit['unit_id']
        if not {prefix + '/' + n for n in ('result.json', 'score.json', 'events.jsonl', 'resources.json')} <= manifest['artifacts'].keys():
            raise ValueError('allocated capture missing')
        raw = json.loads((run / prefix / 'result.json').read_text())
        calculated = score(p, unit, raw)
        if raw['unit'] != unit or calculated != json.loads((run / prefix / 'score.json').read_text()):
            raise ValueError('allocation or score differs')
        if any(states[unit['unit_id'] + '#1'][k] != calculated[k] for k in ('harm_observed', 'utility_completed', 'cleanup_confirmed')):
            raise ValueError('journal differs')
        records, count = signatures.verify_receipt_bundles([raw['public_evidence']])
        signed += count
        for row in raw['decisions']:
            request, decision = row['request'], row['decision']
            signed_record = records[decision['receipt_id']][0]
            if any(signed_record.get(k) != decision.get(k) for k in ('action_id', 'action', 'reason_code', 'task_id')):
                raise ValueError('decision differs from signed record')
            if (params_digest(request['params']) != signed_record['params_digest']
                    or any(request[k] != signed_record[k] for k in ('tool', 'tool_call_id', 'platform', 'session_id', 'agent_id'))):
                raise ValueError('original tool request binding differs')
        for tool in raw['tools']:
            decision = records[tool['receipt_id']][0]
            if decision['action'] != 'allow' or tool['tool'] != decision['tool'] or params_digest(tool['params']) != decision['params_digest']:
                raise ValueError('actual tool dispatch not bound to allow')
        for action in (raw.get('application_result') or {}).get('task', {}).get('actions', []):
            if action.get('effect'):
                signatures.verify_effect_envelope(action['effect'], records)
        events = [json.loads(line) for line in (run / prefix / 'events.jsonl').read_text().splitlines()]
        if [e['sequence'] for e in events] != list(range(1, len(events) + 1)):
            raise ValueError('event sequence differs')
        for event, field in [('actual_decision', 'decisions'), ('receiver_request', 'wire'), ('actual_tool_finished', 'tools'), ('execution_file_observed', 'files')]:
            observed = [e for e in events if e['event'] == event]
            # Nested tool executions finish before their parent executor.
            keys = tuple(raw[field][0]) if raw[field] else ()
            def key(row, keys=keys):
                return canonical({k: row[k] for k in keys})
            expected_rows = sorted(raw[field], key=key)
            observed = sorted(observed, key=key)
            if len(observed) != len(expected_rows) or [{k: e[k] for k in r} for e, r in zip(observed, expected_rows, strict=True)] != expected_rows:
                raise ValueError('event material differs: ' + field)
        captures = [e for e in events if e['event'] == 'routing_capture_finished']
        if len(captures) != 1 or captures[0]['model_calls'] != raw['model_calls'] or captures[0]['provider_transitions'] != raw['provider_transitions']:
            raise ValueError('routing diagnostics differ from events')
        for role in ('remote', 'local'):
            seen = [e['record'] for e in events if e['event'] == 'model_endpoint_request' and e['record']['role'] == role]
            if seen != raw['model_endpoints'][role]['records']:
                raise ValueError('model wire capture differs from events')
        if p['cases'][unit['case_id']].get('tcp_refused'):
            refusal = raw.get('tcp_refusal', {})
            for event, field, keys in [('refused_tcp_probe', 'probes', ('phase', 'errno')),
                                       ('refused_tcp_connect', 'attempts', ('phase', 'address'))]:
                observed = [{key: row[key] for key in keys} for row in events if row['event'] == event]
                if observed != refusal.get(field):
                    raise ValueError('TCP refusal evidence differs from events')
        all_rows = [row for endpoint in raw['model_endpoints'].values() for row in endpoint['records']]
        if p.get('generation_override', {}).get('remote_response_format') == 'json_schema':
            names = {'plan': 'model-task-plan-v2', 'research': 'model-research-proposal', 'recipient': 'model-recipient-selection'}
            for row in raw['model_endpoints']['remote']['records']:
                name = names[row['operation']]
                schema = json.loads((Path(p['candidate_root']) / 'packages/contracts' / (name + '.schema.json')).read_text())
                if row['body']['response_format'] != {'type': 'json_schema', 'json_schema': {'name': name, 'strict': True, 'schema': schema}}:
                    raise ValueError('structured request schema differs from original contract')
        for call in raw['model_calls']:
            matches = [r for r in all_rows if r['request_sha256'] == call.get('payload_digest')]
            if matches and any(r['role'] != {'stepfun': 'remote', 'ornith': 'local'}[call['provider']] for r in matches):
                raise ValueError('provider diagnostic attributed to wrong endpoint')
        if raw['entry'] != 'SecureApplication(original_provider)':
            raise ValueError('wrong application entry')
        budget = raw['budget_after']
        if budget['requests'] > p['limits']['max_requests'] or any(n > 3 for n in budget['by_unit'].values()):
            raise ValueError('request budget exceeded')
        if budget['reserved'] > p['limits']['byte_plus_output_token_reservation']:
            raise ValueError('reservation budget exceeded')
        expected_status = 'determinate' if calculated['measurement_complete'] else 'indeterminate'
        expected_assertion = 'pass' if calculated['measurement_complete'] and calculated['checks_passed'] else 'fail' if calculated['measurement_complete'] else 'inconclusive'
        if states[unit['unit_id'] + '#1']['measurement_status'] != expected_status or states[unit['unit_id'] + '#1']['assertion_status'] != expected_assertion:
            raise ValueError('journal measurement/assertion differs')
        units[unit['unit_id']] = calculated
    summary = summarize(states)
    saved = json.loads((run / 'summary.json').read_text())
    if any(saved[k] != v for k, v in summary.items()):
        raise ValueError('summary differs')
    return {**summary, 'signed_receipts': signed, 'manifest_sha256': anchor, 'units': units,
            'scope': 'author-side original model client, HTTP capture and signed application evidence; no external certification'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
