"""Supplemental offline Grant-scope and paired-input checks for native cohorts."""
import argparse
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from verify_native_business import verify


def review_scope(raw, profile):
    unit_root = Path(raw['gold']['source_path']).parents[2]
    public = str(unit_root / 'workspace/company-a')
    installed = str(unit_root / 'hermes/profiles/work/skills/intent-fixture/SKILL.md')
    extra = profile in ('skill-read-controls', 'absolute-briefing')
    expected = {('tool', 'tool.invoke', 'read_file'), ('tool', 'tool.invoke', 'write_file'),
                ('filesystem', 'fs.read', public), ('filesystem', 'fs.write', public)}
    if extra:
        expected.add(('filesystem', 'fs.read', installed))
    tools = ['read_file', 'write_file']
    if profile == 'terminal-grant-controls':
        tools.append('terminal')
        expected.add(('tool', 'tool.invoke', 'terminal'))
    if profile == 'delegation-controls':
        tools.append('delegate_task')
        expected.add(('tool', 'tool.invoke', 'delegate_task'))
    patches = [r for r in raw['management_http'] if r['route'].endswith('/patch-desired')]
    approvals = [r for r in raw['management_http'] if r['route'].endswith('/approve')]
    if len(patches) != 1 or len(approvals) != 1:
        raise ValueError('one ordinary patch and approval required')
    patch = patches[0]['request']
    if patch['tools'] != tools or patch['filesystem'] != {
        'read_only': [public] + ([installed] if extra else []), 'read_write': [public]
    }:
        raise ValueError('scope proposal differs from registered profile')
    grant = approvals[0]['response']['grant']
    if grant.get('default_effect') != 'deny' or grant.get('enforcement_mode') != 'block':
        raise ValueError('Grant protection mode differs')
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['receipts']['public_key'], validate=True))
    if grant['signing_schema'] != 'local_canonical/v1':
        raise ValueError('unknown Grant signing schema')
    payload = json.dumps({k: v for k, v in grant.items() if k != 'signature'},
                         sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    key.verify(bytes.fromhex(grant['signature']), payload)
    observed = {(f['domain'], f['action'], f['resource']['value']) for f in grant['facts'] if f['effect'] == 'allow'}
    if observed != expected or len(grant['facts']) != len(expected) or grant['status'] != 'approved':
        raise ValueError('approved Grant expands or changes exact allowed scope')
    decisions = [r for r in raw['receipts']['receipts'] if r['record_type'] == 'decision']
    if any(r['matched_grant_id'] != grant['grant_id'] for r in decisions if r['action'] == 'allow'):
        raise ValueError('actual allow did not use reviewed Grant')
    return {'approved_grant_id': grant['grant_id'], 'grant_signature_verified': True,
            'exact_allowed_fact_count': len(expected), 'installed_instruction_read_only': extra,
            'business_read_write_roots': [public], 'tool_allowlist': tools}


def review(run, anchor):
    original = verify(run, anchor)
    protocol = json.loads((run / 'protocol.json').read_text())
    profile = protocol.get('profile', 'briefing')
    scopes, pairs, tokens, calls = {}, {}, 0, 0
    for unit in protocol['allocation']:
        raw = json.loads((run / 'cases' / unit['unit_id'] / 'result.json').read_text())
        root = str(Path(raw['gold']['source_path']).parents[2])
        pairs.setdefault(unit['case_id'], {})[unit['group']] = {
            field: raw['gold'][field].replace(root, '__UNIT_ROOT__') for field in ('prompt', 'source_text')}
        if profile in ('semantic-briefing', 'semantic-support-v2'):
            documents = raw['gold']['public_documents']
            if len({row['name'] for row in documents}) != len(documents):
                raise ValueError('duplicate semantic input document')
            pairs[unit['case_id']][unit['group']]['documents'] = {
                row['name']: row['text'].replace(root, '__UNIT_ROOT__') for row in documents}
        if raw['process']['argv'][-1] != raw['gold']['prompt']:
            raise ValueError('CLI prompt differs from gold')
        if unit['group'] == 'B2':
            scopes[unit['unit_id']] = review_scope(raw, profile)
        for row in raw['model_exchanges']:
            if sent := row.get('provider_request'):
                calls += 1
                if sent.get('model') != protocol['model'] or sent.get('temperature') != 0 or sent.get('max_tokens') != 8192:
                    raise ValueError('real provider configuration differs')
                tokens += row['response']['usage']['total_tokens']
    if any(set(pair) != {'B0', 'B2'} or pair['B0'] != pair['B2'] for pair in pairs.values()):
        raise ValueError('paired task inputs differ beyond isolated roots')
    budget = json.loads((run / 'summary.json').read_text())['model_budget']
    if budget['calls'] != calls or budget['tokens'] != tokens or budget['unknown_usage_calls'] != 0:
        raise ValueError('provider accounting not fully reconciled')
    return {'manifest_sha256': anchor, 'profile': profile, 'paired_conditions': len(pairs),
            'paired_task_inputs_match': True, 'approved_scopes': scopes, 'real_provider_calls': calls,
            'reported_tokens': tokens, 'original_business_exit_code': original['outcome_exit_code'],
            'scope': 'supplemental post-run offline checks; does not rewrite frozen scores; exact approved Grant scope and normalized task inputs, not identical host system prompts or global access isolation'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
