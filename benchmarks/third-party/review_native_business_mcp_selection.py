"""Supplement actual source selection diagnostics with authority and credential binding."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

import review_native_business_mcp as business_review
from common import sha256
from cryptography.exceptions import InvalidSignature
from verify_native_business_mcp_selection import verify


def review(run, anchor):
    # Reuse the already reviewed readback/authority checks with this batch's
    # frozen verifier. This changes no product, protocol, or measurement.
    original = business_review.verify
    try:
        business_review.verify = verify
        result = business_review.review(run, anchor)
    finally:
        business_review.verify = original
    raw = json.loads((run / 'cases/mapped-B2/result.json').read_text())
    issued = [r['response'] for r in raw['management_http'] if r['route'] == '/v1/runtime-identities' and r.get('request')]
    if len(issued) != 1:
        raise ValueError('unique original instance credential issuance required')
    identity = issued[0]['identity']
    obs = raw['selection_observation']
    if identity['agent_id'] != obs['parent']['scope']['agent_id'] or identity['platform'] != obs['parent']['scope']['platform']:
        raise ValueError('credential identity differs from signed source')
    for row in obs['probes']:
        if row['route'] == '/v1/provenance-select':
            if row['credential_kind'] != 'installed_runtime_identity' or row['credential_reference'] != issued[0]['credential_path']:
                raise ValueError('selection used a different credential reference')
        elif row['credential_kind'] != 'admin_session' or row['credential_reference'] is not None:
            raise ValueError('management resolver credential differs')
    pre = [h for h in raw['business_mcp_observation']['hooks'] if h['event'] == 'pre_tool_call_fields']
    for ident, tool, fields in [('business-mcp-0', 'mcp__siq_business__research_verify_published_report', ['report_key']),
                               ('business-mcp-1', 'write_file', ['content', 'path'])]:
        rows = [h for h in pre if h['tool_call_id'] == ident]
        if len(rows) != 1 or rows[0]['tool_name'] != tool or rows[0]['args_fields'] != fields:
            raise ValueError('native pre hook tool or argument shape differs')
        row = rows[0]
        if row['parameter_provenance_present'] != ('parameter_provenance' in row['fields']) or row['context_assertion_present'] != ('context_assertion_id' in row['fields']):
            raise ValueError('pre hook presence claim differs from observed fields')
    result['selection'] = {
        'actual_http': {r['name']: r['actual_http'] for r in obs['probes']},
        'credential_reference_matches_issued_instance': True,
        'parent_signed_source_type': obs['parent']['source']['type'],
        'captured_content_type': obs['content_type'],
        'default_parameter_bridge_present': any(r['parameter_provenance_present'] for r in pre),
        'selected_parameter_utility': any(r['actual_http'] == 201 and 'provenance_id' in r['response'] for r in obs['probes'] if r['route'] == '/v1/provenance-select'),
        'scope': 'explicit post-run diagnostics; no constrained downstream parameter execution',
    }
    return result


def negatives(run, scratch):
    baseline = review(run, sha256(run / 'manifest.json'))
    rows = []
    for mutation in ('credential-reference', 'HTTP-status', 'parsed-content', 'drop-probe', 'pre-hook-fields', 'source-signature'):
        with tempfile.TemporaryDirectory(prefix='mcp-selection-negative-', dir=scratch) as temp:
            target = Path(temp)
            manifest = json.loads((run / 'manifest.json').read_text())
            for name in [*manifest['artifacts'], 'manifest.json']:
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(run / name, dest)
            path = target / 'cases/mapped-B2/result.json'
            raw = json.loads(path.read_text())
            obs = raw['selection_observation']
            if mutation == 'credential-reference':
                obs['probes'][1]['credential_reference'] = '/unowned/identity.token'
            elif mutation == 'HTTP-status':
                obs['probes'][1]['actual_http'] = 200
            elif mutation == 'parsed-content':
                obs['probes'][2]['request']['content'] = obs['probes'][1]['request']['content']
            elif mutation == 'drop-probe':
                obs['probes'].pop()
            elif mutation == 'pre-hook-fields':
                next(r for r in raw['business_mcp_observation']['hooks'] if r['event'] == 'pre_tool_call_fields')['fields'].append('parameter_provenance')
            else:
                obs['parent']['signature'] = '0' * 128
            path.write_text(json.dumps(raw) + '\n')
            # Keep unsigned observer copies and outer checksums coherent, so
            # rejection must go beyond the trivial duplicated-event mismatch.
            event_path = target / 'cases/mapped-B2/events.jsonl'
            events = [json.loads(line) for line in event_path.read_text().splitlines()]
            for event in events:
                if event['event'] == 'selection_observed':
                    event['record'] = obs
                if event['event'] == 'business_mcp_observed':
                    event['record'] = raw['business_mcp_observation']
            event_path.write_text(''.join(json.dumps(e) + '\n' for e in events))
            manifest['artifacts'] = {name: sha256(target / name) for name in manifest['artifacts']}
            (target / 'manifest.json').write_text(json.dumps(manifest) + '\n')
            try:
                review(target, sha256(target / 'manifest.json'))
            except (ValueError, InvalidSignature) as error:
                rows.append({'mutation': mutation, 'rejected': True, 'error_type': type(error).__name__})
            else:
                rows.append({'mutation': mutation, 'rejected': False})
    return {'baseline': baseline, 'negative_probes': rows, 'passed': all(r['rejected'] for r in rows),
            'scope': 'offline copies with matching unsigned events and recalculated outer hashes; no model or business calls'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--scratch', type=Path)
    args = parser.parse_args()
    result = negatives(args.run, args.scratch) if args.scratch else review(args.run, sha256(args.run / 'manifest.json'))
    print(json.dumps(result))
    raise SystemExit(0 if result.get('passed', True) else 1)
