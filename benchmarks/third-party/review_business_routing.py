"""Run sealed-evidence negative controls without calling models or product tools."""
import argparse
import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from common import sha256, write_json


def review(campaign, run_id):
    root = campaign / 'private/runs' / run_id
    harness = campaign / 'protocols' / (run_id + '-protocol') / 'harness-source'
    sys.path.insert(0, str(harness))
    # Do not accidentally import mutable scoring/verifier modules from an earlier review.
    for name in ('verify_business_routing', 'business_routing_scoring'):
        sys.modules.pop(name, None)
    verify = importlib.import_module('verify_business_routing').verify
    baseline = verify(root, sha256(root / 'manifest.json'))
    outcomes = []
    control = 'alias-exact-control' if 'alias-exact-control' in baseline['units'] else 'public-default-local'
    mutations = ['signed-record-change', 'model-event-change', 'budget-excess', 'missing-allocation', 'source-result-change', 'journal-change']
    if control == 'alias-exact-control':
        mutations += ['tcp-attempt-omitted', 'alias-returned-plan-changed']
    for name in mutations:
        with tempfile.TemporaryDirectory(prefix='routing-negative-', dir=campaign / 'private') as temp:
            target = Path(temp)
            manifest = json.loads((root / 'manifest.json').read_text())
            for relative in manifest['artifacts']:
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / relative, path)
            case = 'local-tcp-refused' if name == 'tcp-attempt-omitted' else 'alias-scope' if name == 'alias-returned-plan-changed' else control
            result_path = target / 'cases' / case / 'result.json'
            value = json.loads(result_path.read_text())
            if name == 'signed-record-change':
                value['public_evidence']['receipts'][0]['reason_code'] = 'changed'
            elif name == 'budget-excess':
                value['budget_after']['requests'] = 999999
            elif name == 'source-result-change':
                value['application_result']['research']['source_digests'] = ['0' * 64]
            elif name == 'model-event-change':
                path = target / 'cases' / control / 'events.jsonl'
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                next(row for row in rows if row['event'] == 'model_endpoint_request')['record']['role'] = 'local'
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            elif name == 'missing-allocation':
                del manifest['artifacts']['cases/' + control + '/result.json']
            elif name == 'journal-change':
                path = target / 'journal.jsonl'
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                rows[-1]['record']['utility_completed'] = not rows[-1]['record']['utility_completed']
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            elif name == 'tcp-attempt-omitted':
                value['tcp_refusal']['attempts'] = [r for r in value['tcp_refusal']['attempts'] if r['phase'] != 'application']
                path = target / 'cases' / case / 'events.jsonl'
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                rows = [r for r in rows if not (r['event'] == 'refused_tcp_connect' and r['phase'] == 'application')]
                for number, row in enumerate(rows, 1):
                    row['sequence'] = number
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            elif name == 'alias-returned-plan-changed':
                import hashlib
                model = value['model_endpoints']['remote']['records'][0]
                proposed = json.loads(model['response']['choices'][0]['message']['content'])
                proposed['skills'][0]['input']['scope'] = ['source-0']
                model['response']['choices'][0]['message']['content'] = json.dumps(proposed)
                model['response_wire'] = json.dumps(model['response'])
                model['response_sha256'] = hashlib.sha256(model['response_wire'].encode()).hexdigest()
                path = target / 'cases' / case / 'events.jsonl'
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                for row in rows:
                    if row['event'] == 'model_endpoint_request' and row['record']['role'] == 'remote':
                        row['record'] = model
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            result_path.write_text(json.dumps(value) + '\n')
            manifest['artifacts'] = {relative: sha256(target / relative) for relative in manifest['artifacts']}
            (target / 'manifest.json').write_text(json.dumps(manifest) + '\n')
            try:
                verify(target, sha256(target / 'manifest.json'))
            except (ValueError, AssertionError) as exc:
                outcomes.append({'mutation': name, 'rejected': True, 'error_type': type(exc).__name__, 'reason': str(exc)[:160]})
            else:
                outcomes.append({'mutation': name, 'rejected': False})
    return {'run_id': run_id, 'manifest_sha256': sha256(root / 'manifest.json'),
            'baseline_outcome_exit_code': baseline['outcome_exit_code'], 'signed_receipts': baseline['signed_receipts'],
            'negative_controls': outcomes, 'passed': all(row['rejected'] for row in outcomes),
            'scope': 'fresh copies and recomputed outer hashes; original frozen evidence unchanged; no model or product execution'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = review(args.campaign.resolve(), args.run_id)
    write_json(args.out, result)
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)
