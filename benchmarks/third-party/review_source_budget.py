"""Supplementary joins for frozen ZIP budgets and raw effect observations."""
import argparse
import copy
import hashlib
import json
import zipfile
from pathlib import Path

from common import sha256
from source_budget_trial import LIMITS, score
from source_import_scoring import canonical


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fixtures(p, directory):
    joined = {}
    for name, expected in p['boundary_fixtures'].items():
        path = directory / expected['filename']
        require(sha256(path) == expected['sha256'], 'fixture identity differs')
        with zipfile.ZipFile(path) as archive:
            files, dirs = [], set()
            for item in archive.infolist():
                rel = item.filename.rstrip('/')
                parts = rel.split('/')
                dirs.update('/'.join(parts[:n]) for n in range(1, len(parts)))
                if item.is_dir():
                    dirs.add(rel)
                else:
                    data = archive.read(item)
                    files.append({'path': rel, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'executable': bool((item.external_attr >> 16) & 0o111)})
        files.sort(key=lambda x: x['path'])
        tree = {'files': files, 'directories': sorted(dirs)}
        metrics = {'archive': path.stat().st_size, 'file': max(f['bytes'] for f in files), 'total': sum(f['bytes'] for f in files), 'files': len(files), 'directories': len(dirs),
                   'depth': max(len(n.split('/')) for n in [f['path'] for f in files] + list(dirs))}
        require(tree == expected['tree'] and metrics == expected['metrics'], 'fixture tree/metric differs')
        require(hashlib.sha256(canonical(tree)).hexdigest() == expected['artifact_digest'], 'fixture digest differs')
        axis, variant = expected['axis'], expected['variant']
        if variant != 'recovery':
            require(metrics[axis] == LIMITS[axis] + (variant == 'over'), 'boundary differs')
        require(all(v <= LIMITS[k] for k, v in metrics.items() if k != axis or variant != 'over'), 'other boundary exceeded')
        joined[name] = metrics
    return joined


def validate(p, raw):
    require(score(p, raw)['all_passed'], 'frozen checks failed')
    stamps = [r['monotonic_ns'] for r in raw['http']]
    require(stamps == sorted(set(stamps)), 'request order differs')
    mask = 2 | 64 | 128 | 256 | 512
    for guard in raw['guards']:
        require(guard['nonce'] == p['run_id'] and guard['case_id'] == 'source-management', 'borrowed guard')
        require(guard['window_start_ns'] < min(stamps) <= max(stamps) < guard['window_end_ns'], 'guard window differs')
        require(guard['errors'] == [] and guard['barrier_acknowledged'], 'guard barrier failed')
        require(not any(e['mask'] & mask for e in guard['events']), 'transient effect')
        require(not guard['before']['exists'] and not guard['after']['exists'], 'escape target exists')
    for calibration in raw['calibration']:
        require(any(e['mask'] & mask for e in calibration['observation']['events']) == calibration['expected'], 'calibration contradicts events')
    return True


def negatives(p, raw):
    mutations = {
        'hidden_transient_write': lambda r: r['guards'][0]['events'].append({'mask': 256}),
        'window_misses_request': lambda r: r['guards'][0].update(window_start_ns=r['http'][-1]['monotonic_ns']),
        'borrowed_guard': lambda r: r['guards'][0].update(nonce='different-run'),
        'false_calibration': lambda r: r['calibration'][1]['observation'].update(events=[]),
        'wrong_rejection_layer': lambda r: r['http'][1]['body'].update(error='authentication_required'),
        'empty_directory_residue': lambda r: r['http'][1]['after_directories'].append('blobs/incomplete/payload'),
        'different_recovery_id': lambda r: r['http'][2]['request'].update(import_id='si-' + 'f' * 32),
        'false_file_publication': lambda r: r['http'][1]['after'].update({'records/invalid.json': {'sha256': '0' * 64}}),
        'invalid_signature': lambda r: r['http'][0]['body']['import'].update(signature='0' * 128),
        'unexpected_grant': lambda r: r['authority_files'].append('grants/unapproved.json'),
        'incomplete_rows': lambda r: r['http'].pop(),
        'daemon_live': lambda r: r['cleanup'].update(daemon_stopped=False),
    }
    rejected = {}
    for name, mutate in mutations.items():
        altered = copy.deepcopy(raw)
        mutate(altered)
        try:
            validate(p, altered)
            rejected[name] = False
        except (ValueError, KeyError):
            rejected[name] = True
    require(all(rejected.values()), 'invalid evidence accepted')
    return rejected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--fixtures', type=Path, required=True)
    args = parser.parse_args()
    p = json.loads((args.run / 'protocol.json').read_text())
    raw = json.loads((args.run / 'result.json').read_text())
    print(json.dumps({'fixture_metrics': fixtures(p, args.fixtures), 'raw_observer_joins': validate(p, raw), 'negative_rejections': negatives(p, raw),
                      'scope': 'post-run author review; use original frozen verifier separately; no original scoring changes'}))
