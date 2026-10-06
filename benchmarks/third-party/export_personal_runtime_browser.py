"""Allowlisted local browser evidence export; excludes browser profiles and host state."""
import argparse
import base64
import json
import re
from pathlib import Path

from common import safe_path, sha256, utc_now, write_json


def export(campaign, run_id, anchor):
    if Path(run_id).name != run_id:
        raise ValueError('invalid run ID')
    run = campaign / 'private/runs' / run_id
    if sha256(run / 'manifest.json') != anchor:
        raise ValueError('manifest anchor differs')
    manifest = json.loads((run / 'manifest.json').read_text())
    if manifest['schema_version'] != 'siq-personal-runtime-browser/v1':
        raise ValueError('manifest type differs')
    observation = json.loads((run / 'browser-observations.json').read_text())
    for response in observation.get('browser', {}).get('responses', []):
        if response['path'] in ('/v1/pair', '/v1/session/restore'):
            body = response['body']
            if isinstance(body, dict) and body.get('session') not in (None, '[REDACTED]'):
                raise ValueError('browser session not redacted')
    paths = list((campaign / 'private/credentials').glob('*.key'))
    paths += [p for p in (run / 'state-private').rglob('*') if p.is_file()
              and (p.name == 'token' or p.suffix in ('.token', '.key', '.seed', '.credential'))]
    secrets = set()
    for path in paths:
        value = path.read_bytes().strip()
        if len(value) < 16:
            continue
        secrets.update((value, value.hex().encode(), base64.b64encode(value)))
        try:
            decoded = base64.b64decode(value, validate=True)
            if len(decoded) >= 16:
                secrets.update((decoded, decoded.hex().encode()))
        except ValueError:
            pass
    top = {'protocol.json', 'journal.jsonl', 'summary.json', 'host-after.json', 'score.json',
           'cleanup.json', 'daemon.json', 'browser-observations.json', 'manifest.json'}
    payloads = {}
    for name in [*manifest['artifacts'], 'manifest.json']:
        if name not in top and not re.fullmatch(r'output/playwright/[A-Za-z0-9_-]+\.(txt|yaml|png)', name):
            raise ValueError('artifact not in browser export allowlist')
        path = safe_path(run, name)
        if name in manifest['artifacts'] and sha256(path) != manifest['artifacts'][name]:
            raise ValueError('artifact changed')
        raw = path.read_bytes()
        if any(secret in raw for secret in secrets) or b'PRIVATE KEY-----' in raw:
            raise ValueError('known private material detected')
        payloads[name] = raw
    target = campaign / 'data' / run_id
    target.mkdir(exist_ok=False)
    for name, raw in payloads.items():
        path = safe_path(target, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    result = {'run_id': run_id, 'manifest_sha256': anchor, 'exported_at': utc_now(),
              'files': len(payloads), 'private_value_forms_screened': len(secrets), 'known_private_matches': 0,
              'browser_issued_sessions_redacted': True, 'custody': 'author_local', 'publication': 'local_only',
              'scope': 'explicit text/DOM/screenshot artifacts; browser profiles, hidden raw snapshots and host state excluded'}
    write_json(campaign / 'inventory/anchors' / (run_id + '.json'), result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.campaign.resolve(), args.run_id, args.expected_manifest_sha256)))
