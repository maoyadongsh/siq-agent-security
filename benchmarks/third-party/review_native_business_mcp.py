"""Bind actual business MCP readback, signed authority, and captured source bytes."""
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
from native_business_mcp_fixture import KEY, ROOT, TOOL, digest
from native_business_mcp_trial import report_identity
from verify_native_business_mcp import verify


def payload(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def signed(document, key):
    if document.get('signing_schema', 'local_canonical/v1') != 'local_canonical/v1':
        raise ValueError('signature schema differs')
    key.verify(bytes.fromhex(document['signature']), payload({k: v for k, v in document.items() if k != 'signature'}))


def review(run, anchor):
    original = verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    units, inputs = {}, []
    for unit in p['allocation']:
        raw = json.loads((run / 'cases' / unit['unit_id'] / 'result.json').read_text())
        root = Path(raw['gold']['source_path']).parents[2]
        inputs.append({k: str(raw['gold'][k]).replace(str(root), '__UNIT__') for k in ('prompt', 'expected_brief')})
        obs = raw['business_mcp_observation']
        before = obs['container']['before']
        # Independently bind each final output to the original prepared asset.
        for role, filename in [('markdown', 'report.md'), ('json', 'report.json'), ('html', 'report.html')]:
            source = 'fixtures/report_' + role + '.artifact'
            output = next((n for n in before if n.endswith('/versions/v000001/' + filename)), None)
            if output is None or before[output] != before[source]:
                raise ValueError('published bytes differ from prepared report asset')
        inspection = obs['container']['container_before']
        mounts = {r['Destination']: r for r in inspection['Mounts']}
        for destination, source in [('/opt/business-source', p['publisher_source']['frozen_root']), ('/opt/mcp-sdk', p['mcp_sdk_root']), (ROOT, str(root / 'publication'))]:
            if destination not in mounts or mounts[destination]['Source'] != source or mounts[destination]['RW']:
                raise ValueError('actual runtime mount differs')
        if not inspection['ReadonlyRootfs'] or inspection['NetworkMode'] != 'none':
            raise ValueError('container profile differs')
        detail = {'actual_MCP_calls': original['units'][unit['unit_id']]['actual_MCP_calls'], 'signed_authority_documents': 0,
                  'independent_publication_assets': 3, 'source_content_verified': False}
        if unit['group'] == 'B2':
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['receipts']['public_key'], validate=True))
            grant = next(r['response']['grant'] for r in raw['management_http'] if r['route'].endswith('/approve'))
            signed(grant, key)
            public = str(root / 'workspace/company-a')
            business = '/sandbox/other-business' if unit['wrong_root'] else ROOT
            expected = {('tool', 'tool.invoke', t) for t in ('read_file', 'write_file', TOOL)} | {
                ('filesystem', 'fs.read', public), ('filesystem', 'fs.write', public), ('filesystem', 'fs.read', business)}
            actual = {(r['domain'], r['action'], r['resource']['value']) for r in grant['facts'] if r['effect'] == 'allow'}
            if actual != expected or len(grant['facts']) != 6 or grant['status'] != 'approved' or grant['default_effect'] != 'deny' or grant['enforcement_mode'] != 'block':
                raise ValueError('exact approved scope differs')
            probe = next(r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision' and r['tool_call_id'] == 'business-mcp-0')
            intents = [i for r in raw['management_http'] if r['route'] == '/v1/intents' for i in r['response']['items'] if i['intent_id'] == probe['intent_id']]
            bindings = [i for r in raw['management_http'] if r['route'] == '/v1/intent-bindings' for i in r['response']['items'] if i['intent_id'] == probe['intent_id']]
            if len(intents) != 1 or len(bindings) != 1:
                raise ValueError('unique Intent/binding required')
            intent, binding = intents[0], bindings[0]
            signed(intent, key)
            signed(binding, key)
            intent_digest = hashlib.sha256(payload({k: v for k, v in intent.items() if k not in ('signature', 'digest')})).hexdigest()
            if not intent_digest == intent['digest'] == binding['intent_digest'] == probe['intent_digest']:
                raise ValueError('Intent digest differs')
            if binding['grant_ref']['grant_id'] != grant['grant_id'] or TOOL not in intent['allowed_tools']:
                raise ValueError('tool permission not bound')
            if any(binding[k] != probe[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'intent_id')):
                raise ValueError('authority identities differ')
            if raw['bootstrap']['subjects'] != [[probe['session_id'], probe['runtime_task_id']]] or raw['bootstrap']['failures']:
                raise ValueError('native SEC subject differs')
            detail.update(signed_authority_documents=3, reason=probe['reason_code'])
            if unit['mapping'] and not unit['wrong_root']:
                assertion = obs['source_resolution']
                signed(assertion, key)
                reference, scope = report_identity(probe)
                hooks = [h for h in obs['hooks'] if h['event'] == 'post_tool_call' and h['tool_call_id'] == 'business-mcp-0']
                if len(hooks) != 1:
                    raise ValueError('unique actual native post result required')
                actual_result = hooks[0]['result']
                source_id = digest({'server': 'urn:evaluation:original-business-publisher', 'tool': TOOL})
                source = {'type': 'MCP', 'trust': 'untrusted', 'source_id': 'reported:' + digest({'type': 'MCP', 'source_id': source_id})}
                if assertion['provenance_id'] != reference or assertion['scope'] != scope or assertion['source'] != source or assertion['content_digest'] != digest(actual_result) or assertion['parents'] != [] or assertion['derivation'] != 'direct':
                    raise ValueError('captured source does not match actual native result')
                if raw['gold']['publication']['publication_digest'] not in str(actual_result) or KEY not in str(actual_result):
                    raise ValueError('source is not the actual publication result')
                detail.update(signed_authority_documents=4, source_content_verified=True, source_trust='untrusted', provenance_id=reference)
        units[unit['unit_id']] = detail
    if any(value != inputs[0] for value in inputs):
        raise ValueError('paired business inputs differ')
    return {'manifest_sha256': anchor, 'original_summary': {k: v for k, v in original.items() if k != 'units'}, 'units': units,
            'scope': 'original public MCP readback, exact signed scopes and captured low-trust bytes; no downstream lineage claim'}


def negatives(run, scratch):
    baseline = review(run, sha256(run / 'manifest.json'))
    rows = []
    for mutation in ('source-trust', 'source-digest', 'hook-result', 'container-root', 'published-asset', 'grant-scope', 'MCP-result'):
        with tempfile.TemporaryDirectory(prefix='business-mcp-review-', dir=scratch) as folder:
            target = Path(folder)
            manifest = json.loads((run / 'manifest.json').read_text())
            for name in manifest['artifacts']:
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(run / name, dest)
            path = target / 'cases/mapped-B2/result.json'
            raw = json.loads(path.read_text())
            obs = raw['business_mcp_observation']
            if mutation == 'source-trust':
                obs['source_resolution']['source']['trust'] = 'authoritative'
            elif mutation == 'source-digest':
                obs['source_resolution']['content_digest'] = '0' * 64
            elif mutation == 'hook-result':
                next(h for h in obs['hooks'] if h['event'] == 'post_tool_call')['result'] = 'fabricated result'
            elif mutation == 'container-root':
                next(m for m in obs['container']['container_before']['Mounts'] if m['Destination'] == ROOT)['Source'] = '/unowned/source'
            elif mutation == 'published-asset':
                obs['container']['before']['fixtures/report_markdown.artifact'] = '0' * 64
            elif mutation == 'grant-scope':
                grant = next(r['response']['grant'] for r in raw['management_http'] if r['route'].endswith('/approve'))
                grant['facts'] = [f for f in grant['facts'] if f['resource']['value'] != ROOT]
            else:
                obs['records'] = [r for r in obs['records'] if r['direction'] != 'response' or 'structuredContent' not in r['message'].get('result', {})]
            path.write_text(json.dumps(raw) + '\n')
            manifest['artifacts'] = {n: sha256(target / n) for n in manifest['artifacts']}
            (target / 'manifest.json').write_text(json.dumps(manifest) + '\n')
            try:
                review(target, sha256(target / 'manifest.json'))
            except (ValueError, InvalidSignature) as error:
                rows.append({'mutation': mutation, 'rejected': True, 'error_type': type(error).__name__})
            else:
                rows.append({'mutation': mutation, 'rejected': False})
    return {'baseline': baseline, 'negative_probes': rows, 'passed': all(r['rejected'] for r in rows), 'scope': 'offline copies, outer hashes recomputed, no new business/model calls'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--scratch', type=Path)
    args = parser.parse_args()
    result = negatives(args.run, args.scratch) if args.scratch else review(args.run, sha256(args.run / 'manifest.json'))
    print(json.dumps(result))
    raise SystemExit(0 if result.get('passed', True) else 1)
