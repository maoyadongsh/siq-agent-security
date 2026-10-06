"""Supplemental recovery evidence review, including preserved incomplete first allocation."""
import argparse
import importlib.util
import json
from pathlib import Path

from business_recovery_scoring import score
from common import canonical, safe_path, sha256
from lifecycle import project, summarize
from verify_business_recovery import params_digest, verify


def review(run, anchor):
    if sha256(run / 'manifest.json') != anchor:
        raise ValueError('manifest differs')
    manifest = json.loads((run / 'manifest.json').read_text())
    for name, digest in manifest['artifacts'].items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError('artifact differs')
    p, states, _, _ = project(run)
    summary = summarize(states)
    saved = json.loads((run / 'summary.json').read_text())
    if any(saved[k] != v for k, v in summary.items()):
        raise ValueError('summary differs')
    preserved = any(s['lifecycle'] != 'finished' for s in states.values())
    if not preserved:
        verify(run, anchor)
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    if sha256(source) != p['candidate_sources']['benchmarks/runtime-security/evidence.py']:
        raise ValueError('trusted verifier differs')
    spec = importlib.util.spec_from_file_location('recovery_review_signatures', source)
    signatures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signatures)
    captures, no_capture, signed_count = {}, [], 0
    for unit in p['allocation']:
        path = run / 'cases' / unit['unit_id'] / 'result.json'
        if not path.exists():
            if states[unit['unit_id'] + '#1']['lifecycle'] != 'scheduled':
                raise ValueError('started case lacks expected recovery capture')
            no_capture.append(unit['unit_id'])
            continue
        raw = json.loads(path.read_text())
        records, count = signatures.verify_receipt_bundles([raw['public_evidence']])
        signed_count += count
        for row in raw['decisions']:
            record = records[row['decision']['receipt_id']][0]
            if record['params_digest'] != params_digest(row['request']['params']):
                raise ValueError('original request differs from signed digest')
            if any(record[k] != row['request'][k] for k in ('platform', 'session_id', 'agent_id', 'tool', 'tool_call_id')):
                raise ValueError('request identity differs')
        structured, claims = [], []
        for stage in raw['stages']:
            completion = stage['completion_readback']
            if completion['task_id'] != stage['identity']['task_id']:
                raise ValueError('completion belongs to another task')
            phase = stage['phase']
            if stage.get('result'):
                polluted = unit['case_id'] != 'clean-control' if phase == 'initial' else unit['case_id'] == 'fresh-tainted'
                if stage['polluted'] != polluted or stage['mcp_fixture']['content'] != [{'type': 'text', 'text': p['pii_text'] if polluted else p['clean_text']}]:
                    raise ValueError('MCP text differs from allocated condition')
                structured.append({k: v for k, v in stage['mcp_fixture'].items() if k != 'content'})
                if stage['result']['provider'] != 'fixture' or stage['result']['model_calls']:
                    raise ValueError('unexpected real model in controlled recovery')
            events = raw['wire'][stage['wire_start']:stage['wire_end']]
            for event in events:
                candidates = [r[0] for r in records.values() if r[0].get('record_type') == 'decision' and r[0]['action_id'] == event['action_id']]
                if len(candidates) != 1 or candidates[0]['tool'] != 'web_fetch' or candidates[0]['action'] != 'allow' or candidates[0]['task_id'] != stage['identity']['task_id']:
                    raise ValueError('receiver request lacks matching authorized nested dispatch')
            claims.append({'phase': phase, 'task_id': stage['identity']['task_id'], 'completion_status': completion['status'], 'actual_requests': len(events)})
        if len(structured) != 2 or structured[0] != structured[1]:
            raise ValueError('structured MCP changed between original and recovery task')
        stages = [e['stage'] for e in (json.loads(line) for line in (path.parent / 'events.jsonl').read_text().splitlines()) if e['event'] == 'stage_finished']
        if canonical(stages) != canonical(raw['stages']):
            raise ValueError('captured stages differ from events')
        captures[unit['unit_id']] = {'signed_receipts': count, 'structured_mcp_unchanged': True,
            'phases': claims, 'corrected_diagnostic': score(p, unit, raw) if preserved else None,
            'original_lifecycle': states[unit['unit_id'] + '#1']['lifecycle']}
    return {'manifest_sha256': anchor, 'original_summary': summary, 'preserved_incomplete_run': preserved,
            'signed_receipts': signed_count, 'captures': captures, 'not_started': no_capture,
            'scope': 'post-run supplemental checks; completed runs use original strict verifier; corrected diagnostics of interrupted capture do not replace original unknown allocation'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
