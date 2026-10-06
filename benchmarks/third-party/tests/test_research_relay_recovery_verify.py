"""Verifier negative calibrations; synthetic structures are not live results."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research_relay_recovery_verify as review


@pytest.fixture
def case(tmp_path):
    target, source = tmp_path / 'out', tmp_path / 'in'
    context = {'subject': {'agent_id': 'agent', 'session_id': 'session', 'task_id': 'task'},
               'authority': {'grant_id': 'grant'}, 'context_id': 'context', 'skill': {'content_hash': 'content'}}
    records, attempts = [], []
    for index, (tool, path, content) in enumerate([
        ('read_file', source, None), ('write_file', target, review.BEFORE),
        ('write_file', target, review.DURING), ('write_file', target, review.AFTER)]):
        args = {'path': str(path)}
        if content is not None:
            args['content'] = content.decode()
        digest = hashlib.sha256(review.canonical(args)).hexdigest()
        attempts.append({'tool': tool, 'tool_call_id': str(index), 'task_id': 'task', 'params_sha256': digest})
        if index == 2:
            continue
        decision = {'record_type': 'decision', 'receipt_id': 'r' + str(index),
            'action_id': 'a' + str(index), 'tool_call_id': str(index), 'tool': tool,
            'agent_id': 'agent', 'session_id': 'session', 'runtime_task_id': 'task',
            'matched_grant_id': 'grant', 'action': 'allow', 'effective_action': 'allow',
            'skill_attribution': {'context_id': 'context', 'status': 'verified', 'content_hash': 'content'},
            'resource_refs': review.resource_ref(path), 'params_digest': digest,
            'issued_at': '1970-01-01T00:00:01Z'}
        observation = dict(decision, record_type='observation', receipt_id='o' + str(index), decision_receipt_id=decision['receipt_id'])
        records.extend([decision, observation])
    pending = {'schema': 'pending_decision/v1', 'signed': False, 'outcome': 'deny', 'tool': 'write_file',
        'session_id': 'session', 'reason': 'decision service unavailable (instance session could not be verified)',
        'recorded_at': '1970-01-01T00:00:03Z'}
    raw = json.dumps(pending) + '\n'
    evidence = {'pending_records': [pending], 'pending_raw': raw, 'pending_sha256': hashlib.sha256(raw.encode()).hexdigest(),
        'tool_attempts': attempts, 'positive_observation_receipt_id': 'o1', 'checkpoint': {'tool_call_id': '1'},
        'fault': {'paused_state': 'T', 'resumed_state': 'S', 'watchdog_exit_code': 0,
            'paused_unix': 2, 'resume_requested_unix': 5, 'resumed_unix': 6},
        'pending_observed_unix': 4, 'recovery_ack_unix': 7, 'recovered_effect_observed_unix': 8}
    return records, context, evidence, {'input_path': source, 'target': target,
        'before': review.BEFORE, 'during': review.BEFORE, 'after': review.AFTER}


def test_complete_fixture_passes_effect_logic(case):
    records, context, evidence, inputs = case
    checks = review.effect_checks(records, context, evidence, **inputs)
    assert all(checks.values()), checks


@pytest.mark.parametrize('change', ['write_during_fault', 'no_recovery', 'no_pending', 'watchdog_expired',
    'wrong_task', 'missing_attempt', 'late_denial', 'wrong_allow', 'missing_observation'])
def test_rejects_missing_or_contradictory_evidence(case, change):
    records, context, evidence, inputs = copy.deepcopy(case)
    if change == 'write_during_fault': inputs['during'] = review.DURING
    elif change == 'no_recovery': inputs['after'] = None
    elif change == 'no_pending': evidence['pending_records'] = []
    elif change == 'watchdog_expired': evidence['fault']['watchdog_exit_code'] = 23
    elif change == 'wrong_task': context['subject']['task_id'] = 'other'
    elif change == 'missing_attempt': evidence['tool_attempts'].pop(2)
    elif change == 'late_denial': evidence['fault']['resume_requested_unix'] = 2
    elif change == 'wrong_allow': records[-2]['params_digest'] = evidence['tool_attempts'][2]['params_sha256']
    elif change == 'missing_observation': records.pop()
    assert not all(review.effect_checks(records, context, evidence, **inputs).values())
