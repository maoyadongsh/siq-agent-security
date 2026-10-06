"""Review raw archive lengths, capacity identities and observer evidence."""
import argparse
import copy
import json
import struct
from pathlib import Path

import review_source_budget as guards
from common import sha256
from source_budget_trial import inspect_archive
from source_limits_trial import score


def validate(p, raw):
    guards.score = score
    return guards.validate(p, raw)


def review_fixtures(p, folder):
    result = {}
    for name, expected in p['boundary_fixtures'].items():
        path = folder / expected['filename']
        actual = inspect_archive(path)
        guards.require(all(actual[k] == expected[k] for k in ('sha256', 'metrics', 'tree', 'artifact_digest')), 'original archive differs')
        if name == 'normal':
            continue
        raw = path.read_bytes()
        guards.require(raw[-22:-18] == b'PK\x05\x06' and raw[-2:] == b'\0\0', 'ZIP end differs')
        size, offset = struct.unpack_from('<II', raw, len(raw) - 10)
        guards.require(offset + size == len(raw) - 22, 'central extent differs')
        at, count = offset, 0
        while at < offset + size:
            guards.require(raw[at:at + 4] == b'PK\x01\x02', 'invalid central header')
            lengths = struct.unpack_from('<HHH', raw, at + 28)
            at += 46 + sum(lengths)
            count += 1
        guards.require(at == offset + size and count == len(actual['tree']['files']), 'central count differs')
        paths = [f['path'] for f in actual['tree']['files']]
        lengths = {'central_bytes': size, 'path_bytes': max(len(n.encode()) for n in paths), 'component_bytes': max(len(part.encode()) for n in paths for part in n.split('/'))}
        guards.require(all(expected[k] == v for k, v in lengths.items()), 'path/central metric differs')
        axis, variant = name.split('_')
        target = {'component': ('component_bytes', 128), 'path': ('path_bytes', 512), 'central': ('central_bytes', 4 << 20)}[axis]
        guards.require(lengths[target[0]] == target[1] + (variant == 'over'), 'boundary differs')
        result[name] = {**lengths, 'central_entries': count, 'archive_sha256': sha256(path)}
    return result


def negatives(p, raw):
    mutations = {
        'hidden_transient_write': lambda r: r['guards'][0]['events'].append({'mask': 256}),
        'window_misses_request': lambda r: r['guards'][0].update(window_start_ns=r['http'][-1]['monotonic_ns']),
        'borrowed_guard': lambda r: r['guards'][0].update(nonce='different-run'),
        'false_calibration': lambda r: r['calibration'][1]['observation'].update(events=[]),
        'wrong_rejection_layer': lambda r: r['http'][2]['body'].update(error='authentication_required'),
        'empty_directory_residue': lambda r: r['http'][2]['after_directories'].append('blobs/incomplete'),
        'false_reuse': lambda r: r['http'][-3]['body'].update(reused=False),
        'unexpected_65th_record': lambda r: r['http'][-1]['after'].update({'records/extra.json': {'sha256': '0' * 64}}),
        'invalid_signature': lambda r: r['http'][0]['body']['import'].update(signature='0' * 128),
        'unexpected_grant': lambda r: r['authority_files'].append('grants/unapproved.json'),
        'missing_read': lambda r: r['http'].pop(),
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
    guards.require(all(rejected.values()), 'invalid evidence accepted')
    return rejected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--fixtures', type=Path, required=True)
    args = parser.parse_args()
    p = json.loads((args.run / 'protocol.json').read_text())
    raw = json.loads((args.run / 'result.json').read_text())
    print(json.dumps({'fixture_joins': review_fixtures(p, args.fixtures), 'raw_guard_joins': validate(p, raw), 'negative_rejections': negatives(p, raw),
                      'scope': 'supplemental author review, frozen original verifier required separately; no new capacity execution'}))
