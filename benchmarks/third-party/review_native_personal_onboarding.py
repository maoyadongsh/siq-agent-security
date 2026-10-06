"""Tamper checks for cross-stage identity and signed ownership joins."""
import argparse
import base64
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from common import sha256
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from personal_onboarding_authority import canonical, digest, require
from verify_native_personal_onboarding import verify


def verify_intent(raw):
    decisions = [r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision']
    first = decisions[0]
    intents = [i for row in raw['management_http'] if row['route'] == '/v1/intents' for i in row['response']['items'] if i['intent_id'] == first['intent_id']]
    bindings = [i for row in raw['management_http'] if row['route'] == '/v1/intent-bindings' for i in row['response']['items'] if i['intent_id'] == first['intent_id']]
    require(len(intents) == len(bindings) == 1, 'unique actual Intent and binding required')
    intent, binding = intents[0], bindings[0]
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['receipts']['public_key'], validate=True))
    for document in (intent, binding):
        key.verify(bytes.fromhex(document['signature']), canonical({k: v for k, v in document.items() if k != 'signature'}))
    calculated = digest({k: v for k, v in intent.items() if k not in ('signature', 'digest')})
    require(calculated == intent['digest'] == binding['intent_digest'], 'Intent digest differs')
    granted = next(r['response']['grant'] for r in raw['management_http'] if r['route'].endswith('/approve'))
    require(binding['grant_ref']['grant_id'] == granted['grant_id'] and set(intent['allowed_tools']) == {'read_file', 'write_file'}, 'Intent permissions differ from installed grant')
    for decision in decisions:
        require(decision['intent_digest'] == calculated and all(binding[k] == decision[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'intent_id')), 'signed call belongs to a different Intent binding')
    require(raw['bootstrap']['subjects'] == [[first['session_id'], first['runtime_task_id']]] and not raw['bootstrap']['failures'], 'native bootstrap identity differs')
    return {'signed_documents_verified': 2, 'schema_version': intent['schema_version'], 'intent_id': intent['intent_id'], 'calls_bound': len(decisions)}


def verify_complete(run, anchor):
    result = verify(run, anchor)
    raw = json.loads((run / 'cases/personal-onboarding-B2/result.json').read_text())
    result['supplementary_intent_binding'] = verify_intent(raw)
    return result


def review(run, scratch):
    baseline = verify_complete(run, sha256(run / 'manifest.json'))
    probes = []
    for mutation in ('discovered-source-swap', 'permission-source-swap', 'owner-from-other-install', 'SEC-from-other-grant', 'coherent-payload-swap', 'discovery-authority-promotion', 'Intent-binding-grant-swap'):
        with tempfile.TemporaryDirectory(prefix='personal-onboarding-negative-', dir=scratch) as temp:
            target = Path(temp)
            manifest = json.loads((run / 'manifest.json').read_text())
            for name in [*manifest['artifacts'], 'manifest.json']:
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(run / name, dest)
            path = target / 'cases/personal-onboarding-B2/result.json'
            raw = json.loads(path.read_text())
            obs = raw['onboarding_observation']
            if mutation == 'discovered-source-swap':
                obs['selected_assets']['normal']['source_locator'] = obs['selected_assets']['quarantined']['source_locator']
            elif mutation == 'permission-source-swap':
                next(r for r in raw['management_http'] if r['route'].endswith('/permissions') and 'source' in r['response'])['response']['source']['import_id'] = obs['stages']['bad_import']['import']['import_id']
            elif mutation == 'owner-from-other-install':
                owner = obs['owner_records']['.siq-install-owner']
                owner['document']['install_id'] = 'sin-' + '0' * 64
                owner['raw'] = json.dumps(owner['document'])
                obs['installed_snapshot']['.siq-install-owner']['sha256'] = hashlib.sha256(owner['raw'].encode()).hexdigest()
                obs['installed_snapshot']['.siq-install-owner']['bytes'] = len(owner['raw'].encode())
            elif mutation == 'SEC-from-other-grant':
                next(r for r in raw['management_http'] if r['route'] == '/v1/skill-contexts')['response']['authority']['grant_id'] = 'grt-other'
            elif mutation == 'coherent-payload-swap':
                for mapping in (obs['sources_before']['normal'], obs['sources_after']['normal'], obs['installed_snapshot']):
                    mapping['scripts/probe.sh']['sha256'] = '0' * 64
            elif mutation == 'discovery-authority-promotion':
                asset = obs['selected_assets']['normal']
                asset['status'] = 'approved'
                next(a for a in obs['stages']['discovery']['assets']['assets'] if a['id'] == asset['id'])['status'] = 'approved'
            else:
                next(item for row in raw['management_http'] if row['route'] == '/v1/intent-bindings' for item in row['response']['items'])['grant_ref']['grant_id'] = 'grt-other'
            path.write_text(json.dumps(raw) + '\n')
            event_path = target / 'cases/personal-onboarding-B2/events.jsonl'
            events = [json.loads(line) for line in event_path.read_text().splitlines()]
            for event in events:
                if event['event'] == 'onboarding_observed':
                    event['record'] = obs
            # Original signed records remain authoritative even if unsigned
            # observer duplicates and envelope hashes are rewritten together.
            event_path.write_text(''.join(json.dumps(e) + '\n' for e in events))
            manifest['artifacts'] = {name: sha256(target / name) for name in manifest['artifacts']}
            (target / 'manifest.json').write_text(json.dumps(manifest) + '\n')
            try:
                verify_complete(target, sha256(target / 'manifest.json'))
            except (ValueError, InvalidSignature) as error:
                probes.append({'mutation': mutation, 'rejected': True, 'error_type': type(error).__name__})
            else:
                probes.append({'mutation': mutation, 'rejected': False})
    return {'baseline': baseline, 'negative_probes': probes, 'passed': all(p['rejected'] for p in probes),
            'scope': 'offline tampered copies, not extra business trials or independent executor proof'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    result = review(args.run, args.scratch)
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)
