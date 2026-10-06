"""Verify byte-preserving evaluation relocation or materialize its old layout."""
import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

SOURCE = 'd80879cbbddb05abaaaa42c69fd7f82e30bf3bc4'
MANIFEST = 'evaluations/migrations/20261007/manifest.json'
PREFIX = 'third-party-evaluation/'


def checked_path(root, name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        raise ValueError('unsafe migration path')
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('migration escapes root')
    if any(p.is_symlink() for p in [target, *target.parents] if p.is_relative_to(root)):
        raise ValueError('symlink in migration path')
    return target


def verify_migration(root, expected_source=SOURCE):
    manifest = json.loads((root / MANIFEST).read_text())
    if manifest['source_commit'] != expected_source or manifest['source_prefix'] != PREFIX:
        raise ValueError('migration source identity changed')
    if (root / PREFIX).exists() or (root / PREFIX).is_symlink():
        raise ValueError('retired evaluation root still exists')
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-rz', expected_source, '--', PREFIX])
    originals = {}
    for record in raw.split(b'\0'):
        if record:
            metadata, name = record.split(b'\t', 1)
            mode, kind, oid = metadata.decode().split()
            if kind != 'blob' or mode != '100644':
                raise ValueError('unexpected frozen source type')
            originals[name.decode()] = oid
    rows = manifest['entries']
    if len(rows) != len(originals) or {r['source'] for r in rows} != set(originals):
        raise ValueError('incomplete or duplicate relocation inventory')
    blob_data = subprocess.check_output(
        ['git', '-C', str(root), 'cat-file', '--batch'],
        input=''.join(originals[r['source']] + '\n' for r in rows).encode())
    stream = io.BytesIO(blob_data)
    frozen = set()
    for row in rows:
        header = stream.readline().split()
        if len(header) != 3 or header[1] != b'blob':
            raise ValueError('missing frozen Git object')
        data = stream.read(int(header[2])); stream.read(1)
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('source digest mismatch: ' + row['source'])
        action, target = row['action'], row['destination']
        if action == 'retire':
            if target is not None or row['source'].startswith(PREFIX + '20261006/'):
                raise ValueError('campaign evidence cannot be retired')
            continue
        if action not in ('move', 'deduplicate') or not target.startswith('evaluations/'):
            raise ValueError('invalid relocation destination')
        path = checked_path(root, target)
        if path.read_bytes() != data:
            raise ValueError('relocated bytes changed: ' + target)
        frozen.add(target)
    return frozen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--materialize', type=Path, help='Create a NEW external directory containing the frozen old layout')
    args = parser.parse_args()
    root = args.root.resolve()
    frozen = verify_migration(root)
    if args.materialize:
        output = args.materialize.resolve()
        if output.is_relative_to(root) or output.exists():
            parser.error('materialize requires a new directory outside this repository')
        archive = subprocess.check_output(['git', '-C', str(root), 'archive', SOURCE, PREFIX])
        output.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(output, filter='data')
    print(json.dumps({'result': 'passed', 'preserved_files': len(frozen),
                      'source_commit': SOURCE, 'materialized': bool(args.materialize)}))


if __name__ == '__main__':
    main()
