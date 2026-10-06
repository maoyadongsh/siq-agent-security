"""Offline material/signature verification for original application trials."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit

from business_chain_scoring import score
from common import canonical, safe_path, sha256
from lifecycle import project, summarize


def verify(run, anchor, candidate):
    if sha256(safe_path(run, 'manifest.json')) != anchor:
        raise ValueError('manifest anchor mismatch')
    manifest = json.loads((run / 'manifest.json').read_text())
    if manifest['schema_version'] != 'siq-business-chain/v1':
        raise ValueError('unsupported manifest')
    artifacts = manifest['artifacts']
    for name, digest in artifacts.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError('sealed payload differs')
    for name in ('protocol.json', 'journal.jsonl', 'summary.json', 'calibration.json', 'calibration-events.jsonl'):
        if name not in artifacts:
            raise ValueError('required material missing')
    p, states, _, _ = project(run)
    calibration = json.loads((run / 'calibration.json').read_text())
    if calibration['counts'] != [0, 1, 2] or len(calibration['wire']) != 2 or not calibration['passed']:
        raise ValueError('receiver calibration invalid')
    if not all(calibration['health'].get(k) is True for k in ('before', 'after', 'closed')):
        raise ValueError('calibration observer unhealthy')
    for i, row in enumerate(calibration['wire']):
        body = 'evaluation receiver calibration ' + str(i)
        if (row['status'] != 201 or row['action_id'] != 'calibration-' + str(i)
                or row['payload_sha256'] != hashlib.sha256(body.encode()).hexdigest()
                or row['request_sha256'] != hashlib.sha256(canonical({'body': body})).hexdigest()):
            raise ValueError('calibration wire material differs')
    source = candidate / 'benchmarks/runtime-security/evidence.py'
    if sha256(source) != p['candidate_sources']['benchmarks/runtime-security/evidence.py']:
        raise ValueError('trusted signature verifier differs')
    spec = importlib.util.spec_from_file_location('business_signatures', source)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    results, signed = {}, 0
    for unit in p['allocation']:
        prefix = 'cases/' + unit['unit_id']
        if not {prefix + '/' + n for n in ('result.json', 'score.json', 'events.jsonl')} <= set(artifacts):
            raise ValueError('allocated capture missing')
        raw = json.loads((run / prefix / 'result.json').read_text())
        if raw['unit'] != unit:
            raise ValueError('capture allocation differs')
        calculated = score(p, unit, raw)
        if calculated != json.loads((run / prefix / 'score.json').read_text()):
            raise ValueError('derived score differs')
        row = states[unit['unit_id'] + '#1']
        for field in ('harm_observed', 'utility_completed', 'cleanup_confirmed'):
            if row[field] != calculated[field]:
                raise ValueError('journal score differs')
        events = [json.loads(line) for line in (run / prefix / 'events.jsonl').read_text().splitlines()]
        if [e['sequence'] for e in events] != list(range(1, len(events) + 1)):
            raise ValueError('event sequence differs')
        event_wire = [{k: e[k] for k in r} for e, r in zip([e for e in events if e['event'] == 'receiver_request'], raw['wire'], strict=True)]
        if event_wire != raw['wire']:
            raise ValueError('receiver records differ from events')
        finished_tools = [e for e in events if e['event'] == 'actual_tool_finished']
        if [{k: e[k] for k in t} for e, t in zip(finished_tools, raw['tools'], strict=True)] != raw['tools']:
            raise ValueError('tool records differ from dispatch events')
        decision_events = [e for e in events if e['event'] == 'actual_decision']
        if [{k: e[k] for k in d} for e, d in zip(decision_events, raw['decisions'], strict=True)] != raw['decisions']:
            raise ValueError('decision records differ from events')
        if 'mcp_fixture' in unit:
            fixtures = [e['payload'] for e in events if e['event'] == 'registered_mcp_fixture']
            lookups = [t for t in raw['tools'] if t['tool'] == 'web_fetch'
                       and t['params'].get('json', {}).get('method') == 'tools/call']
            if (fixtures != [unit['mcp_fixture']] or len(lookups) != 1
                    or lookups[0]['result']['json']['result'] != unit['mcp_fixture']):
                raise ValueError('actual MCP response differs from registered text variant')
        capture = raw.get('capture')
        if capture and unit['group'] == 'B0':
            audit = raw.get('baseline_audit', {})
            if (capture.get('public_evidence') is not None or raw['decisions'] or raw['resources']
                    or audit.get('daemon_started') is not False or audit.get('forbidden_security_requests') != []):
                raise ValueError('B0 contains SIQ execution or missing bypass audit')
            app = capture['result']
            if app.get('intent') is not None or app.get('grant') is not None or app['task']['completion']['status'] != 'not_applicable':
                raise ValueError('B0 fabricated authority or completion')
            actions = app.get('preparation', {}).get('actions', []) + app['task']['actions']
            for action in actions:
                if action['receipt_id'] is not None or action['decision'] is not None or action['effect'] is not None:
                    raise ValueError('B0 fabricated SIQ material')
            for tool in raw['tools']:
                if tool['receipt_id'] is not None or not tool['action_id'].startswith('b0-dispatch-'):
                    raise ValueError('B0 dispatch mislabelled as signed')
                matching = [a for a in actions if a['action_id'] == tool['action_id'] and a['tool'] == tool['tool']]
                if len(matching) != 1:
                    raise ValueError('B0 dispatch does not belong to original task')
        if capture and unit['group'] != 'B0':
            receipts, count = verifier.verify_receipt_bundles([capture['public_evidence']])
            signed += count
            app = capture['result']
            for action in app.get('preparation', {}).get('actions', []) + app['task']['actions']:
                rec = receipts[action['receipt_id']][0]
                if any(rec[k] != action[v] for k, v in [('action_id', 'action_id'), ('action', 'decision'), ('reason_code', 'reason_code')]):
                    raise ValueError('application action signature binding differs')
                if action.get('effect'):
                    verifier.verify_effect_envelope(action['effect'], receipts)
            for record in raw['decisions']:
                response = record['response']
                if response is None:
                    continue
                rec = receipts[response['receipt_id']][0]
                request = record['request']
                if any(rec[k] != response[k] for k in ('action_id', 'action', 'reason_code', 'task_id')):
                    raise ValueError('decision response differs from signed receipt')
                if rec['params_digest'] != hashlib.sha256(canonical(request['params'])).hexdigest():
                    raise ValueError('decision parameter binding differs')
                # The original client's request_fields excludes task_id. SIQ
                # resolves its existing identity binding and returns task_id.
                if any(rec[k] != request[k] for k in ('tool', 'session_id', 'agent_id', 'platform')):
                    raise ValueError('decision identity binding differs')
                if 'task_id' in request and rec['task_id'] != request['task_id']:
                    raise ValueError('explicit task binding differs')
            for tool in raw['tools']:
                rec = receipts[tool['receipt_id']][0]
                if rec['action_id'] != tool['action_id'] or rec['params_digest'] != hashlib.sha256(canonical(tool['params'])).hexdigest():
                    raise ValueError('dispatch binding differs')
                if rec['action'] != 'allow':
                    raise ValueError('dispatch without signed permission')
        if capture:
            for received in raw['wire']:
                matching = [t for t in raw['tools'] if t['action_id'] == received['action_id'] and t['tool'] == 'web_fetch']
                if len(matching) != 1 or urlsplit(matching[0]['params']['url']).path != received['path']:
                    raise ValueError('receiver action is not bound to dispatched route')
                payload = matching[0]['params']['json']
                if unit['case_id'] == 'conflicting':
                    payload = {'body': 'Substituted report bytes from the controlled fault fixture.'}
                if (received['request_sha256'] != hashlib.sha256(canonical(payload)).hexdigest()
                        or received['payload_sha256'] != hashlib.sha256(payload['body'].encode()).hexdigest()):
                    raise ValueError('receiver payload differs from dispatched or registered fault bytes')
        results[unit['unit_id']] = calculated
    summary = summarize(states)
    saved = json.loads((run / 'summary.json').read_text())
    if any(saved[k] != v for k, v in summary.items()):
        raise ValueError('summary differs')
    return {'integrity': 'verified_against_supplied_digest', 'manifest_sha256': anchor,
            'signed_receipts': signed, **summary, 'units': results,
            'scope': 'author-run application, not native Hermes or independent third-party certification'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--trusted-candidate', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256, args.trusted_candidate)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
