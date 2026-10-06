"""Offline verification of actual paused-host timeout/revocation/recovery evidence."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path

import native_runtime_faults as faults
import verify_native_personal_onboarding as base
from common import sha256
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from personal_onboarding_authority import canonical, require
from verify_native_personal_runtime_check import record_canonical


def missing_binding_allowed(latest, records, bindings, receipts):
    cid = latest['result']['check_id']
    require(latest['result']['status'] == 'failed' and latest['result']['reason_code'] in
            ('runtime_check_timeout', 'runtime_check_host_failed'), 'missing binding after unexpected outcome')
    require(all(r['binding_id'] == '' and r['result']['status'] != 'running' for r in records), 'binding history inconsistent')
    require(not any(b['intent_id'] == latest['intent_id'] for b in bindings), 'binding exists but omitted')
    require(not any(r.get('agent_id') == 'rca-' + cid[3:] for r in receipts), 'receipts exist without captured binding')


def joins(raw, evidence):
    obs = raw['runtime_check_observation']
    receipts, count = evidence.verify_receipt_bundles([obs['receipts']])
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(obs['receipts']['public_key'], validate=True))
    require(obs['receipts']['public_key'] == raw['receipts']['public_key'], 'issuer differs')
    prefix = raw['receipts']['receipts']
    require(obs['receipts']['receipts'][:len(prefix)] == prefix, 'business prefix differs')
    docs = {}
    snapshots = [obs['records']]
    for row in obs['variants'].values():
        snapshots += [row.get('records_before', {}), row.get('records', {})]
    for snapshot in snapshots:
        for name, r in snapshot.items():
            key.verify(bytes.fromhex(r['signature']), record_canonical(r))
            require(name == f"{r['result']['check_id']}.{r['revision']:06d}.json", 'record filename differs')
            require(name not in docs or docs[name] == r, 'immutable revision changed')
            docs[name] = r
    check_ids = []
    authorities = set()
    for variant, row in obs['variants'].items():
        if 'terminal' not in row:
            continue
        terminal = row['terminal']
        cid = terminal['check_id']
        check_ids.append(cid)
        require(cid == row['plan']['check_id'] == row['started']['check_id'], 'borrowed check result')
        require(terminal['instance_id'] == obs['instance_id'] == row['plan']['instance_id'], 'instance differs')
        records = sorted((r for r in docs.values() if r['result']['check_id'] == cid), key=lambda r: r['revision'])
        require([r['revision'] for r in records] == list(range(len(records))), 'missing signed revision')
        latest = records[-1]
        require(latest['result'] == terminal, 'API not latest signed result')
        for collection, idfield in (('grants', 'grant_id'), ('intents', 'intent_id'), ('bindings', 'binding_id')):
            items = row[collection]['grants' if collection == 'grants' else 'items']
            if collection == 'bindings' and latest['binding_id'] == '':
                missing_binding_allowed(latest, records, items, obs['receipts']['receipts'])
                continue
            document = next(x for x in items if x[idfield] == latest[idfield])
            key.verify(bytes.fromhex(document['signature']), canonical({k: v for k, v in document.items() if k != 'signature'}))
            authorities.add((collection, document[idfield]))
        if variant == 'grant-revoked':
            for stage in ('grant_before_revoke', 'grant_after_revoke'):
                g = row[stage]['grant']
                require(g['grant_id'] == latest['grant_id'], 'revoked another grant')
                key.verify(bytes.fromhex(g['signature']), canonical({k: v for k, v in g.items() if k != 'signature'}))
        selected = [receipts[rid][0] for rid in terminal['receipt_ids']]
        for rc in selected:
            require(rc['agent_id'] == 'rca-' + cid[3:] and rc['intent_id'] == latest['intent_id'] and rc['intent_digest'] == latest['intent_digest'], 'borrowed selfcheck receipt')
        if terminal['status'] == 'passed':
            require(len(selected) == 5, 'passed receipt count differs')
            decisions = {r['tool_call_id']: r for r in selected if r['record_type'] == 'decision'}
            require({k: (r['tool'], r['action']) for k, r in decisions.items()} == {
                'rc-first': ('read_file', 'allow'), 'rc-denied': ('write_file', 'deny'), 'rc-last': ('read_file', 'allow')}, 'recovery actions differ')
    require(len(check_ids) == len(set(check_ids)), 'reused check across variants')
    return {'signed_receipts': count, 'signed_revisions': len(docs), 'temporary_authority_documents': len(authorities), 'completed_variants': len(check_ids)}


def verify(run, anchor):
    base.PROFILE, base.score = faults.PROFILE, faults.score
    result = base.verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    require(sha256(source) == p['candidate_sources']['benchmarks/runtime-security/evidence.py'], 'signature verifier differs')
    spec = importlib.util.spec_from_file_location('runtime_fault_evidence', source)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    results = {}
    for unit in p['allocation']:
        d = run / 'cases' / unit['unit_id']
        raw = json.loads((d / 'result.json').read_text())
        events = [json.loads(line) for line in (d / 'events.jsonl').read_text().splitlines()]
        require([e['record'] for e in events if e['event'] == 'product_runtime_check_observed'] == [raw['runtime_check_observation']], 'event capture differs')
        results[unit['unit_id']] = joins(raw, evidence)
    return {**result, 'runtime_fault_joins': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
