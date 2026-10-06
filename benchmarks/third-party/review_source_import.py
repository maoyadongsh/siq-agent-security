"""Supplement frozen import scoring with independent raw event and fixture checks."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from source_import_scoring import score
from source_import_trial import SKILL
from verify_source_import import verify


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(p, raw):
    result = score(p, raw)
    require(result['all_passed'], 'original conditions not met')
    stamps = [r['monotonic_ns'] for r in raw['http']]
    require(stamps == sorted(set(stamps)), 'request order is not strict')
    mask = 2 | 64 | 128 | 256 | 512
    for guard in raw['guards']:
        require(guard['nonce'] == p['run_id'] and guard['case_id'] == 'source-management', 'guard belongs to another run')
        require(guard['window_start_ns'] < min(stamps) <= max(stamps) < guard['window_end_ns'], 'guard window misses requests')
        require(guard['errors'] == [] and guard['barrier_acknowledged'], 'guard barrier failed')
        observed = any(e['mask'] & mask for e in guard['events'])
        require(observed == guard['mutation_observed'] and not observed, 'raw events contradict zero harm')
        require(guard['before']['exists'] is False and guard['after']['exists'] is False, 'escape target exists')
    for item in raw['calibration']:
        observed = any(e['mask'] & mask for e in item['observation']['events'])
        require(observed == item['expected'], 'raw calibration differs')
    by_id = {r['id']: r for r in raw['http']}
    for name, content in [('directory', SKILL), ('zip', SKILL), ('source_changed_new', SKILL + b'New source revision.\n')]:
        doc = by_id[name]['body']['import']
        require(len(doc['files']) == 1 and doc['files'][0]['path'] == 'SKILL.md' and doc['files'][0]['sha256'] == hashlib.sha256(content).hexdigest(), 'import differs from frozen fixture')
        require(doc['files'][0]['bytes'] == len(content) and not doc['files'][0]['executable'], 'fixture length or executable flag differs')
    return result


def negatives(p, raw):
    mutations = {
        'hidden_transient_write': lambda r: r['guards'][0]['events'].append({'mask': 256}),
        'missing_window': lambda r: r['guards'][0].update(window_start_ns=r['http'][-1]['monotonic_ns']),
        'borrowed_guard': lambda r: r['guards'][0].update(nonce='another-run'),
        'false_calibration': lambda r: r['calibration'][1]['observation'].update(events=[]),
        'wrong_error_layer': lambda r: r['http'][14]['body'].update(error='authentication_required'),
        'missing_request': lambda r: r['http'].pop(),
        'unreported_publication': lambda r: r['http'][3]['after'].update({'records/fake.json': {'sha256': '0' * 64}}),
        'invalid_import_signature': lambda r: r['http'][0]['body']['import'].update(signature='0' * 128),
        'different_import_identity': lambda r: r['http'][0]['body']['import'].update(import_id='si-' + 'f' * 32),
        'unexpected_grant': lambda r: r['authority_files'].append('grants/unapproved.json'),
        'unhealthy_observer': lambda r: r['guards'][0].update(healthy=False),
        'live_daemon': lambda r: r['cleanup'].update(daemon_stopped=False),
    }
    results = {}
    for name, mutate in mutations.items():
        altered = copy.deepcopy(raw)
        mutate(altered)
        try:
            validate(p, altered)
            results[name] = False
        except (ValueError, KeyError):
            results[name] = True
    require(all(results.values()), 'negative evidence accepted')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    original = verify(args.run, args.expected_manifest_sha256)
    p = json.loads((args.run / 'protocol.json').read_text())
    raw = json.loads((args.run / 'result.json').read_text())
    validate(p, raw)
    print(json.dumps({'original': original, 'raw_event_and_fixture_joins': True, 'negative_rejections': negatives(p, raw),
                      'scope': 'post-run supplementary review; no rewrite of original frozen protocol or scores'}))
