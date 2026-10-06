"""Offline browser/API/signed runtime-check correlation; no browser or model execution."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path

from common import safe_path, sha256
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from lifecycle import project, summarize
from personal_onboarding_authority import canonical, require
from personal_runtime_browser_trial import STAGES, allocation, score
from verify_native_personal_runtime_check import record_canonical

PROJECTION_FIELDS = ('receipt_id', 'seq', 'hash', 'issued_at', 'platform', 'session_id',
                     'agent_id', 'action', 'reason', 'tool', 'record_type', 'action_id',
                     'decision_receipt_id', 'matched_grant_id')


def verify_projection(detail, selected):
    # The public activity contract exposes a summary of each signed receipt.
    expected = [{k: r.get(k, '' if k == 'decision_receipt_id' else None)
                 for k in PROJECTION_FIELDS} for r in selected]
    require(detail == expected, 'activity receipt projection differs from signed sequence')


def verify_joins(o, evidence):
    receipts, count = evidence.verify_receipt_bundles([o['receipts']])
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(o['receipts']['public_key'], validate=True))
    records = {}
    for name, record in o['records'].items():
        key.verify(bytes.fromhex(record['signature']), record_canonical(record))
        require(name == f"{record['result']['check_id']}.{record['revision']:06d}.json", 'record filename differs')
        records.setdefault(record['result']['check_id'], []).append(record)
    for rows in records.values():
        require(sorted(r['revision'] for r in rows) == list(range(len(rows))), 'record revision missing')
    for field in ('passed', 'invalidated', 'restored', 'cancelled'):
        if field not in o:
            continue
        view = o[field]
        rows = records.get(view['check_id'], [])
        require(any(r['result'] == view for r in rows), 'API view not in signed history')
        if field in ('restored', 'cancelled'):
            require(max(rows, key=lambda r: r['revision'])['result'] == view, 'API view not latest signed revision')
    if 'passed' not in o:
        return {'unique_signed_receipts': count, 'signed_revisions': sum(map(len, records.values())), 'scope': 'partial signed material only'}
    passed = o['passed']
    selected = [receipts[x][0] for x in passed['receipt_ids']]
    require(len(selected) == len(set(passed['receipt_ids'])) == 5, 'passed receipt set differs')
    decisions = {r['tool_call_id']: r for r in selected if r['record_type'] == 'decision'}
    require(set(decisions) == {'rc-first', 'rc-denied', 'rc-last'}, 'actual selfcheck calls differ')
    for call_id, action in (('rc-first', 'allow'), ('rc-denied', 'deny'), ('rc-last', 'allow')):
        r = decisions[call_id]
        require(r['action'] == action and r['tool'] == ('write_file' if action == 'deny' else 'read_file'), 'signed call action differs')
        require(r['agent_id'] == 'rca-' + passed['check_id'][3:] and r['intent_id'] == 'rci-' + passed['check_id'][3:], 'signed selfcheck identity differs')
    if 'activity_reference' in o:
        binding = o['activity_reference']['activity']['binding']
        for r in selected:
            require(all(r[k] == binding[k] for k in ('chain_id', 'platform', 'session_id', 'agent_id', 'task_id', 'intent_id', 'intent_digest')), 'activity binding differs')
        if 'activity_detail' in o:
            verify_projection(o['activity_detail']['receipts'], selected)
            require(o['activity_reference']['activity']['activity_id'] in o['stages']['activity-detail']['url'], 'UI navigated to different activity')
        if 'security_view' in o:
            require(o['security_view']['activity']['binding'] == binding and o['security_view']['snapshot'] == o['activity_reference']['snapshot'], 'security view belongs to another activity')
    for g in o.get('grants_cancelled', o.get('grants_passed', {})).get('grants', []):
        key.verify(bytes.fromhex(g['signature']), canonical({k: v for k, v in g.items() if k != 'signature'}))
    starts = [r['body'] for r in o['browser']['responses'] if r['path'] == '/v1/runtime-checks/start' and r['status'] == 202]
    require(len(starts) == len({r['check_id'] for r in starts}), 'duplicate browser launches')
    for start in starts:
        require(start['check_id'] in records and start['instance_id'] == o['instance_id'], 'browser started different instance')
    return {'unique_signed_receipts': count, 'signed_revisions': sum(map(len, records.values())),
            'actual_browser_start_ids': [s['check_id'] for s in starts], 'scope': 'signed identity and actual UI/API mapping; no independent syscall oracle'}


def verify(run, anchor):
    require(sha256(run / 'manifest.json') == anchor, 'manifest anchor differs')
    manifest = json.loads((run / 'manifest.json').read_text())
    require(manifest['schema_version'] == 'siq-personal-runtime-browser/v1', 'manifest type differs')
    for name, expected in manifest['artifacts'].items():
        require(sha256(safe_path(run, name)) == expected, 'artifact changed')
    p, states, _, _ = project(run)
    require(p['allocation'] == allocation() and p['profile'] == 'personal-runtime-browser', 'allocation differs')
    for name, expected in p['harness_sources'].items():
        require(sha256(safe_path(Path(__file__).parent, name)) == expected, 'frozen harness changed')
    require(json.loads((run / 'host-after.json').read_text()) == p['host'], 'host identity changed')
    o = json.loads((run / 'browser-observations.json').read_text())
    result = score(o)
    require(result == json.loads((run / 'score.json').read_text()), 'score differs')
    for name in STAGES:
        if name not in o['stages']:
            continue
        snapshot = run / 'output/playwright' / (name + '.yaml')
        require(snapshot.is_file() and str(snapshot.relative_to(run)) in manifest['artifacts'], 'stage snapshot missing')
        marker = {'selfcheck-passed': '本次自检通过', 'activity-detail': '未设置结果核验', 'invalidated': '自检结果已失效',
                  'restored-invalidated': '自检结果已失效', 'cancelled': '自检已取消'}.get(name)
        if marker:
            require(marker in snapshot.read_text(), 'DOM and independent snapshot disagree')
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    require(sha256(source) == p['candidate_sources']['benchmarks/runtime-security/evidence.py'], 'signature verifier changed')
    spec = importlib.util.spec_from_file_location('browser_runtime_evidence', source)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    joins = verify_joins(o, evidence)
    summary = summarize(states)
    require(summary == json.loads((run / 'summary.json').read_text()), 'summary differs')
    case = next(iter(states.values()))
    if case['measurement_status'] == 'determinate':
        require(case['utility_completed'] == result['all_passed'], 'journal utility differs')
    return {**summary, 'browser_checks': result, 'joins': joins, 'manifest_sha256': anchor,
            'scope': 'author-captured actual browser journey, not independent certification'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
