"""Freeze one-candidate native discovery to real governed backend effects."""
import argparse
import json
from pathlib import Path

import governance_trial as base
from common import sha256, utc_now, write_json
from enterprise_native_edge import ASSERTIONS, CASES
from enterprise_runtime import ASSERTIONS as EFFECT_ASSERTIONS


def freeze(campaign, protocol_id):
    candidate = campaign / 'private/candidates/5470ab3780f2-governancefix1'
    base.freeze(campaign, protocol_id, include_backend=True, candidate_root=candidate)
    path = campaign / 'protocols' / protocol_id / 'protocol.json'
    p = json.loads(path.read_text())
    p.update(native_enterprise_assertions=ASSERTIONS, native_build=json.loads((campaign / 'inventory/enterprise-native-build-001.json').read_text()))
    p['expected_status'].update(CASES)
    p['backend_assertions'] += EFFECT_ASSERTIONS
    p['scope'] = 'one candidate API + native Edge/Hermes discovery + operator target authority + approval + actual OpenShell policy enforcement/readback/rollback; synthetic protocol negatives retained separately'
    p['limits'] = ['ephemeral RS256 test issuer, not enterprise customer IdP', 'native CLI registration, not publisher-signed installer or periodic discovery service', 'one owned target and receiver; no shared-target/Windows/general model claim', 'controlled network task, not natural model attack or independent third-party witness']
    p['frozen_at'] = utc_now()
    registration = campaign / 'plan' / (protocol_id.removesuffix('-protocol') + '.md')
    p['registration'] = {'path': str(registration), 'sha256': sha256(registration)}
    for folder in ('edge/agent', 'connectors/hermes'):
        for file in (candidate / folder).rglob('*'):
            if file.is_file() and (file.suffix == '.go' or file.name in ('go.mod', 'go.sum')):
                p['candidate_sources'][str(file.relative_to(candidate))] = sha256(file)
    for name in ('enterprise_chain_trial.py', 'enterprise_native_edge.py', 'enterprise_runtime.py', 'verify_governance.py'):
        (path.parent / 'harness-source' / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    p['harness_sources'] = {str(f.relative_to(path.parent / 'harness-source')): sha256(f) for f in (path.parent / 'harness-source').rglob('*') if f.is_file()}
    write_json(path, p, exclusive=False)
    write_json(path.parent / 'local-anchor.json', {'sha256': sha256(path)}, exclusive=False)
    print(json.dumps({'protocol': str(path), 'HTTP_allocation': len(p['expected_status']), 'native_assertions': len(ASSERTIONS), 'effect_assertions': len(EFFECT_ASSERTIONS)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--protocol-id', required=True)
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.action == 'freeze':
        freeze(args.campaign.resolve(), args.protocol_id)
    else:
        raise SystemExit(base.run(args.campaign.resolve(), args.protocol_id, args.run_id))
