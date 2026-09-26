#!/usr/bin/env python3
"""Native skill protocol and Python schema parity, using only synthetic files."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connector', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit('refusing to overwrite evidence')
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'LANG', 'LC_ALL', 'TZ'}}
    with tempfile.TemporaryDirectory(prefix='siq-skill-collection-') as raw:
        root = Path(raw)
        for name, data in [('one', '---\nname: same-name\nallowed-tools: read_file\n---\n'),
                           ('two', '---\nname: same-name\nallowed-tools: [$(execute)]\n---\n')]:
            path = root / name
            path.mkdir()
            (path / 'SKILL.md').write_text(data)
            (path / '.env').write_text('FIXTURE_SECRET=must-not-be-read\n')
        env['HOME'] = str(root)
        request = {'id': 'fixture', 'op': 'collect_skills', 'params': {'plan': {
            'scope': {'roots': [str(root)], 'include': ['SKILL.md']},
            'limits': {'max_files': 200, 'max_bytes': 1048576},
        }}}
        run = subprocess.run([str(args.connector.resolve()), '--serve'], input=json.dumps(request) + '\n',
                             text=True, capture_output=True, env=env, timeout=20, check=True)
        response = json.loads(run.stdout)
        assert response['ok'] is True
        result = response['result']
        assert len(result['observations']) == 2 and result['truncated'] is False
        assert {o['parse_status'] for o in result['observations']} == {'parsed', 'unsupported'}
        assert str(root) not in run.stdout and 'FIXTURE_SECRET' not in run.stdout and 'execute' not in run.stdout
        env.update(SIQ_AS_DEV='1', SIQ_AS_ALLOW_SQLITE='1')
        validation = subprocess.run([str(ROOT / 'apps/control-api/.venv/bin/python'), '-c',
            'import json,sys; from app.skill_upload import SkillObservationIn; '
            'items=json.load(sys.stdin); [SkillObservationIn.model_validate(item) for item in items]; '
            'print(len(items))'],
            input=json.dumps(result['observations']), text=True, capture_output=True, env=env,
            cwd=ROOT / 'apps/control-api', timeout=20, check=True)
        assert validation.stdout.strip() == '2'
    evidence = {'passed': True, 'scope': 'native NDJSON and Python schema, synthetic files only',
                'observations_validated': 2, 'raw_content_absent': True, 'production_uploaded': False,
                'connector_sha256': hashlib.sha256(args.connector.read_bytes()).hexdigest()}
    args.out.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
