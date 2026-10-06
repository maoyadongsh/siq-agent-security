"""Offline native CLI evidence verification without re-running host or model."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

from common import safe_path, sha256
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from lifecycle import project, summarize
from native_business_mcp_selection import PROFILE, allocation, score
from native_business_scoring import transcript


def verify_selection(raw, events):
    obs = raw['selection_observation']
    if [e['record'] for e in events if e['event'] == 'selection_observed'] != [obs]:
        raise ValueError('selection observer and original events differ')
    parent = obs.get('parent')
    if parent:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['receipts']['public_key'], validate=True))
        unsigned = {k: v for k, v in parent.items() if k != 'signature'}
        key.verify(bytes.fromhex(parent['signature']), json.dumps(unsigned, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode())
        if parent != raw['business_mcp_observation']['source_resolution'] or parent['source']['type'] != 'MCP' or parent['source']['trust'] != 'untrusted':
            raise ValueError('actual low-trust parent differs')
        gate = next(r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision' and r['tool_call_id'] == 'business-mcp-0')
        if parent['scope'] != {k: gate[k] for k in ('platform', 'agent_id', 'session_id', 'task_id')}:
            raise ValueError('source scope differs from actual native decision')
    if any(r['route'] not in ('/v1/provenance-resolve', '/v1/provenance-select') for r in obs['probes']):
        raise ValueError('unexpected write or substitute source API')


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
        raise ValueError('MCP allocation differs')
    for name, digest in p['harness_sources'].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError('frozen MCP harness differs')
    if json.loads((run / 'host-after.json').read_text()) != p['host']:
        raise ValueError('native host source identity changed')
    for name, digest in p.get('mcp_sdk_sources', {}).items():
        if sha256(safe_path(Path(p['mcp_sdk_root']), name)) != digest:
            raise ValueError('frozen MCP SDK differs')
    for name, digest in p['publisher_source']['files'].items():
        if sha256(safe_path(Path(p['publisher_source']['frozen_root']), name)) != digest:
            raise ValueError('original publisher source changed')
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    if sha256(source) != p['candidate_sources']['benchmarks/runtime-security/evidence.py']:
        raise ValueError('trusted signature verifier differs')
    spec = importlib.util.spec_from_file_location('native_business_signature_verifier', source)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    units, signed = {}, 0
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
        for key in ('harm_observed', 'utility_completed', 'cleanup_confirmed'):
            if states[unit['unit_id'] + '#1'][key] != calculated[key]:
                raise ValueError('journal differs')
        events = [json.loads(line) for line in (run / prefix / 'events.jsonl').read_text().splitlines()]
        if [e['sequence'] for e in events] != list(range(1, len(events) + 1)):
            raise ValueError('event sequence differs')
        exchanges = [e['exchange'] for e in events if e['event'] == 'model_exchange_finished']
        if sorted(exchanges, key=lambda e: e['sequence']) != raw['model_exchanges']:
            raise ValueError('model transcript differs from original events')
        observed = [e['record'] for e in events if e['event'] == 'business_mcp_observed']
        if observed != [raw['business_mcp_observation']]:
            raise ValueError('MCP observer differs from event log')
        verify_selection(raw, events)
        if raw.get('receipts'):
            receipts, count = verifier.verify_receipt_bundles([raw['receipts']])
            signed += count
            calls, _, _ = transcript(raw)
            decisions = [r[0] for r in receipts.values() if r[0].get('record_type') == 'decision']
            for decision in decisions:
                call = calls.get(decision['tool_call_id'])
                if call and call['tool'] == 'tool_call':
                    params = call['params']
                    if set(params) != {'name', 'arguments'} or params['name'] != 'mcp__siq_business__research_verify_published_report' or not isinstance(params['arguments'], dict):
                        raise ValueError('unexpected native deferred tool envelope')
                    call = {'tool': params['name'], 'params': params['arguments']}
                if call is None or call['tool'] != decision['tool'] or parameter_digest(call['params']) != decision['params_digest']:
                    raise ValueError('native model proposal and signed decision differ')
        if unit['group'] == 'B0' and (raw.get('receipts') or raw['management_http']):
            raise ValueError('B0 contains SIQ artifacts')
        units[unit['unit_id']] = calculated
    summary = summarize(states)
    saved = json.loads((run / 'summary.json').read_text())
    if any(saved[k] != v for k, v in summary.items()):
        raise ValueError('summary differs')
    return {**summary, 'signed_receipts': signed, 'manifest_sha256': anchor, 'units': units,
            'scope': 'author-captured actual Hermes CLI and signed SIQ receipts; not independent certification'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
