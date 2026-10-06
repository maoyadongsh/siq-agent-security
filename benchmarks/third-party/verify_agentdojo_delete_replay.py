"""Verify recorded deletion replay without model calls or executing tools."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from agentdojo_delete_replay import allocation, score_capture
from common import canonical, safe_path, sha256
from lifecycle import project, summarize


def verify(run, anchor, candidate):
    if sha256(safe_path(run, 'manifest.json')) != anchor:
        raise ValueError('manifest anchor mismatch')
    manifest = json.loads((run / 'manifest.json').read_text())
    if manifest['schema_version'] != 'siq-agentdojo-delete-replay/v1':
        raise ValueError('unsupported replay manifest')
    artifacts = manifest['artifacts']
    if not {'protocol.json', 'journal.jsonl', 'summary.json'} <= set(artifacts):
        raise ValueError('missing canonical material')
    for name, digest in artifacts.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError('sealed payload differs')
    p, states, _, _ = project(run)
    if p['allocation'] != allocation() or p['model_calls_enabled'] is not False or p['deletion_arguments'] != {'email_id': '31'}:
        raise ValueError('unregistered action replay')
    source = candidate / 'benchmarks/runtime-security/evidence.py'
    if sha256(source) != p['candidate_sources']['benchmarks/runtime-security/evidence.py']:
        raise ValueError('trusted signature verifier differs')
    spec = importlib.util.spec_from_file_location('replay_signatures', source)
    signatures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signatures)
    results, signed_count = {}, 0
    for unit in p['allocation']:
        name, prefix = unit['unit_id'], 'cases/' + unit['unit_id']
        required = [prefix + '/' + n for n in ('environment-before.json', 'environment-after.json', 'result.json', 'score.json', 'dispatch-events.jsonl')]
        if not set(required) <= set(artifacts):
            raise ValueError('allocated replay material missing')
        directory = run / prefix
        if sha256(directory / 'environment-before.json') != p['source_files']['environment-before.json']:
            raise ValueError('replay starts from different source environment')
        before, after = [json.loads((directory / n).read_text()) for n in ('environment-before.json', 'environment-after.json')]
        result = json.loads((directory / 'result.json').read_text())
        if result['model_calls'] != 0:
            raise ValueError('replay contains model calls')
        outcome = score_capture(unit, p, before, after, result)
        if json.loads((directory / 'score.json').read_text()) != outcome or result['scenario'] != name:
            raise ValueError('replay outcome differs')
        events = [json.loads(s) for s in (directory / 'dispatch-events.jsonl').read_text().splitlines()]
        if [e['sequence'] for e in events] != list(range(1, len(events) + 1)):
            raise ValueError('dispatch event gap')
        ends = [e for e in events if e['event'] == 'tool_dispatch_finished']
        requests = [e for e in events if e['event'] == 'tool_dispatch_requested']
        if len(requests) != len(result['dispatches']) or len(ends) != len(result['dispatches']):
            raise ValueError('dispatch event count differs')
        for i, d in enumerate(result['dispatches']):
            if any(ends[i][k] != v for k, v in d.items()):
                raise ValueError('dispatch projection differs from events')
            if requests[i]['dispatch_id'] != d['dispatch_id'] or requests[i]['arguments'] != d['arguments'] or requests[i]['entered']:
                raise ValueError('dispatch start binding differs')
            if d['tool'] == 'delete_email' and d['arguments'] != p['deletion_arguments']:
                raise ValueError('replayed deletion parameters differ')
        if name == 'no_guard':
            if result['decisions']:
                raise ValueError('unguarded arm has SIQ decision')
        else:
            if prefix + '/product-evidence.json' not in artifacts:
                raise ValueError('missing SIQ public receipts')
            bundle = json.loads((directory / 'product-evidence.json').read_text())
            if bundle['binary_sha256'] != p['candidate_digest']:
                raise ValueError('wrong product binary')
            receipts, count = signatures.verify_receipt_bundles([bundle])
            signed_count += count
            for item in result['decisions']:
                decision = item['decision']
                signed = receipts[decision['receipt_id']][0]
                if any(signed[k] != decision[k] for k in ('action_id', 'action', 'reason_code', 'task_id')):
                    raise ValueError('recorded deletion decision differs from signed receipt')
                if (signed['task_id'] != 'replay-task' or signed['tool'] != 'delete_email' or signed['tool_call_id'] != item['dispatch_id']
                        or signed['params_digest'] != hashlib.sha256(canonical(p['deletion_arguments'])).hexdigest()
                        or item['params_sha256'] != signed['params_digest']):
                    raise ValueError('signed deletion action/call/params/task binding differs')
                if p.get('fixture_revision') == 2:
                    expected_session = 'agentdojo-explicit-delete' if name == 'authorized_delete_unsupported' else 'agentdojo-session'
                    request_identity = result['request_identity']
                    if (request_identity['session_id'] != expected_session or request_identity['platform'] != 'hermes'
                            or any(signed[k] != v for k, v in request_identity.items())):
                        raise ValueError('signed deletion identity binding differs')
        state = states[name + '#1']
        expected_harm = outcome['deletion_observed'] if name != 'authorized_delete_unsupported' else False
        if (state['assertion_status'] != ('pass' if outcome['passed'] else 'fail') or state['harm_observed'] != expected_harm
                or state['cleanup_confirmed'] != outcome['checks']['cleanup'] or state['utility_completed'] is not None):
            raise ValueError('canonical outcome differs')
        results[name] = outcome
    summary = summarize(states)
    if summary != json.loads((run / 'summary.json').read_text()):
        raise ValueError('summary differs')
    return {'integrity': 'verified_against_supplied_digest', 'manifest_sha256': anchor, **summary,
            'scenarios': results, 'signed_receipts': signed_count, 'model_calls': 0,
            'scope': 'same recorded action/environment, real SIQ decision, original simulated mailbox effects; authorized deletion remains unsupported; not new model ASR'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--trusted-candidate', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256, args.trusted_candidate)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
