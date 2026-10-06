"""Frozen, bounded format-only diagnosis of failed Step planning responses."""
import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

from business_chain_trial import load_benchmark
from business_routing_transport import RoutingBudget, forward
from common import sha256, utc_now, write_json


def freeze(campaign, run_id):
    base = campaign / 'protocols/business-model-routing-live-001-protocol'
    original = json.loads((base / 'protocol.json').read_text())
    target = campaign / 'protocols' / (run_id + '-protocol')
    target.mkdir(exist_ok=False)
    shutil.copytree(base / 'harness-source', target / 'harness-source', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copyfile(Path(__file__), target / 'harness-source' / Path(__file__).name)
    benchmark = load_benchmark(Path(original['candidate_root']))
    from secure_agent.models import proposal_schema
    sources, allocation = {}, []
    for source in ('public-default-local', 'confidential-default'):
        path = campaign / 'private/runs/business-model-routing-live-001/cases' / source / 'result.json'
        sources[str(path)] = sha256(path)
        body = json.loads(path.read_text())['model_endpoints']['remote']['records'][0]['body']
        for mode in ('json_schema', 'text'):
            value = copy.deepcopy(body)
            value['response_format'] = {'type': mode}
            if mode == 'json_schema':
                value['response_format']['json_schema'] = {'name': 'model-task-plan-v2', 'strict': True,
                                                         'schema': proposal_schema('model-task-plan-v2')}
            allocation.append({'unit_id': source + '-' + mode, 'source_unit': source, 'format': mode, 'request': value})
    source = target / 'harness-source'
    p = {k: original[k] for k in ('candidate_root', 'candidate_sources', 'upstreams')}
    p.update(run_id=run_id, operation='format_only_diagnostic_not_business_evaluation', frozen_at=utc_now(),
        campaign_root=str(campaign), allocation=allocation, input_sources=sources,
        candidate_entry=str(benchmark.ROOT / 'apps/secure-agent/secure_agent/contracts.py') + ':TaskPlan.parse',
        limits={'calls': 4, 'request_seconds': 45, 'seconds': 240, 'max_tokens': 4096, 'reservation': 200000, 'retries': 0},
        harness_sources={str(f.relative_to(source)): sha256(f) for f in source.rglob('*') if f.is_file()},
        scope='same two preserved synthetic plan payloads; only response_format changed; no SIQ business tool or local-model execution; no repair of missing fields or extraction from reasoning')
    write_json(target / 'protocol.json', p)
    print(json.dumps({'protocol': str(target / 'protocol.json'), 'requests': len(allocation)}))


def run(protocol):
    p = json.loads(protocol.read_text())
    for name, expected in p['harness_sources'].items():
        if sha256(Path(__file__).parent / name) != expected:
            raise ValueError('frozen helper changed')
    for name, expected in p['input_sources'].items():
        if sha256(Path(name)) != expected:
            raise ValueError('preserved input changed')
    for name, expected in p['candidate_sources'].items():
        if sha256(Path(p['candidate_root']) / name) != expected:
            raise ValueError('candidate source changed')
    load_benchmark(Path(p['candidate_root']))
    from secure_agent.contracts import AgentError, TaskPlan, strict_json
    out = Path(p['campaign_root']) / 'private/runs' / p['run_id']
    out.mkdir(exist_ok=False)
    shutil.copyfile(protocol, out / 'protocol.json')
    budget = RoutingBudget(calls=4, seconds=240, reservation=200000)
    rows = []
    for unit in p['allocation']:
        row = {'unit_id': unit['unit_id'], 'request': unit['request'], 'status': None, 'error': None,
               'task_plan_valid': False, 'response_wire': None}
        request = json.dumps(unit['request'], ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()
        row['request_sha256'] = hashlib.sha256(request).hexdigest()
        try:
            row['reservation'] = budget.take(unit['unit_id'], unit['request'], len(request))
            status, response = forward(p['upstreams']['remote'], request, p['limits']['request_seconds'])
            row.update(status=status, response_wire=response.decode(), response_sha256=hashlib.sha256(response).hexdigest())
            parsed = strict_json(response)
            row['usage'] = parsed.get('usage', {})
            if status == 200:
                choice = parsed['choices'][0]
                row['finish_reason'] = choice['finish_reason']
                if choice['finish_reason'] == 'stop':
                    TaskPlan.parse(strict_json(choice['message']['content']))
                    row['task_plan_valid'] = True
        except AgentError as exc:
            row['error'] = str(exc)
        except Exception as exc:  # noqa: BLE001 -- diagnosis preserves failure and never prints provider internals
            row['error'] = type(exc).__name__
        rows.append(row)
        write_json(out / 'cases' / unit['unit_id'] / 'result.json', row)
        print(json.dumps({k: row.get(k) for k in ('unit_id', 'status', 'error', 'task_plan_valid')}), flush=True)
    summary = {'allocated': len(p['allocation']), 'finished': len(rows), 'requests': budget.snapshot(),
               'valid_task_plans': sum(row['task_plan_valid'] for row in rows), 'business_executions': 0,
               'scope': p['scope']}
    write_json(out / 'summary.json', summary)
    write_json(out / 'manifest.json', {'schema_version': 'siq-model-format-diagnostic/v1',
        'artifacts': {str(f.relative_to(out)): sha256(f) for f in out.rglob('*') if f.is_file()}})
    print(json.dumps({'manifest_sha256': sha256(out / 'manifest.json'), **summary}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--protocol', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        freeze(args.campaign.resolve(), args.run_id)
    else:
        run(args.protocol)
