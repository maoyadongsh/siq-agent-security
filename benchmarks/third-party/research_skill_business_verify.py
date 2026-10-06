"""Independently bind native Skill loading, signed SECs and real file effects."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from research_skill_install_verify import canonical, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--research-root', type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    run = json.loads((campaign / 'reports' / (args.batch + '.json')).read_text())
    base = json.loads((campaign / 'reports' / (args.batch + '-verification.json')).read_text())
    bundle = json.loads((campaign / 'data' / (args.batch + '-verified-receipts.json')).read_text())
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(bundle['public_key'], validate=True))
    proof = run['proof']
    rows, contexts, image = proof['skill_installations'], proof['skill_sync_records'], proof['candidate_image']
    checks = {'base_receipts_and_effects_verified': base['passed'] is True,
              'live_run_passed': run['passed'] is True,
              'two_loaded_skills': len(rows) == len(contexts) == 2,
              'distinct_skills': len({r['name'] for r in rows}) == 2}
    state = campaign / 'private/runs' / args.batch / 'authority-state'
    grants = []
    decisions = [r for r in bundle['receipts'] if r.get('record_type') == 'decision']
    for row, record in zip(rows, contexts, strict=True):
        context, request = record['context'], record['request']
        verify(key, context)
        matches = []
        for path in (state / 'grants').glob('*.json'):
            grant = json.loads(path.read_text())
            normalized = json.loads(path.read_text(), parse_int=float)
            if (grant['grant_id'] == context['authority']['grant_id'] and
                hashlib.sha256(canonical(normalized)).hexdigest() == context['authority']['grant_digest']):
                verify(key, grant)
                matches.append(grant)
        if not matches or any(g != matches[0] for g in matches):
            raise ValueError('no unique signed authority matches Skill context')
        grants.append(matches[0])
        name = row['name']
        expected_source = campaign / 'private/runs' / args.batch / 'skill-business-fixtures' / name / 'SKILL.md'
        if Path(row['source_path']) / 'SKILL.md' != expected_source or expected_source.resolve() != expected_source:
            raise ValueError('unexpected Skill source path')
        digest = hashlib.sha256(expected_source.read_bytes()).hexdigest()
        checks[name + '_exact_installed_source_image_and_loaded_hash'] = (
            digest == row['skill_file_sha256'] == request['skill_file_sha256']
            == image['evaluation_skill_bundle']['skills'][name]['sha256'])
        checks[name + '_context_matches_install_and_grant'] = (
            context['install']['install_id'] == row['install_id'] and context['authority']['grant_id'] == row['grant_id']
            and context['skill'] == matches[0]['skill'] and context['evidence_level'] == 'controlled_task'
            and context['subject']['task_id'] == request['task_id']
            and context['subject']['session_id'] == request['session_id'])
        calls = [r for r in decisions if r.get('matched_grant_id') == row['grant_id']]
        checks[name + '_every_decision_has_verified_skill_context'] = len(calls) == 2 and all(
            r.get('skill_attribution', {}).get('context_id') == context['context_id']
            and r.get('skill_attribution', {}).get('skill_id') == context['skill']['skill_id']
            and r.get('skill_attribution', {}).get('content_hash') == context['skill']['content_hash']
            and r.get('skill_attribution', {}).get('status') == 'verified'
            and r.get('agent_id') == context['subject']['agent_id']
            and r.get('session_id') == context['subject']['session_id']
            and r.get('runtime_task_id') == context['subject']['task_id'] for r in calls)
        code = ('import hashlib,json,sys; from tools.skills_tool import skill_view; '
                'd=json.loads(skill_view(name=sys.argv[1],preprocess=False)); '
                'print(json.dumps({"success":d.get("success"),'
                '"content_sha256":hashlib.sha256(d.get("content","").encode()).hexdigest()}))')
        loaded = subprocess.run(['docker', 'run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m',
            '--env', 'HERMES_HOME=' + str(args.research_root / 'data/hermes/home/profiles/siq_analysis'),
            '--entrypoint', '/opt/siq/hermes/venv/bin/python', image['image_id'], '-c', code, name],
            capture_output=True, text=True, timeout=45, check=True)
        value = json.loads(loaded.stdout)
        checks[name + '_native_loader_independent_reproduction'] = value.get('success') is True and (
            value['content_sha256'] == request['loaded_content_sha256'])
    result = {'schema_version': 'siq.evaluation.research-skill-business-review.v1',
        'batch': args.batch, 'passed': all(checks.values()), 'checks': checks,
        'claim_scope': 'two installed Skills, sequential trusted task selection, real analysis API/Hermes/OpenShell',
        'limits': ['evaluation-only host SEC synchronizer', 'not automatic arbitrary Skill switching',
                   'not daily deployment promotion', 'not concurrent root identities']}
    authority = {'public_key': bundle['public_key'], 'contexts': [r['context'] for r in contexts],
                 'grants': grants, 'image_id': image['image_id']}
    for directory, suffix, value in [('data', '-skill-authority', authority), ('reports', '-skill-verification', result)]:
        with (campaign / directory / (args.batch + suffix + '.json')).open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
