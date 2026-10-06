"""Exact-limit and limit-plus-one imports through the actual management API."""
import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path

import source_import_trial as base
from common import sha256, utc_now, write_json
from source_import_scoring import canonical
from source_import_scoring import score as original_score

LIMITS = {'archive': 32 << 20, 'file': 8 << 20, 'total': 64 << 20, 'files': 2000, 'directories': 2000, 'depth': 16}


def inspect_archive(path):
    files, directories = [], set()
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            name = item.filename.rstrip('/')
            parts = name.split('/')
            directories.update('/'.join(parts[:i]) for i in range(1, len(parts)))
            if item.is_dir():
                directories.add(name)
            else:
                files.append({'path': name, 'bytes': item.file_size, 'sha256': hashlib.sha256(archive.read(item)).hexdigest(), 'executable': bool((item.external_attr >> 16) & 0o111)})
    files.sort(key=lambda f: f['path'])
    tree = {'files': files, 'directories': sorted(directories)}
    metrics = {'archive': path.stat().st_size, 'file': max(f['bytes'] for f in files), 'total': sum(f['bytes'] for f in files),
               'files': len(files), 'directories': len(directories), 'depth': max(len(n.split('/')) for n in [f['path'] for f in files] + list(directories))}
    return {'metrics': metrics, 'tree': tree, 'artifact_digest': hashlib.sha256(canonical(tree)).hexdigest(), 'sha256': sha256(path)}


def create_fixture(path, axis, value):
    regular = stat.S_IFREG | 0o600
    entries = [('SKILL.md', base.SKILL, regular)]
    compression = zipfile.ZIP_DEFLATED
    if axis == 'file':
        entries.append(('data.bin', b'\0' * value, regular))
    elif axis == 'total':
        remaining = value - len(base.SKILL)
        while remaining:
            count = min(remaining, LIMITS['file'])
            entries.append((f'data-{len(entries):02d}.bin', b'\0' * count, regular))
            remaining -= count
    elif axis == 'files':
        entries.extend((f'f-{i:04d}.txt', b'', regular) for i in range(value - 1))
    elif axis == 'directories':
        entries.extend((f'd-{i:04d}/', b'', stat.S_IFDIR | 0o700) for i in range(value))
    elif axis == 'depth':
        entries.append(('/'.join(['d'] * (value - 1) + ['data.txt']), b'x', regular))
    elif axis == 'archive':
        # ZIP_STORED permits an exact byte size without malformed trailing padding.
        names = ['SKILL.md'] + [f'data-{i}.bin' for i in range(4)]
        overhead = 22 + sum(30 + len(n.encode()) + 46 + len(n.encode()) for n in names)
        remaining = value - overhead - len(base.SKILL)
        for name in names[1:]:
            count = min(remaining, LIMITS['file'])
            entries.append((name, b'\0' * count, regular))
            remaining -= count
        assert remaining == 0
        compression = zipfile.ZIP_STORED
    else:
        raise ValueError('unknown boundary')
    with zipfile.ZipFile(path, 'x') as archive:
        for name, content, mode in entries:
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = compression
            archive.writestr(info, content)
    metadata = inspect_archive(path)
    assert metadata['metrics'][axis] == value
    assert all(v <= LIMITS[k] for k, v in metadata['metrics'].items() if k != axis)
    return metadata


def score(p, raw):
    result = original_score(p, raw)
    checks = result['checks']
    by_id = {r['id']: r for r in raw['http']}
    for axis in LIMITS:
        for suffix in ('limit', 'over', 'recovery'):
            name = axis + '_' + suffix
            row = by_id.get(name, {})
            meta = p['boundary_fixtures'][name]
            if suffix == 'over':
                checks[name + '.no_directory_residue'] = 'before_directories' in row and row['before_directories'] == row.get('after_directories')
            else:
                record = row.get('body', {}).get('import', {})
                checks[name + '.exact_tree'] = record.get('files') == meta['tree']['files'] and record.get('directories') == meta['tree']['directories']
                checks[name + '.tree_digest'] = record.get('artifact_digest') == meta['artifact_digest']
                if suffix == 'recovery':
                    checks[name + '.reuses_rejected_id'] = row.get('request', {}).get('import_id') == by_id.get(axis + '_over', {}).get('request', {}).get('import_id')
    result.update(passed=sum(checks.values()), total=len(checks), all_passed=all(checks.values()), scope='six exact/plus-one local ZIP boundaries and same rejected-ID recovery; management API only; no native or model attack claim')
    return result


def freeze(campaign, run_id):
    path = base.freeze(campaign, run_id)
    p = json.loads(path.read_text())
    folder = path.parent / 'fixtures'
    root = campaign / 'private/runs' / run_id / 'state-private/fixtures'
    metadata, requests = {}, []
    for index, (axis, limit) in enumerate(LIMITS.items()):
        for suffix in ('limit', 'over', 'recovery'):
            name = axis + '_' + suffix
            archive = folder / (name + '.zip') if suffix != 'recovery' else folder / 'normal.zip'
            meta = inspect_archive(archive) if suffix == 'recovery' else create_fixture(archive, axis, limit + (suffix == 'over'))
            metadata[name] = {**meta, 'filename': archive.name, 'axis': axis, 'boundary': limit, 'variant': suffix}
            rejected = suffix == 'over'
            number = 100 + index * 2 + (suffix != 'limit')
            status = (400 if axis == 'depth' else 413) if rejected else 201
            error = ('skill_import_invalid' if axis == 'depth' else 'skill_import_limit') if rejected else None
            body = {'schema_version': 'local-skill-import-create/v1', 'import_id': 'si-' + f'{number:032x}', 'source_kind': 'local_zip', 'path': str(root / archive.name), 'actor_id': 'source-evaluation-operator'}
            requests.append({'id': name, 'route': '/v1/skill-imports', 'body': body, 'status': status, 'error': error})
    registration = campaign / 'plan/source-budget-boundaries-001.md'
    p.update(profile='source-budget', frozen_at=utc_now(), requests=requests, boundary_fixtures=metadata, fixtures=base.tree(folder), timeout_seconds=420, capture_import_directories=True,
             registration={'path': str(registration), 'sha256': sha256(registration)}, scope='six local ZIP exact/plus-one boundaries; same rejected-ID recovery; real daemon; no model or external network')
    for name in ('source_budget_trial.py', 'verify_source_budget.py'):
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
