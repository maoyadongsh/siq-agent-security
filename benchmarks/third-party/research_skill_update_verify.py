"""Verify candidate approval cannot replace the installed native Skill authority."""
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


def phase_checks(receipts, context, *, input_path, output_path, output_exists):
    decisions = [r for r in receipts if r.get('record_type') == 'decision']
    read = [r for r in decisions if r.get('tool') == 'read_file' and r.get('resource_refs') == resource_ref(input_path)]
    write = [r for r in decisions if r.get('tool') == 'write_file' and r.get('resource_refs') == resource_ref(output_path)]
    observations = [r for r in receipts if r.get('record_type') == 'observation'
        and len(read) == 1 and r.get('decision_receipt_id') == read[0]['receipt_id']]
    return {'two_actual_decisions': len(decisions) == 2,
        'native_read_allow': len(read) == 1 and read[0].get('action') == read[0].get('effective_action') == 'allow',
        'native_write_scope_deny': len(write) == 1 and write[0].get('action') == write[0].get('effective_action') == 'deny'
            and write[0].get('reason_code') == 'grant_scope_violation',
        'write_proposal_matches_target_and_content': len(write) == 1 and write[0].get('params_digest') == hashlib.sha256(
            canonical({'path': str(output_path), 'content': 'CANDIDATE_WRITE_ATTEMPT'})).hexdigest(),
        'read_observation_linked': len(observations) == 1 and all(observations[0].get(k) == read[0].get(k)
            for k in ('action_id', 'tool_call_id', 'session_id', 'runtime_task_id', 'resource_refs')),
        'actual_output_absent': not output_exists,
        'same_installed_authority': all(r.get('matched_grant_id') == context['authority']['grant_id']
            and r.get('agent_id') == context['subject']['agent_id'] and r.get('session_id') == context['subject']['session_id']
            and r.get('runtime_task_id') == context['subject']['task_id']
            and (r.get('skill_attribution') or {}).get('context_id') == context['context_id']
            and (r.get('skill_attribution') or {}).get('status') == 'verified' for r in decisions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign', 'binary', 'research-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--batch', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'research-permissions-skill-update-[0-9]{3}', args.batch):
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
    e = proof['skill_update_evidence']; old = e['unapproved_comparison']['previous_grant']
    unsigned = e['candidate_unapproved']['grant']; approved = e['candidate_approved']['grant']
    documents = {'original_grant': old, 'unapproved_candidate': unsigned, 'approved_candidate': approved,
        'approved_update_plan': e['approved_update_plan'], 'original_install_operation': e['old_installation']['operation']}
    for value in documents.values():
        verify(key, value)
    contexts = [s['context'] for s in proof['skill_sync_records']]
    for context in contexts:
        verify(key, context)
    checks = {'six_signed_records': len(records) == 6, 'two_native_contexts': len(contexts) == 2,
        'candidate_requires_separate_approval': unsigned['status'] not in {'approved', 'deployed'} and approved['status'] == 'approved',
        'candidate_identity_stable_and_distinct_from_original': unsigned['grant_id'] == approved['grant_id'] != old['grant_id'],
        'candidate_content_differs': unsigned['skill']['content_hash'] == approved['skill']['content_hash'] != old['skill']['content_hash'],
        'unapproved_install_and_update_denied': all(e[k]['HTTP_status'] == 409 and e[k]['error'] == 'skill_install_changed'
            for k in ('unapproved_install', 'unapproved_update')),
        'update_preparation_is_not_installation': e['approved_update_plan'].get('platform_changes') is False
            and e['approved_update_plan'].get('runtime_verified') is False
            and e['approved_update_plan'].get('requires_confirmation') is True,
        'same_installed_skill_two_new_tasks': len(contexts) == 2 and contexts[0]['install'] == contexts[1]['install']
            and contexts[0]['subject']['agent_id'] == contexts[1]['subject']['agent_id']
            and contexts[0]['subject']['session_id'] != contexts[1]['subject']['session_id']}
    checks['both_contexts_bind_original_signed_grant_digest'] = all(
        context['authority']['grant_digest'] == hashlib.sha256(canonical(
            json.loads(json.dumps(old), parse_int=float))).hexdigest() for context in contexts)
    checks['both_native_requests_loaded_original_content'] = all(
        row['request']['skill_name'] == 'research-permissions-reader'
        and row['request']['skill_file_sha256'] == e['original_skill_sha256']
        and row['request']['session_id'] == row['context']['subject']['session_id']
        and row['request']['task_id'] == row['context']['subject']['task_id'] for row in proof['skill_sync_records'])
    old_source = private / 'skill-business-fixtures/research-permissions-reader/SKILL.md'
    candidate_source = private / 'skill-business-fixtures/reader-update-source/SKILL.md'
    checks['original_and_candidate_source_files_distinct'] = (
        hashlib.sha256(old_source.read_bytes()).hexdigest() == e['original_skill_sha256']
        and hashlib.sha256(candidate_source.read_bytes()).hexdigest() == e['candidate_skill_sha256']
        and e['original_skill_sha256'] != e['candidate_skill_sha256'])
    original_writes = [f for f in old['facts'] if f['action'] == 'fs.write' and f['effect'] == 'allow']
    candidate_writes = [f['resource']['value'] for f in approved['facts'] if f['action'] == 'fs.write' and f['effect'] == 'allow']
    checks['only_candidate_has_write_scope'] = not original_writes and len(candidate_writes) == 1
    companies = args.research_root.resolve() / 'data/wiki/companies'
    for label in ('candidate_unapproved', 'candidate_approved_not_installed'):
        phase = proof['update_phases'][label]; context = phase['context']; target = Path(phase['output_path'])
        rel = target.relative_to(companies)
        if (target.resolve() != target or len(rel.parts) != 5 or rel.parts[1:3] != ('analysis', 'runs')
                or not re.fullmatch(r'600000-SyntheticApi[a-f0-9]{16}', rel.parts[0])
                or not re.fullmatch(r'qwen-request-[a-f0-9]{16}', rel.parts[3]) or rel.parts[4] != 'permission-result.md'):
            raise ValueError('unowned target')
        verify(key, context)
        selected = [r for r in records if r.get('session_id') == context['subject']['session_id']]
        values = phase_checks(selected, context, input_path=companies / rel.parts[0] / 'synthetic.txt',
                              output_path=target, output_exists=target.exists())
        checks.update({label + '_' + k: v for k, v in values.items()})
        checks[label + '_current_bytes_and_grant_unchanged'] = phase['original_installation']['installed_sha256'] == e['original_skill_sha256']
        current = phase['original_installation']['grant']['grant']; verify(key, current)
        checks[label + '_signed_current_grant_unchanged'] = current == old
        checks[label + '_installed_source_is_runtime_source'] = (
            context['authority']['grant_id'] == old['grant_id'] and context['skill'] == old['skill']
            and context['install']['install_id'] == e['old_installation']['install_id']
            and e['original_skill_sha256'] == proof['candidate_image']['evaluation_skill_bundle']['skills']['research-permissions-reader']['sha256'])
        checks[label + '_candidate_scope_covers_attempt_but_is_unused'] = candidate_writes == [str(target.parent.parent)] and all(
            r.get('matched_grant_id') != approved['grant_id'] for r in selected if r.get('record_type') == 'decision')
        checks[label + '_old_installation_not_removed'] = phase['original_installation']['removal']['status'] == 'not_requested'
        checks[label + '_unexpected_file_is_rejected'] = not phase_checks(selected, context,
            input_path=companies / rel.parts[0] / 'synthetic.txt', output_path=target, output_exists=True)['actual_output_absent']
        wrong = copy.deepcopy(context); wrong['authority']['grant_id'] = approved['grant_id']
        checks[label + '_candidate_authority_substitution_rejected'] = not phase_checks(selected, wrong,
            input_path=companies / rel.parts[0] / 'synthetic.txt', output_path=target, output_exists=False)['same_installed_authority']
    changed = copy.deepcopy(bundle)
    next(r for r in changed['receipts'] if r.get('action') == 'deny')['action'] = 'allow'
    try:
        verify_receipt_bundles([changed])
    except (ValueError, InvalidSignature):
        checks['tampered_decision_rejected'] = True
    else:
        checks['tampered_decision_rejected'] = False
    protocol_path = c / 'protocols' / (args.batch + '.json'); protocol = json.loads(protocol_path.read_text())
    checks['frozen_protocol_matches_run'] = hashlib.sha256(protocol_path.read_bytes()).hexdigest() == run['pre_run_protocol_sha256']
    checks['immutable_image_matches_freeze'] = proof['candidate_image']['image_id'] == protocol['expected_image_id']
    checks['live_run_and_cleanup_passed'] = run['passed'] is True
    result = {'schema_version': 'siq.research-skill-update-review.v1', 'batch': args.batch,
        'passed': all(checks.values()), 'checks': checks,
        'limits': ['Two real business tasks with the original installed Reader; candidate is never committed or activated.',
                   'Does not yet prove behavior after completed replacement or reuse of old execution contexts.',
                   'Dedicated deployment and explicit controlled Skill selection; no daily-entry promotion.']}
    for directory, suffix, value in [('reports', '-verification', result), ('data', '-verified-receipts', bundle),
            ('data', '-skill-authority', {'public_key': public, 'contexts': contexts, **documents})]:
        with (c / directory / (args.batch + suffix + '.json')).open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
