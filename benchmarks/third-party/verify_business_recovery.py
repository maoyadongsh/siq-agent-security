"""Recompute recovery effects, original application results, signatures and request bindings."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from business_recovery_scoring import score
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
    if p['operation'] != 'original_application_pii_recovery':
        raise ValueError('recovery protocol required')
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    if sha256(source) != p['candidate_sources']['benchmarks/runtime-security/evidence.py']:
        raise ValueError('trusted verifier changed')
    spec = importlib.util.spec_from_file_location('recovery_signatures', source)
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
        for stage in raw['stages']:
            for action in (stage.get('result') or {}).get('task', {}).get('actions', []):
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
        if [e['stage'] for e in events if e['event'] == 'stage_finished'] != raw['stages']:
            raise ValueError('stage result differs from events')
        units[unit['unit_id']] = calculated
    summary = summarize(states)
    saved = json.loads((run / 'summary.json').read_text())
    if any(saved[k] != v for k, v in summary.items()):
        raise ValueError('summary differs')
    return {**summary, 'signed_receipts': signed, 'manifest_sha256': anchor, 'units': units,
            'scope': 'author-side signed application and receiver evidence; no external certification'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
