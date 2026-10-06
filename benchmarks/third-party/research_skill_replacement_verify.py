"""Independently check public update authority and actual new-version effects."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from research_cross_company_verify import resource_ref
from research_permissions_verify import verify_receipt_bundles
from research_skill_install_verify import canonical, verify

OUTPUT = b'AUTHORIZED_UPDATED_READER'
INSTALL_SCHEMAS = {
    'local-skill-install-operation/v1', 'local-skill-update-plan/v1',
    'local-skill-update-claim/v1', 'local-skill-update-result/v1',
    'local-skill-install-plan/v1', 'local-skill-install-removal-result/v1',
}


def signed(key, document):
    if document.get('schema_version') in INSTALL_SCHEMAS:
        if 'signing_schema' in document:
            raise ValueError('unexpected installation signature encoding')
        key.verify(bytes.fromhex(document['signature']), canonical(
            {k: v for k, v in document.items() if k != 'signature'}))
    else:
        verify(key, document)


def native_checks(records, context, *, input_path, output_path, output_bytes):
    decisions = [r for r in records if r.get('record_type') == 'decision']
    observations = [r for r in records if r.get('record_type') == 'observation']
    checks = {'two_native_decisions_and_observations': len(decisions) == len(observations) == 2,
        'exact_output_bytes': output_bytes == OUTPUT,
        'all_current_skill_attribution': bool(decisions) and all(
            r.get('matched_grant_id') == context['authority']['grant_id']
            and r.get('agent_id') == context['subject']['agent_id']
            and r.get('session_id') == context['subject']['session_id']
            and r.get('runtime_task_id') == context['subject']['task_id']
            and (r.get('skill_attribution') or {}).get('context_id') == context['context_id']
            and (r.get('skill_attribution') or {}).get('content_hash') == context['skill']['content_hash']
            and (r.get('skill_attribution') or {}).get('status') == 'verified' for r in decisions)}
    for tool, path in [('read_file', input_path), ('write_file', output_path)]:
        selected = [r for r in decisions if r.get('tool') == tool]
        checks[tool + '_exact_target_allowed'] = len(selected) == 1 and (
            selected[0].get('action') == selected[0].get('effective_action') == 'allow'
            and selected[0].get('resource_refs') == resource_ref(path))
        obs = [r for r in observations if len(selected) == 1
            and r.get('decision_receipt_id') == selected[0]['receipt_id']]
        checks[tool + '_linked_observation'] = len(obs) == 1 and all(
            obs[0].get(k) == selected[0].get(k) for k in (
                'action_id', 'tool_call_id', 'session_id', 'runtime_task_id', 'resource_refs', 'matched_grant_id'))
        if tool == 'write_file':
            checks['write_exact_parameters'] = len(selected) == 1 and selected[0].get('params_digest') == hashlib.sha256(
                canonical({'path': str(output_path), 'content': OUTPUT.decode()})).hexdigest()
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign', 'binary', 'research-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--batch', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'research-permissions-skill-replacement-[0-9]{3}', args.batch):
        raise ValueError('invalid batch')
    c = args.campaign.resolve(); private = c / 'private/runs' / args.batch
    run = json.loads((c / 'reports' / (args.batch + '.json')).read_text()); proof = run['proof']
    if run['batch'] != args.batch or hashlib.sha256(args.binary.read_bytes()).hexdigest() != run['binary_sha256']:
        raise ValueError('binary or batch mismatch')
    state = private / 'authority-state'
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'LANG') if k in os.environ}
    env['SIQ_AGENT_SECURITY_STATE_DIR'] = str(state)
    public = subprocess.run([str(args.binary), 'pubkey'], env=env, capture_output=True, text=True,
                            timeout=15, check=True).stdout.strip()
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True))
    records = [json.loads(line) for p in (state / 'receipts').glob('*/*.jsonl')
               for line in p.read_text().splitlines() if line]
    records.sort(key=lambda r: (r['chain_id'], r['seq']))
    bundle = {'fixture': args.batch, 'public_key': public, 'binary_sha256': run['binary_sha256'], 'receipts': records}
    verify_receipt_bundles([bundle])
    e = proof['skill_update_evidence']; update = e['committed_update']
    original = e['unapproved_comparison']['previous_grant']; current = e['current_grant']['grant']
    contexts = [e['old_context'], proof['replacement_positive']['context']]
    docs = {'original_grant': original, 'revoked_grant': e['old_grant_after_commit']['grant'],
        'approved_grant': e['candidate_approved']['grant'], 'current_grant': current,
        'update_plan': e['approved_update_plan'], 'update_claim': update['claim'],
        'update_result': update['result'], 'replacement_operation': update['installation'],
        'old_context': contexts[0], 'current_context': contexts[1]}
    for value in docs.values():
        signed(key, value)
    old_context, context = contexts
    target = Path(proof['replacement_positive']['output_path'])
    companies = args.research_root.resolve() / 'data/wiki/companies'
    rel = target.relative_to(companies)
    if (target.resolve() != target or len(rel.parts) != 5 or rel.parts[1:3] != ('analysis', 'runs')
        or not re.fullmatch(r'600000-SyntheticApi[a-f0-9]{16}', rel.parts[0])
        or not re.fullmatch(r'qwen-request-[a-f0-9]{16}', rel.parts[3]) or rel.parts[4] != 'permission-result.md'):
        raise ValueError('unowned output target')
    raw = target.read_bytes() if target.is_file() else None
    checks = native_checks(records, context, input_path=companies / rel.parts[0] / 'synthetic.txt',
                            output_path=target, output_bytes=raw)
    checks.update({
        'public_update_completed': update['status'] == 'updated_unverified'
            and update['removal']['status'] == 'removed' and update['installation']['status'] == 'installed_unverified',
        'install_claim_does_not_invent_runtime_proof': update['result']['runtime_verified'] is False,
        'old_grant_revoked_and_old_identity_unavailable': docs['revoked_grant']['grant_id'] == original['grant_id']
            and docs['revoked_grant']['status'] == 'revoked'
            and e['old_identity_after_commit']['identity_id'] == e['old_identity_id']
            and e['old_identity_after_commit']['status'] == 'grant_unavailable',
        'old_session_was_enrolled_before_update': e['old_session_positive_before_update']['session_id'] == old_context['subject']['session_id']
            and e['old_session_positive_before_update']['identity_id'] == e['old_identity_id'],
        'new_installation_and_content_distinct': context['install']['install_id'] == update['installation']['install_id']
            and context['install']['install_id'] != old_context['install']['install_id']
            and context['skill']['content_hash'] == current['skill']['content_hash'] != original['skill']['content_hash'],
        'same_agent_and_skill_name': context['subject']['agent_id'] == old_context['subject']['agent_id']
            and proof['skill_sync_records'][0]['request']['skill_name'] == 'research-permissions-reader',
        'new_context_current_grant_digest': context['authority']['grant_id'] == current['grant_id'] != original['grant_id']
            and context['authority']['grant_digest'] == hashlib.sha256(canonical(
                json.loads(json.dumps(current), parse_int=float))).hexdigest(),
        'current_narrow_write_scope': [f['resource']['value'] for f in current['facts']
            if f['action'] == 'fs.write' and f['effect'] == 'allow'] == [str(target.parent.parent)],
        'original_no_write_authority': not any(f['action'] == 'fs.write' and f['effect'] == 'allow' for f in original['facts']),
        'stale_authentication_probes_not_tool_receipts': e['stale_probes_no_receipts'] is True
            and len(records) == 4 and all(r['session_id'] != old_context['subject']['session_id'] for r in records),
        'management_stale_target_absent': not (private / 'skill-business-fixtures/stale-write.txt').exists(),
        'new_identity_fresh_session_works': e['new_identity_fresh_session']['identity_id'] == e['new_identity_id']
            and e['new_identity_id'] != e['old_identity_id'],
    })
    expected = {
        'stale_decision': (401, {'scoped_decision_credential_required'}),
        'old_credential_enroll': (401, {'runtime_identity_required'}),
        'new_identity_old_session': (409, {'runtime_identity_authority_conflict'}),
        'old_install_context': (409, {'skill_context_install_changed', 'skill_context_grant_changed'}),
        'new_install_old_session_context': (409, {'skill_context_session_unbound'}),
    }
    for label, (status, reasons) in expected.items():
        checks[label + '_exact_rejection'] = e[label]['HTTP_status'] == status and e[label]['reason'] in reasons
    checks['replays_target_actual_old_session'] = all(e[k]['request']['session_id'] == old_context['subject']['session_id']
        for k in ('stale_decision', 'old_credential_enroll', 'new_identity_old_session', 'new_install_old_session_context'))
    checks['old_install_context_targets_removed_installation'] = e['old_install_context']['request']['install_id'] == old_context['install']['install_id']
    new_source = private / 'skill-business-fixtures/reader-update-source/SKILL.md'
    old_source = private / 'skill-business-fixtures/research-permissions-reader/SKILL.md'
    checks['runtime_loaded_actual_updated_source'] = hashlib.sha256(new_source.read_bytes()).hexdigest() == e['candidate_skill_sha256'] == (
        proof['skill_sync_records'][0]['request']['skill_file_sha256']) == proof['candidate_image']['evaluation_skill_bundle']['skills']['research-permissions-reader']['sha256']
    checks['preserved_distinct_original_bytes'] = hashlib.sha256(old_source.read_bytes()).hexdigest() == e['original_skill_sha256'] != e['candidate_skill_sha256']
    checks['different_immutable_images'] = proof['candidate_image']['image_id'] != e['original_image']['image_id']
    bad = copy.deepcopy(bundle); bad['receipts'][0]['action'] = 'deny'
    try:
        verify_receipt_bundles([bad])
    except (ValueError, InvalidSignature):
        checks['receipt_tamper_rejected'] = True
    else:
        checks['receipt_tamper_rejected'] = False
    for label, value in docs.items():
        bad = copy.deepcopy(value); bad['signature'] = '0' * 128
        try:
            signed(key, bad)
        except (ValueError, InvalidSignature):
            checks[label + '_tamper_rejected'] = True
        else:
            checks[label + '_tamper_rejected'] = False
    checks['missing_effect_rejected'] = not native_checks(records, context,
        input_path=companies / rel.parts[0] / 'synthetic.txt', output_path=target, output_bytes=None)['exact_output_bytes']
    bad_context = copy.deepcopy(context); bad_context['authority']['grant_id'] = original['grant_id']
    checks['old_authority_substitution_rejected'] = not native_checks(records, bad_context,
        input_path=companies / rel.parts[0] / 'synthetic.txt', output_path=target, output_bytes=raw)['all_current_skill_attribution']
    protocol_path = c / 'protocols' / (args.batch + '.json'); protocol = json.loads(protocol_path.read_text())
    checks['frozen_protocol_matches_run'] = hashlib.sha256(protocol_path.read_bytes()).hexdigest() == run['pre_run_protocol_sha256']
    checks['expected_image_matches'] = proof['candidate_image']['image_id'] == protocol['expected_image_id']
    checks['live_business_and_cleanup_passed'] = run['passed'] is True and proof['business_HTTP_attempted'] is True
    result = {'schema_version': 'siq.research-skill-replacement-review.v1', 'batch': args.batch,
        'passed': all(checks.values()), 'checks': checks, 'signed_record_count': len(records),
        'limits': ['Old credential/session/context probes are explicit management API probes, not native model calls.',
                  'One actual native business task exercises the activated new version; prior old-version utility is a separate batch.',
                  'Dedicated deployment, controlled Skill selection and evaluation SEC synchronization; daily entry remains separate.']}
    for directory, suffix, value in [('reports', '-verification', result), ('data', '-verified-receipts', bundle),
        ('data', '-skill-authority', {'public_key': public, **docs})]:
        with (c / directory / (args.batch + suffix + '.json')).open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
