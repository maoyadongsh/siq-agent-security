"""Verify snapshot invalidation, preserved historical revisions and separate authority."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path

import native_runtime_snapshot as snapshot
import verify_native_personal_onboarding as base
from common import sha256
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from personal_onboarding_authority import canonical, require
from verify_native_personal_runtime_check import record_canonical
from verify_native_runtime_faults import joins as fault_joins


def joins(raw, p, evidence):
    obs = raw['runtime_check_observation']
    require(obs['variant'] == p['snapshot_variant'] and obs['variant'] in snapshot.VARIANTS, 'snapshot variant differs')
    final = obs['receipts_final']
    _, count = evidence.verify_receipt_bundles([final])
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(final['public_key'], validate=True))
    require(final['public_key'] == raw['receipts']['public_key'], 'snapshot issuer differs')
    prefix = raw['receipts']['receipts']
    require(final['receipts'][:len(prefix)] == prefix, 'business prefix differs')
    details = {}
    docs = {}
    snapshots = [obs.get('records_after_change', {}), obs['records_final']]
    for stage in ('baseline', 'fresh'):
        if stage not in obs:
            continue
        item = obs[stage]
        details[stage] = fault_joins({**raw, 'runtime_check_observation': item}, evidence)
        require(final['receipts'][:len(item['receipts']['receipts'])] == item['receipts']['receipts'], 'selfcheck prefix changed')
        snapshots += [item['records']]
    for records in snapshots:
        for name, record in records.items():
            key.verify(bytes.fromhex(record['signature']), record_canonical(record))
            require(name == f"{record['result']['check_id']}.{record['revision']:06d}.json", 'snapshot filename differs')
            require(name not in docs or docs[name] == record, 'snapshot revision overwritten')
            docs[name] = record
    for stage in ('grant_before', 'grant_after'):
        if stage in obs:
            grant = obs[stage]['grant']
            key.verify(bytes.fromhex(grant['signature']), canonical({k: v for k, v in grant.items() if k != 'signature'}))
            require(grant['grant_id'] == obs['identity_before']['grant_ref']['grant_id'], 'changed another business Grant')
    mutation = obs.get('mutation', {})
    if 'signed_revocation' in mutation:
        document = mutation['signed_revocation']
        key.verify(bytes.fromhex(document['signature']), canonical({k: v for k, v in document.items() if k != 'signature'}))
        require(document['identity_id'] == obs['identity_before']['identity_id'] == obs['identity_after']['identity_id'], 'revoked another identity')
    ids = {r['result']['check_id'] for r in docs.values()}
    for cid in ids:
        own = sorted((r for r in docs.values() if r['result']['check_id'] == cid), key=lambda r: r['revision'])
        require([r['revision'] for r in own] == list(range(len(own))), 'snapshot revision missing')
        require(all(r['result']['instance_id'] == obs['instance_id'] for r in own), 'snapshot belongs to another instance')
    old = obs.get('baseline', {}).get('variants', {}).get('recovery', {}).get('plan', {}).get('check_id')
    for stage in ('after_change', 'after_restore', 'old_after_fresh'):
        if stage in obs:
            require(obs[stage]['check_id'] == old and any(r['result'] == obs[stage] for r in docs.values()), 'old check API lacks matching signed revision')
    if 'old_after_fresh' in obs:
        old_records = [r for r in docs.values() if r['result']['check_id'] == old]
        require(max(old_records, key=lambda r: r['revision'])['result'] == obs['old_after_fresh'], 'old API differs from latest signed revision')
    if obs.get('error_type') is None:
        require(len(ids) == 2 and set(details) == {'baseline', 'fresh'}, 'two distinct checks not captured')
        require(obs['identity_before']['identity_id'] == obs['identity_after']['identity_id'], 'identity readback replaced')
    return {'unique_signed_receipts': count, 'signed_revisions': len(docs), 'checks': details,
            'scope': 'signed selfcheck and business authority states; not an independent probe effect oracle'}


def verify(run, anchor):
    base.PROFILE, base.score = snapshot.PROFILE, snapshot.score
    result = base.verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    require(sha256(source) == p['candidate_sources']['benchmarks/runtime-security/evidence.py'], 'trusted verifier changed')
    spec = importlib.util.spec_from_file_location('snapshot_signature_evidence', source)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    output = {}
    for unit in p['allocation']:
        directory = run / 'cases' / unit['unit_id']
        raw = json.loads((directory / 'result.json').read_text())
        events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
        require([e['record'] for e in events if e['event'] == 'product_runtime_check_observed'] == [raw['runtime_check_observation']], 'snapshot event capture differs')
        output[unit['unit_id']] = joins(raw, p, evidence)
    return {**result, 'runtime_snapshot_joins': output}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
