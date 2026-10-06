"""Real path/ZIP parser boundary and full import-store reuse controls."""
import argparse
import json
import stat
import struct
import zipfile
from pathlib import Path

import source_import_trial as base
from common import sha256, utc_now, write_json
from source_budget_trial import inspect_archive
from source_import_scoring import score as original_score


def central_size(path):
    raw = path.read_bytes()
    if raw[-22:-18] != b'PK\x05\x06' or raw[-2:] != b'\0\0':
        raise ValueError('unexpected ZIP end record')
    return struct.unpack_from('<I', raw, len(raw) - 10)[0]


def fixture(path, axis, limit):
    entries = [('SKILL.md', base.SKILL)]
    if axis == 'component':
        entries.append(('x' * limit, b''))
    elif axis == 'path':
        entries.append(('/'.join(['x' * 128] * 3 + ['y' * (limit - 387)]), b''))
    elif axis == 'central':
        entries += [(f'f-{i:02d}.txt', b'') for i in range(63)]
    else:
        raise ValueError('invalid fixture axis')
    comment_remaining = limit - sum(46 + len(n) for n, _ in entries) if axis == 'central' else 0
    with zipfile.ZipFile(path, 'x') as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            size = min(comment_remaining, 65535)
            info.comment = b'x' * size
            comment_remaining -= size
            archive.writestr(info, data)
    assert comment_remaining == 0
    metadata = inspect_archive(path)
    metadata.update(filename=path.name, central_bytes=central_size(path), path_bytes=max(len(f['path'].encode()) for f in metadata['tree']['files']),
                    component_bytes=max(len(part.encode()) for f in metadata['tree']['files'] for part in f['path'].split('/')))
    assert metadata[{'component': 'component_bytes', 'path': 'path_bytes', 'central': 'central_bytes'}[axis]] == limit
    return metadata


def score(p, raw):
    result = original_score(p, raw)
    checks = result['checks']
    by_id = {r['id']: r for r in raw['http']}
    for wanted in p['requests']:
        name = wanted['id']
        row = by_id.get(name, {})
        if wanted['status'] >= 400:
            checks[name + '.no_directory_residue'] = 'before_directories' in row and row['before_directories'] == row.get('after_directories')
        else:
            record = row.get('body', {}).get('import', {})
            meta = p['record_fixtures'][name]
            checks[name + '.exact_tree'] = record.get('files') == meta['tree']['files'] and record.get('directories') == meta['tree']['directories'] and record.get('artifact_digest') == meta['artifact_digest']
    first = by_id.get('normal', {}).get('body', {}).get('import')
    for name in ('full_retry', 'full_read'):
        row = by_id.get(name, {})
        checks[name + '.original_record'] = bool(first) and row.get('body', {}).get('import') == first
        checks[name + '.no_state_change'] = bool(row) and row['before'] == row['after'] and row['before_directories'] == row['after_directories']
    checks['full_retry.reused'] = by_id.get('full_retry', {}).get('body', {}).get('reused') is True
    final = raw['http'][-1] if raw['http'] else {}
    records = sorted(n for n in final.get('after', {}) if n.startswith('records/') and n.endswith('.json'))
    expected = sorted('records/' + w['body']['import_id'] + '.json' for w in p['requests'] if w['status'] == 201)
    checks['exact_64_published_ids'] = len(expected) == 64 and records == expected
    checks['exact_64_blob_ids'] = sorted(n for n in final.get('after_directories', []) if n.startswith('blobs/') and n.count('/') == 1) == sorted('blobs/' + w['body']['import_id'] for w in p['requests'] if w['status'] == 201)
    result.update(passed=sum(checks.values()), total=len(checks), all_passed=all(checks.values()), scope='path component/total and central-directory boundary; 64-slot store plus failed-new/reuse/conflict/read controls; management only')
    return result


def freeze(campaign, run_id):
    path = base.freeze(campaign, run_id)
    p = json.loads(path.read_text())
    folder = path.parent / 'fixtures'
    root = campaign / 'private/runs' / run_id / 'state-private/fixtures'
    normal = inspect_archive(folder / 'normal.zip')
    normal['filename'] = 'normal.zip'
    metadata = {'normal': normal}
    requests, expected = [], {}
    next_id = 1000

    def add(name, meta, status, error=None, body=None, route='/v1/skill-imports'):
        nonlocal next_id
        if body is None:
            body = {'schema_version': 'local-skill-import-create/v1', 'import_id': 'si-' + f'{next_id:032x}', 'source_kind': 'local_zip', 'path': str(root / meta['filename']), 'actor_id': 'source-evaluation-operator'}
            next_id += 1
        requests.append({'id': name, 'route': route, 'body': body, 'status': status, 'error': error})
        if status < 400:
            expected[name] = meta
        return body

    first = add('normal', normal, 201)
    for axis, limit in [('component', 128), ('path', 512), ('central', 4 << 20)]:
        for suffix, value in [('limit', limit), ('over', limit + 1)]:
            name = axis + '_' + suffix
            metadata[name] = fixture(folder / (name + '.zip'), axis, value)
            status = 201 if suffix == 'limit' else 413 if axis == 'central' else 400
            error = None if status == 201 else 'skill_import_limit' if status == 413 else 'skill_import_invalid'
            add(name, metadata[name], status, error)
    for i in range(60):
        add(f'fill_{i + 5:02d}', normal, 201)
    add('full_new', normal, 413, 'skill_import_limit')
    add('full_retry', normal, 200, body=first)
    add('full_conflict', normal, 409, 'skill_import_conflict', body={**first, 'actor_id': 'another-actor'})
    requests.append({'id': 'full_read', 'route': '/v1/skill-imports/' + first['import_id'], 'body': None, 'status': 200, 'error': None})
    expected['full_read'] = normal
    registration = campaign / 'plan/source-path-slots-001.md'
    p.update(profile='source-path-slots', frozen_at=utc_now(), requests=requests, boundary_fixtures=metadata, record_fixtures=expected, fixtures=base.tree(folder), timeout_seconds=420, capture_import_directories=True,
             registration={'path': str(registration), 'sha256': sha256(registration)}, scope='71 real local import API requests; path/central boundaries and 64-slot reuse; no runtime/model execution')
    for name in ('source_limits_trial.py', 'source_budget_trial.py', 'verify_source_limits.py'):
        (path.parent / 'harness-source' / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    p['harness_sources'] = {str(f.relative_to(path.parent / 'harness-source')): sha256(f) for f in (path.parent / 'harness-source').rglob('*') if f.is_file()}
    write_json(path, p, exclusive=False)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--protocol', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        print(freeze(args.campaign.resolve(), args.run_id))
    else:
        base.score = score
        raise SystemExit(base.execute(args.protocol))
