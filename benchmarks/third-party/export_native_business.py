"""Allowlisted local export of native synthetic evidence, excluding host state."""
import argparse
import base64
import json
from pathlib import Path

from common import safe_path, sha256, utc_now, write_json


def export(campaign, run_id, anchor):
    if Path(run_id).name != run_id:
        raise ValueError('invalid run ID')
    run = campaign / 'private/runs' / run_id
    if sha256(run / 'manifest.json') != anchor:
        raise ValueError('manifest anchor differs')
    manifest = json.loads((run / 'manifest.json').read_text())
    if manifest['schema_version'] != 'siq-native-business/v1':
        raise ValueError('unsupported native export')
    paths = list((campaign / 'private/credentials').glob('*.key'))
    paths += [p for p in (run / 'state-private').rglob('*') if p.is_file()
              and (p.name == 'token' or p.suffix in ('.token', '.seed', '.key'))]
    secrets = set()
    for path in paths:
        value = path.read_bytes().strip()
        if len(value) >= 16:
            secrets.update((value, value.hex().encode(), base64.b64encode(value)))
            try:
                decoded = base64.b64decode(value, validate=True)
                if len(decoded) >= 16:
                    secrets.update((decoded, decoded.hex().encode()))
            except ValueError:
                pass
    root_names = {'protocol.json', 'journal.jsonl', 'summary.json', 'host-after.json', 'manifest.json'}
    case_names = {'result.json', 'score.json', 'gold.json', 'events.jsonl', 'resources.json'}
    payloads = {}
    for relative in [*manifest['artifacts'], 'manifest.json']:
        parts = Path(relative).parts
        if relative not in root_names and not (len(parts) == 3 and parts[0] == 'cases' and parts[2] in case_names):
            raise ValueError('non-allowlisted artifact')
        path = safe_path(run, relative)
        if relative in manifest['artifacts'] and sha256(path) != manifest['artifacts'][relative]:
            raise ValueError('artifact differs')
        raw = path.read_bytes()
        if any(secret in raw for secret in secrets) or b'PRIVATE KEY-----' in raw:
            raise ValueError('private material detected; export stopped')
        payloads[relative] = raw
    target = campaign / 'data' / run_id
    target.mkdir(parents=True, exist_ok=False)
    for relative, raw in payloads.items():
        path = safe_path(target, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    result = {'run_id': run_id, 'manifest_sha256': anchor, 'custody': 'author_local',
              'publication': 'local_only', 'exported_at': utc_now(), 'files': len(payloads),
              'private_values_screened': len(secrets), 'known_private_values_found': 0,
              'policy': 'strict manifest allowlist; known provider/runtime/recovery/key screening; unchanged synthetic captures; no host state export'}
    write_json(campaign / 'inventory/anchors' / (run_id + '.json'), result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.campaign, args.run_id, args.expected_manifest_sha256)))
