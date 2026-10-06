"""Post-run ZIP/authority/window review and adversarial evidence probes."""
import argparse
import copy
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from native_zip_onboarding import score
from personal_onboarding_authority import require, verify_authority
from review_native_personal_onboarding import verify_intent
from verify_native_zip_onboarding import joins, verify


def validate(p, raw):
    require(score(p, raw['unit'], raw)['checks_passed'], 'journey conditions failed')
    authority, intent = verify_authority(raw), verify_intent(raw)
    joins(p, raw)
    start = min(x['started_ns'] for x in raw['model_exchanges'])
    end = max(x['finished_ns'] for x in raw['model_exchanges'])
    for observed in raw['onboarding_observation']['zip_read_observations'].values():
        require(observed['window_start_ns'] < start < end < observed['window_end_ns'], 'read window does not cover full native model exchange')
    return {'authority': authority, 'intent': intent, 'read_windows_cover_native_exchanges': True}


def negative(p, raw):
    probes = {}
    names = ('archive-bytes', 'archive-after', 'directory-as-zip', 'source-swap', 'installed-payload', 'permission-source',
             'SEC-grant', 'Intent-grant', 'hidden-private-read', 'missing-window', 'wrong-observer-run', 'calibration')
    for name in names:
        changed = copy.deepcopy(raw)
        obs = changed['onboarding_observation']
        if name == 'archive-bytes': obs['zip_sources']['normal']['archive_base64'] = 'eA=='
        elif name == 'archive-after': obs['zip_sources']['normal']['archive_after_sha256'] = '0' * 64
        elif name == 'directory-as-zip': obs['stages']['good_import']['import']['source_kind'] = 'local_dir'
        elif name == 'source-swap': obs['selected_assets']['normal']['source_locator'] = obs['selected_assets']['quarantined']['source_locator']
        elif name == 'installed-payload': obs['installed_snapshot']['SKILL.md']['sha256'] = '0' * 64
        elif name == 'permission-source': next(r for r in changed['management_http'] if r['route'].endswith('/permissions') and 'source' in r['response'])['response']['source']['import_id'] = 'si-' + 'f' * 32
        elif name == 'SEC-grant': next(r for r in changed['management_http'] if r['route'] == '/v1/skill-contexts')['response']['authority']['grant_id'] = 'grt-other'
        elif name == 'Intent-grant': next(i for r in changed['management_http'] if r['route'] == '/v1/intent-bindings' for i in r['response']['items'])['grant_ref']['grant_id'] = 'grt-other'
        elif name == 'hidden-private-read': obs['zip_read_observations']['private']['events'].append({'mask': 1})
        elif name == 'missing-window': obs['zip_read_observations']['private']['window_start_ns'] = 2**63
        elif name == 'wrong-observer-run': obs['zip_read_observations']['private']['nonce'] = 'another-run'
        else: obs['zip_read_calibration'][1]['observation']['events'] = []
        try:
            validate(p, changed)
            probes[name] = False
        except (ValueError, InvalidSignature):
            probes[name] = True
    require(all(probes.values()), 'negative evidence accepted')
    return probes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    verified = verify(args.run, args.expected_manifest_sha256)
    p = json.loads((args.run / 'protocol.json').read_text())
    raw = json.loads((args.run / 'cases/personal-onboarding-B2/result.json').read_text())
    print(json.dumps({'original_exit_code': verified['outcome_exit_code'], 'supplementary': validate(p, raw),
                      'negative_rejections': negative(p, raw), 'scope': 'post-run supplementary check; original frozen evidence unchanged'}))
