"""Verify and locally export a sealed native journey, preserving failed outcomes."""
import argparse
import base64
import json
import shutil
from pathlib import Path

from common import safe_path, sha256, utc_now, write_json
from verify_native_lifecycle import verify


def export(campaign, run_id):
    source = safe_path(campaign / 'private/runs', run_id)
    anchor = sha256(source / 'manifest.json')
    result, outcome_code = verify(source, anchor)
    manifest = json.loads((source / 'manifest.json').read_text())
    names = [*manifest['artifacts'], 'manifest.json']
    secrets = []
    for path in (source / 'state-private').rglob('*'):
        if path.is_file() and (path.name in ('token', 'signing.seed') or path.suffix in ('.token', '.key', '.credential')):
            for raw in (path.read_bytes(), path.read_bytes().strip()):
                if len(raw) >= 16:
                    secrets.extend([raw, raw.hex().encode(), base64.b64encode(raw)])
    secrets.extend(p.read_bytes().strip() for p in (campaign / 'private/credentials').glob('*.key'))
    for name in names:
        if '/' in name or (name.startswith('.') and name != '.writer.lock'):
            raise ValueError('native export only permits sealed top-level files')
        data = safe_path(source, name).read_bytes()
        if any(secret and secret in data for secret in secrets):
            raise ValueError('credential detected; export stopped')
    destination = safe_path(campaign / 'data', run_id)
    destination.mkdir(exist_ok=False)
    for name in names:
        shutil.copy2(source / name, destination / name)
    write_json(campaign / 'inventory/anchors' / (run_id + '.json'), {'manifest_sha256': anchor, 'custody': 'author_local'})
    write_json(campaign / 'reports' / (run_id + '-verification.json'), result)
    write_json(campaign / 'reports' / (run_id + '-export-review.json'), {
        'checked_at': utc_now(), 'manifest_sha256': anchor, 'files_checked': len(names), 'known_credential_matches': 0,
        'cleanup': json.loads((source / 'cleanup.json').read_text()), 'outcome_exit_code': outcome_code,
        'whitelist': 'sealed top-level artifacts only; no state directory'})
    return {'run_id': run_id, 'manifest_sha256': anchor, 'exported': True, 'measurement_outcome_exit_code': outcome_code, 'verification': result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.campaign.resolve(), args.run_id)))
