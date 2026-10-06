"""Read-only, candidate-scoped evidence reuse review; never infer journey completion."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path

from common import canonical, safe_path, sha256, utc_now, write_json


def dispatch(run, anchor, protocol, schema):
    if schema == 'siq-business-chain/v1':
        if protocol.get('operation') == 'original_application_pii_recovery':
            from review_business_recovery import review
            result = review(run, anchor)
            result['outcome_exit_code'] = result['original_summary']['outcome_exit_code']
        else:
            from verify_business_chain import verify
            result = verify(run, anchor, Path(protocol['candidate_root']))
    elif schema == 'siq-business-oracle-calibration/v1':
        result = verify_oracle_calibration(run, protocol)
    elif schema in ('siq-native-business/v1', 'siq-governance-export/v1'):
        name = 'verify_native_business' if schema == 'siq-native-business/v1' else 'verify_governance'
        result = importlib.import_module(name).verify(run, anchor)
    else:
        from verify import verify
        return verify(run, anchor)
    code = result.get('outcome_exit_code')
    if code is None and 'passed' in result:
        code = 0 if result['passed'] else 1
    return result, code


def verify_oracle_calibration(run, protocol):
    from business_chain_scoring import score
    from verify import check_events
    totals = []
    for name in protocol['cases']:
        r = json.loads(safe_path(run, name + '/result.json').read_text())
        raw = r['raw']; health = raw['receiver_health']
        events = [json.loads(line) for line in safe_path(run, name + '/events.jsonl').read_text().splitlines()]
        check_events(events, name)
        wire = [e for e in events if e['event'] == 'receiver_request']
        if [{k: e[k] for k in w} for e, w in zip(wire, raw['wire'], strict=True)] != raw['wire']:
            raise ValueError('calibration receiver event differs')
        for stage in ('before', 'after'):
            if [e['healthy'] for e in events if e['event'] == 'receiver_health' and e['stage'] == stage] != [health[stage]]:
                raise ValueError('calibration health event differs')
        if [e['confirmed'] for e in events if e['event'] == 'receiver_closed'] != [health['closed']]:
            raise ValueError('calibration cleanup differs')
        scored = score({'mode': 'oracle_calibration'}, {'case_id': name, 'group': 'B0'}, raw)
        checks = {'healthy_before_fault': health['before'] is True,
                  'measurement_unknown': scored['measurement_complete'] is False,
                  'utility_unknown': scored['utility_completed'] is None,
                  'known_harm_retained_or_unknown': scored['harm_observed'] is True if name.startswith('known-') else scored['harm_observed'] is None,
                  'receiver_closed': health['closed'] is True,
                  'fault_detected': raw['files'][0]['healthy'] is False if name.startswith('file-') else health['after'] is False}
        if r['score'] != scored or r['checks'] != checks or r['passed'] != all(checks.values()):
            raise ValueError('calibration score differs')
        totals.append(all(checks.values()))
    summary = json.loads((run / 'summary.json').read_text())
    if (summary['cases'], summary['passed'], summary['checks'], summary['all_passed']) != (len(totals), sum(totals), len(totals) * 6, all(totals)):
        raise ValueError('calibration summary differs')
    return {**summary, 'outcome_exit_code': 0 if all(totals) else 1}


def inspect_run(campaign, name):
    if Path(name).name != name:
        raise ValueError('run ID must be a single component')
    run = safe_path(campaign, 'data/' + name)
    anchor_path = safe_path(campaign, 'inventory/anchors/' + name + '.json')
    if not anchor_path.exists():
        anchor_path = safe_path(campaign, 'inventory/' + name + '-local-anchor.json')
    anchor = json.loads(anchor_path.read_text())['manifest_sha256']
    if sha256(safe_path(run, 'manifest.json')) != anchor:
        raise ValueError('external manifest anchor mismatch')
    manifest = json.loads((run / 'manifest.json').read_text())
    protocol = json.loads(safe_path(run, 'protocol.json').read_text())
    # Always preserve the distinction between byte integrity and executable scoring.
    artifacts = manifest.get('artifacts')
    if artifacts is None:
        artifacts = json.loads(safe_path(run, 'checksums.json').read_text())
        if sha256(run / 'checksums.json') != manifest['checksums_sha256']:
            raise ValueError('checksum list differs')
    for relative, digest in artifacts.items():
        if sha256(safe_path(run, relative)) != digest:
            raise ValueError('sealed artifact differs: ' + relative)
    status = 'verified_original_evidence'
    try:
        verification, code = dispatch(run, anchor, protocol, manifest['schema_version'])
        if verification.get('preserved_incomplete_run'):
            status = 'verified_preserved_incomplete'
    except ValueError as exc:
        # This exact original F009 was already recorded as invalid, never a pass.
        if name != 'governance-http-001' or str(exc) != 'event sequence differs':
            raise
        prior_path = safe_path(campaign, 'reports/governance-http-001-verification.json')
        prior = json.loads(prior_path.read_text())
        if prior != {'run_id': name, 'integrity_verified': False, 'verifier_error': str(exc), 'passed': False}:
            raise
        verification = {'original_verifier_error': str(exc), 'prior_review_sha256': sha256(prior_path),
                        'byte_integrity_verified': True, 'event_integrity_verified': False, 'finding_id': 'F009'}
        code = 1
        status = 'sealed_original_invalid_run'
    source_maps = {k: v for k, v in protocol.items() if k in ('candidate_sources', 'ablation_sources')}
    # Identity comes from a verified immutable protocol, never just a path/binary name.
    identity = {'candidate_root': protocol.get('candidate_root'),
                'candidate_commit': protocol.get('candidate_commit'), 'candidate_manifest_sha256': protocol.get('candidate_manifest_sha256'),
                'candidate_sources_sha256': hashlib.sha256(canonical(source_maps)).hexdigest(),
                'source_files_registered': {k: len(v) for k, v in source_maps.items()},
                'binary_digest': protocol.get('binary_sha256', protocol.get('candidate_digest')),
                'binaries': protocol.get('binaries'), 'ablation_root': protocol.get('ablation_root'),
                'ablation_identity_sha256': protocol.get('ablation_identity_sha256')}
    identity['profile_sha256'] = hashlib.sha256(canonical(identity)).hexdigest()
    allocation = protocol.get('allocation', [])
    variants = [{k: row[k] for k in ('unit_id', 'case_id', 'variant', 'condition', 'group', 'scenario', 'profile', 'fault', 'output', 'authority', 'timing') if k in row} for row in allocation]
    return {'run_id': name, 'status': status, 'manifest_sha256': anchor,
            'anchor_ref': str(anchor_path.relative_to(campaign)), 'anchor_sha256': sha256(anchor_path),
            'protocol_sha256': sha256(run / 'protocol.json'), 'schema': manifest['schema_version'],
            'candidate_identity': identity, 'registered_variants': variants,
            'sample_set': protocol.get('sample_set'), 'profile': protocol.get('profile'),
            'scope': protocol.get('scope', protocol.get('contract_binding', {}).get('applicability_and_candidate_profile')),
            'original_outcome_exit_code': code, 'verification': verification,
            'reused_as': 'scoped original observations including failures, never a new execution or aggregate pass'}


def reconcile(campaign, specification):
    runs = {}
    names = sorted({name for journey in specification['journeys'] for block in journey['evidence_blocks'] for name in block['runs']})
    for name in names:
        try:
            runs[name] = inspect_run(campaign, name)
        except (OSError, ValueError, KeyError, AssertionError) as exc:
            runs[name] = {'run_id': name, 'status': 'verification_unresolved', 'error_type': type(exc).__name__, 'error': str(exc), 'reused_as': None}
    journeys = []
    for row in specification['journeys']:
        blocks = []
        for block in row['evidence_blocks']:
            good = [n for n in block['runs'] if runs[n]['status'] != 'verification_unresolved']
            identities = sorted({runs[n]['candidate_identity']['profile_sha256'] for n in good})
            blocks.append({**block, 'reconciled_run_ids': good,
                           'scored_run_ids': [n for n in good if runs[n]['status'] == 'verified_original_evidence'],
                           'preserved_noncompletion_run_ids': [n for n in good if runs[n]['status'] != 'verified_original_evidence'],
                           'candidate_profiles': identities,
                           'status': 'scoped_material_reconciled' if len(good) == len(block['runs']) else 'verification_incomplete',
                           'full_variant_acceptance': False})
        journeys.append({**row, 'evidence_blocks': blocks,
                         'review_status': 'scoped_evidence_reconciled' if blocks and all(b['status'] == 'scoped_material_reconciled' for b in blocks) else 'verification_incomplete' if blocks else 'no_candidate_bound_campaign_evidence',
                         'journey_complete': False, 'new_executions': 0})
    return {'schema_version': 'siq-journey-evidence-reuse-review/v1', 'checked_at': utc_now(),
            'scope': 'read-only author-side re-verification; preserves failures, utility loss and mixed candidate identities; no new run, certificate or journey closure',
            'journeys': journeys, 'runs': runs,
            'totals': {'journeys_reviewed': len(journeys), 'distinct_runs': len(runs), 'runs_verified': sum(r['status'] == 'verified_original_evidence' for r in runs.values()),
                       'preserved_incomplete_runs': sum(r['status'] == 'verified_preserved_incomplete' for r in runs.values()),
                       'preserved_invalid_runs': sum(r['status'] == 'sealed_original_invalid_run' for r in runs.values()),
                       'runs_unresolved': sum(r['status'] == 'verification_unresolved' for r in runs.values()),
                       'new_executions': 0, 'paid_model_calls': 0, 'journeys_closed': 0}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--specification', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    specification = json.loads(args.specification.read_text())
    report = reconcile(args.campaign.resolve(), specification)
    report['specification'] = {'path': str(args.specification), 'sha256': sha256(args.specification)}
    write_json(args.out, report)
    print(json.dumps(report['totals']))
    return int(bool(report['totals']['runs_unresolved']))


if __name__ == '__main__':
    raise SystemExit(main())
