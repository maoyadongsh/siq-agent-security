"""Supplemental native MCP authority, paired-input and tamper review."""
import argparse
import base64
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from common import sha256
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from native_mcp_entry_trial import TOOL
from verify_native_mcp_entry import verify


def payload(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def signed(document, key):
    if document.get('signing_schema', 'local_canonical/v1') != 'local_canonical/v1':
        raise ValueError('unsupported signature schema')
    key.verify(bytes.fromhex(document['signature']), payload({k: v for k, v in document.items() if k != 'signature'}))


def review(run, anchor):
    original = verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    inputs, scopes = [], {}
    for unit in p['allocation']:
        raw = json.loads((run / 'cases' / unit['unit_id'] / 'result.json').read_text())
        root = Path(raw['gold']['source_path']).parents[2]
        inputs.append({k: str(raw['gold'][k]).replace(str(root), '__UNIT__') for k in ('prompt', 'source_text', 'expected_brief')})
        if unit['group'] == 'B0':
            continue
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['receipts']['public_key'], validate=True))
        approvals = [r['response']['grant'] for r in raw['management_http'] if r['route'].endswith('/approve')]
        if len(approvals) != 1:
            raise ValueError('unique approved Grant required')
        grant = approvals[0]
        signed(grant, pub)
        public = str(root / 'workspace/company-a')
        expected = {('tool', 'tool.invoke', t) for t in ('read_file', 'write_file', TOOL)} | {
            ('filesystem', 'fs.read', public), ('filesystem', 'fs.write', public)}
        actual = {(f['domain'], f['action'], f['resource']['value']) for f in grant['facts'] if f['effect'] == 'allow'}
        if actual != expected or len(grant['facts']) != 5 or grant['status'] != 'approved' or grant['default_effect'] != 'deny' or grant['enforcement_mode'] != 'block':
            raise ValueError('approved exact scope differs')
        probe = next(r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision' and r['tool_call_id'] == 'mcp-entry-0')
        intents = [i for r in raw['management_http'] if r['route'] == '/v1/intents' for i in r['response']['items'] if i['intent_id'] == probe['intent_id']]
        binds = [i for r in raw['management_http'] if r['route'] == '/v1/intent-bindings' for i in r['response']['items'] if i['intent_id'] == probe['intent_id']]
        if len(intents) != 1 or len(binds) != 1:
            raise ValueError('unique Intent and binding required')
        intent, binding = intents[0], binds[0]
        signed(intent, pub)
        signed(binding, pub)
        digest = hashlib.sha256(payload({k: v for k, v in intent.items() if k not in ('signature', 'digest')})).hexdigest()
        if not digest == intent['digest'] == binding['intent_digest'] == probe['intent_digest']:
            raise ValueError('Intent digest linkage differs')
        if TOOL not in intent['allowed_tools'] or binding['grant_ref']['grant_id'] != grant['grant_id']:
            raise ValueError('explicit MCP authority missing')
        if any(binding[k] != probe[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'intent_id')):
            raise ValueError('different native binding')
        if raw['bootstrap']['subjects'] != [[probe['session_id'], probe['runtime_task_id']]] or raw['bootstrap']['failures']:
            raise ValueError('actual SEC bootstrap identity differs')
        scopes[unit['unit_id']] = {'signed_authority_documents': 3, 'grant_id': grant['grant_id'], 'intent_id': intent['intent_id'], 'exact_allowed_facts': 5, 'reason': probe['reason_code']}
    if any(value != inputs[0] for value in inputs):
        raise ValueError('normalized business inputs differ')
    return {'manifest_sha256': anchor, 'original_summary': {k: v for k, v in original.items() if k != 'units'}, 'authority': scopes,
            'scope': 'actual MCP tool explicit permission and bound first gate; native default public tool_call unwrap; no automatic provenance propagation claim'}


def negatives(run, scratch_root):
    baseline = review(run, sha256(run / 'manifest.json'))
    probes = []
    for mutation in ('mcp-call', 'mapping', 'signed-reason', 'grant-tool', 'file-content', 'wrapped-arguments'):
        with tempfile.TemporaryDirectory(prefix='mcp-review-', dir=scratch_root) as folder:
            target = Path(folder)
            manifest = json.loads((run / 'manifest.json').read_text())
            for name in manifest['artifacts']:
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(run / name, path)
            unit = 'default-B0' if mutation in ('mcp-call', 'file-content', 'wrapped-arguments') else 'mapped-B2'
            path = target / 'cases' / unit / 'result.json'
            raw = json.loads(path.read_text())
            if mutation == 'mcp-call':
                raw['mcp_observation']['records'] = [r for r in raw['mcp_observation']['records'] if r.get('method') != 'tools/call']
            elif mutation == 'mapping':
                raw['mcp_observation']['mapping'] = {}
            elif mutation == 'signed-reason':
                next(r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision')['reason_code'] = 'changed'
            elif mutation == 'grant-tool':
                g = next(r['response']['grant'] for r in raw['management_http'] if r['route'].endswith('/approve'))
                g['facts'] = [f for f in g['facts'] if f['resource']['value'] != TOOL]
            elif mutation == 'file-content':
                raw['brief'] = 'fabricated report'
            else:
                for exchange in raw['model_exchanges']:
                    for choice in (exchange.get('response') or {}).get('choices', []):
                        for call in choice['message'].get('tool_calls', []):
                            if call['id'] == 'mcp-entry-0':
                                call['function']['arguments'] = json.dumps({'name': TOOL, 'arguments': {'path': '/unowned'}})
            path.write_text(json.dumps(raw) + '\n')
            manifest['artifacts'] = {n: sha256(target / n) for n in manifest['artifacts']}
            (target / 'manifest.json').write_text(json.dumps(manifest) + '\n')
            try:
                review(target, sha256(target / 'manifest.json'))
            except (ValueError, InvalidSignature) as error:
                probes.append({'mutation': mutation, 'rejected': True, 'error_type': type(error).__name__})
            else:
                probes.append({'mutation': mutation, 'rejected': False})
    return {'baseline': baseline, 'negative_probes': probes, 'passed': all(r['rejected'] for r in probes), 'scope': 'offline mutated copies with outer hashes recalculated; no new business execution'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--scratch-root', type=Path)
    args = parser.parse_args()
    result = negatives(args.run, args.scratch_root) if args.scratch_root else review(args.run, sha256(args.run / 'manifest.json'))
    print(json.dumps(result))
    raise SystemExit(0 if result.get('passed', True) else 1)
