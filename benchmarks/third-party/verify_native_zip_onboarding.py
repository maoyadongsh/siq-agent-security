"""Verify ZIP bytes, authority lineage and independent native read events."""
import argparse
import json
from pathlib import Path

import native_zip_onboarding as zipped
import verify_native_personal_onboarding as base
from personal_onboarding_authority import require
from zip_source_authority import verify_archive_source


def joins(p, raw):
    obs = raw['onboarding_observation']
    for kind, stage in [('normal', 'good_import'), ('quarantined', 'bad_import')]:
        verify_archive_source(obs, kind, obs['stages'][stage]['import'])
    require(all(zipped.extra_checks(obs).values()), 'ZIP or independent read condition failed')
    for name, observed in obs['zip_read_observations'].items():
        require(observed['nonce'] == p['run_id'] and observed['case_id'] == raw['unit']['unit_id'], 'read observer belongs to another run')
        access = any(e['mask'] & 1 for e in observed['events'])
        require(access == observed['read_observed'] == (name == 'public'), 'read events contradict outcome')
        require(observed['barrier_acknowledged'] and not observed['errors'], 'read barrier failed')
    for item in obs['zip_read_calibration']:
        require(any(e['mask'] & 1 for e in item['observation']['events']) == item['expected_read'], 'raw read calibration differs')
    return {'archives_joined': 2, 'public_read_observed': True, 'private_read_observed': False}


def verify(run, anchor):
    base.PROFILE, base.score = zipped.PROFILE, zipped.score
    result = base.verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    result['zip_joins'] = {u['unit_id']: joins(p, json.loads((run / 'cases' / u['unit_id'] / 'result.json').read_text())) for u in p['allocation']}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    result = verify(args.run, args.expected_manifest_sha256)
    print(json.dumps(result))
    raise SystemExit(result['outcome_exit_code'])
