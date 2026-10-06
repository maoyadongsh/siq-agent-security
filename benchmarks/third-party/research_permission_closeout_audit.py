"""Read-only final evidence inventory; this is not a new model evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

from research_daily_permissions_verify import verify_records
from research_permissions_verify import verify_receipt_bundles

CASES = {
    'RG01': ['daily-permissions-001'],
    'RG02': ['daily-permissions-001'],
    'RG03': ['cross-company-004'],
    'RG04': ['skill-business-003'],
    'RG05': ['skill-update-001', 'skill-replacement-005', 'skill-drift-containment-002'],
    'RG06': ['skill-revoke-004', 'business-revoke-003'],
    'RG07': ['tool-utility-003'],
    'RG08': ['relay-recovery-002'],
    'RG09': ['daily-permissions-001', 'skill-business-003'],
}


def owned_path(root, value):
    path = Path(value)
    rel = path.relative_to(root / 'data/wiki/companies')
    if (not re.fullmatch(r'600000-Synthetic(?:Api|Daily)[a-f0-9]{16}', rel.parts[0])
            or path.resolve() != path):
        raise ValueError('unowned research effect path')
    return path


def effects(value, root, location='proof'):
    checked = []
    if isinstance(value, dict):
        if value.get('output_path') and value.get('output_sha256'):
            path = owned_path(root, value['output_path'])
            checked.append({'location': location, 'path': str(path), 'kind': 'current_file_hash',
                'passed': path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == value['output_sha256']})
        if value.get('write_target_absent') is True and value.get('write_target_path'):
            path = owned_path(root, value['write_target_path'])
            checked.append({'location': location, 'path': str(path), 'kind': 'current_file_absent',
                            'passed': not path.exists()})
        for name, item in value.items():
            checked.extend(effects(item, root, location + '.' + name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            checked.extend(effects(item, root, location + '[' + str(index) + ']'))
    return checked


def audit(campaign, root):
    rows = []
    for name in sorted({n for group in CASES.values() for n in group}):
        batch = 'research-permissions-' + name
        paths = {'execution': campaign / 'reports' / (batch + '.json'),
            'verification': campaign / 'reports' / (batch + ('-skill-verification.json' if name.startswith('skill-business-')
                                                            else '-verification.json')),
            'protocol': campaign / 'protocols' / (batch + '.json'),
            'receipts': campaign / 'data' / (batch + '-verified-receipts.json')}
        docs = {label: json.loads(path.read_text()) for label, path in paths.items()}
        bundle = docs['receipts']
        if name == 'daily-permissions-001':
            signatures = verify_records(bundle['receipts'], bundle['public_key'])
            count, scope = signatures['records'], signatures['scope']
        else:
            _, count = verify_receipt_bundles([bundle])
            scope = 'Complete owned receipt chain prefix, individual hashes and signatures.'
        run, review = docs['execution'], docs['verification']
        proof = run.get('proof', run)
        truth = effects(proof, root)
        recorded_protocol = run.get('pre_run_protocol_sha256') or run.get('protocol_sha256')
        checks = {'execution_passed': run.get('passed') is True, 'independent_review_passed': review.get('passed') is True,
            'all_review_checks_true': bool(review.get('checks')) and all(review['checks'].values()),
            'signed_receipts_reverified': count > 0, 'current_exported_effect_paths_match': all(c['passed'] for c in truth),
            'protocol_digest_matches_run': recorded_protocol == hashlib.sha256(paths['protocol'].read_bytes()).hexdigest()}
        rows.append({'batch': batch, 'passed': all(checks.values()), 'checks': checks,
            'receipt_count': count, 'signature_scope': scope, 'current_file_checks': truth,
            'artifact_refs': {k: str(p.relative_to(campaign)) for k, p in paths.items()},
            'artifact_sha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}})
    return {'schema_version': 'siq.research-permission-closeout-evidence.v1', 'recorded_unix': time.time(),
            'passed': all(r['passed'] for r in rows), 'cases': CASES, 'rows': rows,
            'scope': 'Final read-only artifact integrity/signature/current-effect check. Requirement coverage also needs the human-reviewed final report; no new model task or independent institution certification.',
            'limitations': ['Current-file review covers exported output_path/output_sha256 and absent-target fields only.',
                'Other case-specific effects and semantics retain their separate verification reports.',
                'Historical source versions are represented by each frozen protocol; they need not equal the later repaired worktree.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--research-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.campaign.resolve(), args.research_root.resolve())
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'passed': result['passed'], 'batches': len(result['rows']),
                      'failed_checks': {r['batch']: [k for k, v in r['checks'].items() if not v] for r in result['rows'] if not r['passed']}}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
