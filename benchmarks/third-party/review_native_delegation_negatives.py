"""Reanchored evidence tampering probes; never execute a native host or model."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from common import sha256
from cryptography.exceptions import InvalidSignature
from review_native_delegation_authority import review


def check(campaign, run_id):
    run = campaign / 'private/runs' / run_id
    baseline = review(run, sha256(run / 'manifest.json'))
    rows = []
    for mutation in ('decision-reason', 'grant-permission', 'intent-permission', 'binding-task',
                     'child-lineage', 'child-file', 'read-calibration'):
        with tempfile.TemporaryDirectory(prefix='delegation-negative-', dir=campaign / 'private') as temporary:
            target = Path(temporary)
            manifest = json.loads((run / 'manifest.json').read_text())
            for name in manifest['artifacts']:
                dst = target / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(run / name, dst)
            case = 'delegate_public-B2' if mutation in ('decision-reason', 'grant-permission', 'intent-permission', 'binding-task') else 'delegate_public-B0'
            path = target / 'cases' / case / 'result.json'
            raw = json.loads(path.read_text())
            if mutation == 'decision-reason':
                next(r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision')['reason_code'] = 'changed'
            elif mutation == 'grant-permission':
                grant = next(r['response']['grant'] for r in raw['management_http'] if r['route'].endswith('/approve'))
                grant['facts'] = [r for r in grant['facts'] if r['resource']['value'] != 'delegate_task']
            elif mutation == 'intent-permission':
                intent = next(i for r in raw['management_http'] if r['route'] == '/v1/intents' for i in r['response']['items'])
                intent['allowed_tools'] = [tool for tool in intent['allowed_tools'] if tool != 'delegate_task']
            elif mutation == 'binding-task':
                binding = next(i for r in raw['management_http'] if r['route'] == '/v1/intent-bindings' for i in r['response']['items'])
                binding['task_id'] = 'wrong-parent-task'
            elif mutation == 'child-lineage':
                next(r for r in raw['delegation_observation']['hooks'] if r['event'] == 'subagent_stop')['child_session_id'] = 'foreign-child'
            elif mutation == 'child-file':
                raw['delegation_observation']['content'] = 'file supplied by a different task'
            else:
                raw['delegation_observation']['calibration'][1]['observation']['events'] = []
            path.write_text(json.dumps(raw) + '\n')
            manifest['artifacts'] = {name: sha256(target / name) for name in manifest['artifacts']}
            (target / 'manifest.json').write_text(json.dumps(manifest) + '\n')
            try:
                review(target, sha256(target / 'manifest.json'))
            except (ValueError, InvalidSignature) as error:
                rows.append({'mutation': mutation, 'rejected': True, 'error_type': type(error).__name__})
            else:
                rows.append({'mutation': mutation, 'rejected': False})
    return {'run_id': run_id, 'manifest_sha256': sha256(run / 'manifest.json'),
            'original_exit_code': baseline['original_summary']['outcome_exit_code'],
            'negative_controls': rows, 'passed': all(row['rejected'] for row in rows),
            'scope': 'copies with recomputed outer hashes; no new native/model execution'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    result = check(args.campaign.resolve(), args.run_id)
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)
