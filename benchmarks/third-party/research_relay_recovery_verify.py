"""Separate receipt signatures, unsigned fail-closed trace, and file truth."""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime
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

BEFORE = b'AUTHORIZED_STAGE_ONE'
DURING = b'DURING_RELAY_OUTAGE'
AFTER = b'RECOVERED_RELAY_WRITE'


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def effect_checks(records, context, evidence, *, input_path, target, before, during, after):
    decisions = [r for r in records if r.get('record_type') == 'decision']
    observations = [r for r in records if r.get('record_type') == 'observation']
    writes = [r for r in decisions if r.get('tool') == 'write_file']
    reads = [r for r in decisions if r.get('tool') == 'read_file']
    pending = evidence.get('pending_records', [])
    attempts = evidence.get('tool_attempts', [])
    fault = evidence.get('fault', {})
    checks = {
        'three_allow_decisions_three_observations': len(records) == 6 and len(decisions) == len(observations) == 3,
        'one_read_two_successful_writes': len(reads) == 1 and len(writes) == 2,
        'exact_positive_before_bytes': before == BEFORE,
        'outage_preserves_same_file_bytes': during == before == BEFORE,
        'exact_recovered_file_bytes': after == AFTER,
        'same_agent_session_task_and_skill': bool(decisions) and all(
            r.get('agent_id') == context['subject']['agent_id']
            and r.get('session_id') == context['subject']['session_id']
            and r.get('runtime_task_id') == context['subject']['task_id']
            and r.get('matched_grant_id') == context['authority']['grant_id']
            and (r.get('skill_attribution') or {}).get('context_id') == context['context_id']
            and (r.get('skill_attribution') or {}).get('status') == 'verified'
            and (r.get('skill_attribution') or {}).get('content_hash') == context['skill']['content_hash']
            for r in decisions),
        'signed_permissions_allow_only': bool(decisions) and all(
            r.get('action') == r.get('effective_action') == 'allow' for r in decisions),
        'read_exact_resource': len(reads) == 1 and reads[0].get('resource_refs') == resource_ref(input_path),
        'writes_same_exact_resource': len(writes) == 2 and all(
            r.get('resource_refs') == resource_ref(target) for r in writes),
        'observations_linked_to_each_allowed_call': bool(decisions) and all(len([
            o for o in observations if o.get('decision_receipt_id') == r['receipt_id']
            and all(o.get(k) == r.get(k) for k in ('tool_call_id', 'action_id', 'session_id',
                'runtime_task_id', 'resource_refs', 'matched_grant_id'))]) == 1 for r in decisions),
        'native_unsigned_failclosed_record': len(pending) == 1 and pending[0].get('signed') is False
            and pending[0].get('schema') == 'pending_decision/v1' and pending[0].get('outcome') == 'deny'
            and pending[0].get('tool') == 'write_file'
            and pending[0].get('session_id') == context['subject']['session_id']
            and pending[0].get('reason') == 'decision service unavailable (instance session could not be verified)',
        'four_actual_tool_attempts': len(attempts) == 4 and [a.get('tool') for a in attempts]
            == ['read_file', 'write_file', 'write_file', 'write_file'],
        'attempts_have_distinct_call_ids': len(attempts) == 4 and len({a.get('tool_call_id') for a in attempts}) == 4,
        'attempts_same_task': len(attempts) == 4 and all(a.get('task_id') == context['subject']['task_id'] for a in attempts),
        'relay_paused_and_normally_resumed': fault.get('paused_state') in {'T', 't'}
            and fault.get('resumed_state') not in {None, 'T', 't', 'Z', 'X'}
            and fault.get('watchdog_exit_code') == 0 and not fault.get('process_exited_before_resume'),
    }
    digests = {label: hashlib.sha256(canonical({'path': str(target), 'content': raw.decode()})).hexdigest()
               for label, raw in [('before', BEFORE), ('during', DURING), ('after', AFTER)]}
    checks['positive_write_parameters'] = len(writes) == 2 and [r.get('params_digest') for r in writes] == [digests['before'], digests['after']]
    checks['outage_attempt_has_no_signed_allow'] = all(r.get('params_digest') != digests['during'] for r in decisions)
    checks['attempted_three_exact_writes'] = len(attempts) == 4 and [a.get('params_sha256') for a in attempts[1:]] == list(digests.values())
    checks['attempts_link_to_signed_calls'] = len(attempts) == 4 and [a.get('tool_call_id') for a in [attempts[0], attempts[1], attempts[3]]] == [r.get('tool_call_id') for r in decisions]
    try:
        checks['pending_bytes_match_independent_hash'] = (hashlib.sha256(evidence['pending_raw'].encode()).hexdigest()
            == evidence['pending_sha256'] and [json.loads(s) for s in evidence['pending_raw'].splitlines()] == pending)
        checks['failure_occurs_inside_paused_window'] = (fault['paused_unix'] <= timestamp(pending[0]['recorded_at'])
            <= evidence['pending_observed_unix'] <= fault['resume_requested_unix'])
        checks['same_process_recovery_before_positive_effect'] = (fault['resume_requested_unix'] <= fault['resumed_unix']
            <= evidence['recovery_ack_unix'] <= evidence['recovered_effect_observed_unix'])
        checks['positive_observation_precedes_fault'] = len([r for r in observations
            if r['receipt_id'] == evidence['positive_observation_receipt_id']
            and r['tool_call_id'] == evidence['checkpoint']['tool_call_id']
            and timestamp(r['issued_at']) <= fault['paused_unix']]) == 1
    except (KeyError, ValueError, IndexError, TypeError):
        checks['complete_chronology_required'] = False
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign', 'binary', 'research-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--batch', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'research-permissions-relay-recovery-[0-9]{3}', args.batch):
        raise ValueError('invalid batch')
    campaign = args.campaign.resolve()
    private = campaign / 'private/runs' / args.batch
    run = json.loads((campaign / 'reports' / (args.batch + '.json')).read_text())
    proof = run['proof']
    if run['batch'] != args.batch or hashlib.sha256(args.binary.read_bytes()).hexdigest() != run['binary_sha256']:
        raise ValueError('binary or batch mismatch')
    state = private / 'authority-state'
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'LANG') if k in os.environ}
    env['SIQ_AGENT_SECURITY_STATE_DIR'] = str(state)
    public = subprocess.run([str(args.binary), 'pubkey'], env=env, capture_output=True,
                            text=True, timeout=15, check=True).stdout.strip()
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True))
    records = [json.loads(line) for path in (state / 'receipts').glob('*/*.jsonl')
               for line in path.read_text().splitlines() if line]
    records.sort(key=lambda r: (r['chain_id'], r['seq']))
    bundle = {'fixture': args.batch, 'public_key': public, 'binary_sha256': run['binary_sha256'], 'receipts': records}
    verify_receipt_bundles([bundle])
    context = proof['skill_sync_records'][0]['context']
    grant = proof['relay_writer_grant']
    verify(key, context)
    verify(key, grant)
    evidence = proof['relay_fault_evidence']
    target = Path(evidence['output_path'])
    companies = args.research_root.resolve() / 'data/wiki/companies'
    relative = target.relative_to(companies)
    if (target.resolve() != target or len(relative.parts) != 5 or relative.parts[1:3] != ('analysis', 'runs')
            or not re.fullmatch(r'600000-SyntheticApi[a-f0-9]{16}', relative.parts[0])
            or not re.fullmatch(r'qwen-request-[a-f0-9]{16}', relative.parts[3]) or relative.parts[4] != 'permission-result.md'):
        raise ValueError('unowned output target')
    inputs = {'input_path': companies / relative.parts[0] / 'synthetic.txt', 'target': target,
        'before': (private / 'skill-business-fixtures/relay-before.txt').read_bytes(),
        'during': (private / 'skill-business-fixtures/relay-during.txt').read_bytes(),
        'after': target.read_bytes() if target.is_file() else None}
    checks = effect_checks(records, context, evidence, **inputs)
    writer = proof['skill_installations'][1]
    sync = proof['skill_sync_records'][0]['request']
    protocol_path = campaign / 'protocols' / (args.batch + '.json')
    protocol = json.loads(protocol_path.read_text())
    checks.update({
        'context_matches_installed_writer': context['install']['install_id'] == writer['install_id']
            and writer['name'] == sync['skill_name'] == 'research-permissions-writer',
        'signed_grant_matches_context': grant['grant_id'] == context['authority']['grant_id']
            and context['authority']['grant_digest'] == hashlib.sha256(canonical(
                json.loads(json.dumps(grant), parse_int=float))).hexdigest(),
        'installed_source_matches_loaded_immutable_skill': hashlib.sha256(
            (Path(writer['source_path']) / 'SKILL.md').read_bytes()).hexdigest() == writer['skill_file_sha256']
            == sync['skill_file_sha256'] == proof['candidate_image']['evaluation_skill_bundle']['skills'][writer['name']]['sha256'],
        'fault_owned_unit_matches_real_run': evidence['unit'] == 'siq-qwen38-api-supervisor@' + relative.parts[3].removeprefix('qwen-request-') + '.service'
            and evidence['fault']['process']['cgroup'].endswith('/' + evidence['unit'] + '\n'),
        'frozen_protocol_matches_run': hashlib.sha256(protocol_path.read_bytes()).hexdigest() == run['pre_run_protocol_sha256'],
        'expected_image_and_relay_match': proof['candidate_image']['image_id'] == protocol['expected_image_id']
            and evidence['relay_sha256'] == run['relay_sha256'] == protocol['expected_relay_sha256'],
        'actual_business_and_cleanup_passed': run['passed'] is True and proof['business_HTTP_attempted'] is True,
    })
    bad = copy.deepcopy(bundle)
    bad['receipts'][0]['action'] = 'deny'
    try:
        verify_receipt_bundles([bad])
    except (ValueError, InvalidSignature):
        checks['receipt_tamper_rejected'] = True
    else:
        checks['receipt_tamper_rejected'] = False
    for label, document in [('context', context), ('grant', grant)]:
        bad = copy.deepcopy(document)
        bad['signature'] = '0' * 128
        try:
            verify(key, bad)
        except (ValueError, InvalidSignature):
            checks[label + '_tamper_rejected'] = True
        else:
            checks[label + '_tamper_rejected'] = False
    for label, changes in [('missing_recovery_effect', {'after': None}), ('unauthorized_effect', {'during': DURING})]:
        checks[label + '_rejected'] = not all(effect_checks(records, context, evidence, **{**inputs, **changes}).values())
    result = {'schema_version': 'siq.research-relay-recovery-review.v1', 'batch': args.batch,
        'passed': all(checks.values()), 'checks': checks, 'signed_record_count': len(records),
        'unsigned_pending_count': len(evidence.get('pending_records', [])),
        'limits': ['Owned live relay is paused, not killed; no restart/crash recovery claim.',
            'Outage denial is a native unsigned pending record, not a signed SIQ decision.',
            'Dedicated real business deployment with evaluation Skill/context and fault synchronization.',
            'Synthetic permission effects only; no financial answer quality or daily-entry certification.']}
    for folder, suffix, value in [('reports', '-verification', result), ('data', '-verified-receipts', bundle),
        ('data', '-skill-authority', {'public_key': public, 'context': context, 'grant': grant})]:
        with (campaign / folder / (args.batch + suffix + '.json')).open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'passed': result['passed'], 'checks': len(checks),
                      'failed_checks': [k for k, v in checks.items() if not v]}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
