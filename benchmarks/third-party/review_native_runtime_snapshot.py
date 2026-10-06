"""Cross-bind snapshot checks to the installed business identity; reject tampering."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from native_runtime_snapshot import checks
from personal_onboarding_authority import require, verify_authority
from verify_native_runtime_snapshot import joins, verify


def strict_scope(raw, p, evidence):
    result = joins(raw, p, evidence)
    actual = verify_authority(raw)
    obs = raw['runtime_check_observation']
    for stage in ('identity_before', 'identity_after', 'identity_restored'):
        require(obs[stage]['identity_id'] == actual['runtime_identity_id'], 'snapshot uses another business identity')
        require(obs[stage]['grant_ref']['grant_id'] == actual['grant_id'], 'snapshot uses another business Grant')
        require(obs[stage]['instance_id'] == obs['instance_id'], 'snapshot uses another installed instance')
    require(obs['grant_before']['grant']['grant_id'] == obs['grant_after']['grant']['grant_id'] == actual['grant_id'], 'snapshot Grant readbacks differ')
    for stage in ('baseline', 'fresh'):
        own = obs[stage]['variants']['recovery']
        record = next(r for r in own['records'].values() if r['result'] == own['terminal'])
        binding = next(b for b in own['bindings']['items'] if b['binding_id'] == record['binding_id'])
        require(record['grant_id'] != actual['grant_id'] and binding['grant_ref']['grant_id'] == record['grant_id'] and binding['intent_id'] == record['intent_id'] and binding['intent_digest'] == record['intent_digest'], 'selfcheck borrowed business grant or binding')
    variant = p['snapshot_variant']
    if variant in ('business-grant', 'business-identity'):
        route = '/v1/grants/' + actual['grant_id'] + '/revoke' if variant == 'business-grant' else '/v1/runtime-identities/' + actual['runtime_identity_id'] + '/revoke'
        requests = [r for r in raw['management_http'] if r['route'] == route and r.get('request')]
        require(len(requests) == 1 and requests[0]['response'] == obs['mutation']['response'], 'mutation not bound to actual management request')
    require(all(checks(obs, variant).values()), 'snapshot scope assertions differ')
    return result


def review(run, anchor):
    original = verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    source = Path(p['candidate_root']) / 'benchmarks/runtime-security/evidence.py'
    spec = importlib.util.spec_from_file_location('snapshot_review_evidence', source)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    raw = json.loads((run / 'cases/personal-onboarding-B2/result.json').read_text())
    joined = strict_scope(raw, p, evidence)
    probes = []
    mutations = ['revision-signature', 'foreign-instance', 'borrowed-business-identity', 'borrowed-business-grant',
                 'reuse-old-check', 'chain-prefix-truncation', 'wrong-variant']
    if p['snapshot_variant'] == 'plugin-entry':
        mutations += ['revive-old-pass', 'no-file-change']
    if p['snapshot_variant'] == 'business-grant':
        mutations += ['hide-authority-failure', 'different-revocation-response']
    for mutation in mutations:
        changed = copy.deepcopy(raw)
        obs = changed['runtime_check_observation']
        if mutation == 'revision-signature':
            next(iter(obs['records_final'].values()))['actor_id'] = 'different-operator'
        elif mutation == 'foreign-instance':
            obs['instance_id'] = 'hi-' + '0' * 32
        elif mutation == 'borrowed-business-identity':
            obs['identity_restored']['identity_id'] = 'ri-' + '0' * 32
        elif mutation == 'borrowed-business-grant':
            obs['identity_restored']['grant_ref']['grant_id'] = 'grt-other'
        elif mutation == 'reuse-old-check':
            obs['fresh'] = copy.deepcopy(obs['baseline'])
        elif mutation == 'chain-prefix-truncation':
            obs['receipts_final']['receipts'].pop(0)
        elif mutation == 'wrong-variant':
            obs['variant'] = 'different-variant'
        elif mutation == 'revive-old-pass':
            obs['old_after_fresh'] = copy.deepcopy(obs['baseline']['variants']['recovery']['terminal'])
        elif mutation == 'no-file-change':
            obs['mutation']['changed_sha256'] = obs['mutation']['before_sha256']
        elif mutation == 'hide-authority-failure':
            target = next(r for r in obs['changed_instances']['instances'] if r['instance_id'] == obs['instance_id'])
            next(c for c in target['diagnosis']['checks'] if c['code'] == 'instance_authority')['status'] = 'pass'
        else:
            obs['mutation']['response'] = {'revoked': False}
        try:
            strict_scope(changed, p, evidence)
        except (ValueError, InvalidSignature) as error:
            probes.append({'mutation': mutation, 'rejected': True, 'error_type': type(error).__name__})
        else:
            raise ValueError('snapshot evidence mutation accepted: ' + mutation)
    return {'original_verification': original, 'cross_scope_join': joined, 'negative_probes': probes,
            'passed': True, 'scope': 'offline copies only; no new product execution or natural attacks'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
