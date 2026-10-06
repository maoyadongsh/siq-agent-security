"""Offline native CLI evidence verification without re-running host or model."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from common import safe_path, sha256
from lifecycle import project, summarize
from native_business_scoring import transcript
from native_personal_onboarding import PROFILE, allocation, score
from personal_onboarding_authority import verify_authority


def parameter_digest(params):
    """Match Go json.Marshal for this harness's string/bool/safe-integer inputs.

    Receipt signatures use a different canonical representation. Reject numbers
    outside this supported subset rather than silently accepting an approximation.
    """
    def validate(value):
        if value is None or type(value) in (str, bool):
            return
        if type(value) is int and abs(value) <= 2**53 - 1:
            return
        if type(value) is list:
            for child in value:
                validate(child)
            return
        if type(value) is dict and all(type(key) is str for key in value):
            for child in value.values():
                validate(child)
            return
        raise ValueError('unsupported parameter value for Go JSON digest')

    validate(params)
    payload = json.dumps(params, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    for literal, escaped in (('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'),
                             ('\u2028', '\\u2028'), ('\u2029', '\\u2029')):
        payload = payload.replace(literal, escaped)
    return hashlib.sha256(payload.encode()).hexdigest()


def verify(run, anchor):
    if sha256(run / 'manifest.json') != anchor:
        raise ValueError('manifest anchor differs')
    manifest = json.loads((run / 'manifest.json').read_text())
    if manifest['schema_version'] != 'siq-native-business/v1':
        raise ValueError('unexpected native manifest')
    if not {'protocol.json', 'journal.jsonl', 'summary.json', 'host-after.json'} <= manifest['artifacts'].keys():
        raise ValueError('missing required global artifacts')
    for name, digest in manifest['artifacts'].items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError('artifact differs')
    p, states, _, _ = project(run)
    if p['allocation'] != allocation() or p['profile'] != PROFILE:
        raise ValueError('onboarding allocation differs')
    for name, digest in p['harness_sources'].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError('frozen onboarding harness differs')
    if json.loads((run / 'host-after.json').read_text()) != p['host']:
        raise ValueError('native host source identity changed')
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    if sha256(source) != p['candidate_sources']['benchmarks/runtime-security/evidence.py']:
        raise ValueError('trusted signature verifier differs')
    spec = importlib.util.spec_from_file_location('native_business_signature_verifier', source)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    units, signed, authority = {}, 0, {}
    for unit in p['allocation']:
        prefix = 'cases/' + unit['unit_id']
        for f in ('result.json', 'score.json', 'gold.json', 'events.jsonl'):
            if prefix + '/' + f not in manifest['artifacts']:
                raise ValueError('missing allocated capture')
        raw = json.loads((run / prefix / 'result.json').read_text())
        if raw['unit'] != unit or raw['gold'] != json.loads((run / prefix / 'gold.json').read_text()):
            raise ValueError('allocation or task gold differs')
        calculated = score(p, unit, raw)
        if calculated != json.loads((run / prefix / 'score.json').read_text()):
            raise ValueError('score differs from raw material')
        if calculated['measurement_complete']:
            authority[unit['unit_id']] = verify_authority(raw)
        for key in ('harm_observed', 'utility_completed', 'cleanup_confirmed'):
            if states[unit['unit_id'] + '#1'][key] != calculated[key]:
                raise ValueError('journal differs')
        events = [json.loads(line) for line in (run / prefix / 'events.jsonl').read_text().splitlines()]
        if [e['sequence'] for e in events] != list(range(1, len(events) + 1)):
            raise ValueError('event sequence differs')
        if [e['record'] for e in events if e['event'] == 'onboarding_observed'] != [raw['onboarding_observation']]:
            raise ValueError('onboarding observer differs from original events')
        exchanges = [e['exchange'] for e in events if e['event'] == 'model_exchange_finished']
        if p.get('profile') == 'delegation-wait-controls':
            # Concurrent parent/child requests can finish out of request order.
            exchanges = sorted(exchanges, key=lambda row: row['sequence'])
        if exchanges != raw['model_exchanges']:
            raise ValueError('model transcript differs from original events')
        if p.get('profile') in ('delegation-controls', 'delegation-wait-controls'):
            observed = [e['record'] for e in events if e['event'] == 'native_delegation_hook']
            if observed != (raw.get('delegation_observation') or {}).get('hooks', []):
                raise ValueError('native delegation lineage differs from hook events')
        if raw.get('receipts'):
            receipts, count = verifier.verify_receipt_bundles([raw['receipts']])
            signed += count
            calls, _, _ = transcript(raw)
            decisions = [r[0] for r in receipts.values() if r[0].get('record_type') == 'decision']
            for decision in decisions:
                call = calls.get(decision['tool_call_id'])
                if call is None or call['tool'] != decision['tool'] or parameter_digest(call['params']) != decision['params_digest']:
                    raise ValueError('native model proposal and signed decision differ')
        if unit['group'] == 'B0' and (raw.get('receipts') or raw['management_http']):
            raise ValueError('B0 contains SIQ artifacts')
        units[unit['unit_id']] = calculated
    summary = summarize(states)
    saved = json.loads((run / 'summary.json').read_text())
    if any(saved[k] != v for k, v in summary.items()):
        raise ValueError('summary differs')
    return {**summary, 'signed_receipts': signed, 'manifest_sha256': anchor, 'units': units, 'authority_joins': authority,
            'scope': 'author-captured actual Hermes CLI and signed SIQ receipts; not independent certification'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
