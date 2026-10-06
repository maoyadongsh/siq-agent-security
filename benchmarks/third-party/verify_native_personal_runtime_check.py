"""Offline signed self-check revisions and exact activity/temporary authority joins."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path

import native_personal_runtime_check as runtime
import verify_native_personal_onboarding as base
from common import sha256
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from personal_onboarding_authority import canonical, require


def record_canonical(record):
    # Product recordMap uses json.Unmarshal(map[string]any): revision is float64.
    unsigned = {k: v for k, v in record.items() if k != 'signature'}
    return canonical(json.loads(json.dumps(unsigned), parse_int=float))


def verify_runtime(raw, evidence_verifier):
    obs = raw['runtime_check_observation']
    s = obs['stages']
    if 'receipts' not in s:
        return {'scope': 'partial runtime check; no complete authority claim', 'signed_receipts': 0}
    receipts, count = evidence_verifier.verify_receipt_bundles([s['receipts']])
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(s['receipts']['public_key'], validate=True))
    require(s['receipts']['public_key'] == raw['receipts']['public_key'], 'different issuer in same-daemon journey')
    require(s['receipts']['receipts'][:len(raw['receipts']['receipts'])] == raw['receipts']['receipts'], 'onboarding receipt prefix changed')
    documents = {}
    for stage in ('records_before_drift', 'records_after_restore'):
        for name, record in s.get(stage, {}).items():
            require(name == f"{record['result']['check_id']}.{record['revision']:06d}.json", 'record filename differs')
            key.verify(bytes.fromhex(record['signature']), record_canonical(record))
            if name in documents:
                require(documents[name] == record, 'immutable record changed')
            documents[name] = record
    terminal = s['terminal']
    require(terminal['instance_id'] == obs['instance_id'] == s['plan']['instance_id'], 'instance changed')
    for record in documents.values():
        require(record['result']['check_id'] == terminal['check_id'] and record['result']['instance_id'] == obs['instance_id'], 'borrowed record')
    revisions = sorted(r['revision'] for r in documents.values())
    require(revisions == list(range(len(revisions))), 'record revision missing')
    if terminal['status'] != 'passed':
        return {'signed_receipts': count, 'signed_record_revisions': len(documents), 'product_selfcheck_passed': False}
    require(any(r['result'] == terminal for r in documents.values()), 'passed HTTP result not signed')
    require(any(r['result'] == s['after_restore'] for r in documents.values()), 'restored HTTP result not signed')
    record = next(r for r in documents.values() if r['result'] == terminal)
    selected = [receipts[i][0] for i in terminal['receipt_ids']]
    require(len(selected) == len(set(terminal['receipt_ids'])) == 5, 'selfcheck receipt count differs')
    decisions = {r['tool_call_id']: r for r in selected if r['record_type'] == 'decision'}
    require(set(decisions) == {'rc-first', 'rc-denied', 'rc-last'}, 'selfcheck calls differ')
    expected = {'rc-first': ('read_file', 'allow'), 'rc-denied': ('write_file', 'deny'), 'rc-last': ('read_file', 'allow')}
    binding = s['activity']['activity']['binding']
    for call_id, rc in decisions.items():
        require((rc['tool'], rc['action']) == expected[call_id], 'selfcheck action differs')
        require(rc['intent_id'] == record['intent_id'] and rc['intent_digest'] == record['intent_digest'], 'selfcheck Intent differs')
        require(rc['agent_id'] == 'rca-' + terminal['check_id'][3:], 'selfcheck agent differs')
        require(all(rc[k] == binding[k] for k in ('chain_id', 'platform', 'session_id', 'agent_id', 'task_id', 'intent_id', 'intent_digest')), 'activity binding differs')
        if rc['action'] == 'allow':
            require(rc['matched_grant_id'] == record['grant_id'] and rc['authority_status'] == 'valid', 'selfcheck Grant differs')
    observed = [r for r in selected if r['record_type'] == 'observation']
    require(len(observed) == 2, 'observations missing')
    for rc in observed:
        decision = decisions[rc['tool_call_id']]
        require(decision['action'] == 'allow' and rc['decision_receipt_id'] == decision['receipt_id'] and rc['action_id'] == decision['action_id'], 'observation association differs')
    require(s['activity']['activity']['receipt_count'] == 5 and s['activity']['instance_id'] == obs['instance_id'], 'activity count or instance differs')
    authorities = [next(g for g in s['grants_after']['grants'] if g['grant_id'] == record['grant_id']),
                   next(i for i in s['intents_after']['items'] if i['intent_id'] == record['intent_id']),
                   next(b for b in s['bindings_after']['items'] if b['binding_id'] == record['binding_id'])]
    for document in authorities:
        key.verify(bytes.fromhex(document['signature']), canonical({k: v for k, v in document.items() if k != 'signature'}))
    require(authorities[0]['status'] == 'revoked', 'temporary Grant not revoked')
    require(authorities[2]['grant_ref']['grant_id'] == record['grant_id'] and authorities[2]['intent_digest'] == record['intent_digest'], 'temporary binding differs')
    return {'signed_receipts': count, 'additional_selfcheck_receipts': len(selected),
            'signed_record_revisions': len(documents), 'temporary_authority_documents': len(authorities),
            'product_selfcheck_passed': True, 'scope': 'signature and identity joins, not independent observation of ephemeral physical effects'}


def verify(run, anchor):
    base.PROFILE = runtime.PROFILE
    base.score = runtime.score
    result = base.verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    require(sha256(source) == p['candidate_sources']['benchmarks/runtime-security/evidence.py'], 'signature verifier changed')
    spec = importlib.util.spec_from_file_location('runtime_check_evidence', source)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    joins = {}
    for unit in p['allocation']:
        directory = run / 'cases' / unit['unit_id']
        raw = json.loads((directory / 'result.json').read_text())
        events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
        require([e['record'] for e in events if e['event'] == 'product_runtime_check_observed'] == [raw['runtime_check_observation']], 'runtime check observation differs')
        joins[unit['unit_id']] = verify_runtime(raw, verifier)
    result['runtime_check_joins'] = joins
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
