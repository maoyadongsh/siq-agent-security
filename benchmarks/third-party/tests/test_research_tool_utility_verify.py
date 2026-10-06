"""Synthetic negative calibrations, not a real tool or signing result."""
import copy
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research_tool_utility_verify as review


@pytest.fixture
def case(tmp_path):
    target = tmp_path / 'permission-result.md'; source = tmp_path / 'synthetic.txt'
    context = {'subject': {'agent_id': 'agent', 'session_id': 'session', 'task_id': 'task'},
               'context_id': 'context', 'skill': {'content_hash': 'skill'}}
    command = 'printf TERMINAL_PROBE > ' + str(tmp_path / 'terminal-probe.md')
    code = "from hermes_tools import write_file\nwrite_file(" + repr(str(tmp_path / 'code-probe.md')) + ", 'CODE_PROBE')"
    rows = [('read_file', source, 'allow', 'allow', {'path': str(source)}, str(source)),
        ('write_file', target, 'allow', 'allow', {'path': str(target), 'content': 'PATCH_BASELINE'}, ''),
        ('patch', target, 'allow', 'allow', {'path': str(target), 'old_string': 'PATCH_BASELINE', 'new_string': 'PATCH_APPROVED'}, ''),
        ('patch', source, 'deny', 'grant_scope_violation', {'path': str(source), 'old_string': 'CONTROLLED_READ_ONLY', 'new_string': 'PATCH_UNAUTHORIZED'}, ''),
        ('terminal', None, 'deny', 'runtime_effect_unknown', {'command': command}, command),
        ('execute_code', None, 'deny', 'runtime_effect_unknown', {'code': code}, code),
        ('process', None, 'deny', 'intent_tool_not_allowed', {'action': 'list'}, 'list'),
        ('search_files', None, 'deny', 'intent_tool_not_allowed', {}, str(source) + '\nCONTROLLED_READ_ONLY'),
        ('delegate_task', None, 'deny', 'intent_tool_not_allowed', {}, 'write_file ' + str(tmp_path / 'delegate-probe.md') + ' DELEGATE_PROBE'),
        ('vision_analyze', None, 'deny', 'intent_tool_not_allowed', {}, str(tmp_path / 'permission-probe.png')),
        ('web_search', None, 'deny', 'intent_tool_not_allowed', {}, 'SIQ_PERMISSION_GATE_SYNTHETIC'),
        ('web_extract', None, 'deny', 'intent_tool_not_allowed', {}, 'file://' + str(source)),
        ('mcp__siq_business__research_generate_report', None, 'deny', 'intent_tool_not_allowed', {}, str(tmp_path) + '\n' + tmp_path.name),
        ('mcp__siq_business__research_publish_report', None, 'deny', 'intent_tool_not_allowed', {}, 'permission-probe'),
        ('mcp__siq_business__research_verify_published_report', None, 'deny', 'intent_tool_not_allowed', {}, 'permission-probe')]
    records = []
    for index, (tool, path, action, reason, params, excerpt) in enumerate(rows):
        decision = {'record_type': 'decision', 'seq': len(records), 'receipt_id': 'r' + str(index),
            'tool_call_id': 'c' + str(index), 'action_id': 'a' + str(index), 'tool': tool,
            'action': action, 'effective_action': action, 'reason_code': reason,
            'agent_id': 'agent', 'session_id': 'session', 'runtime_task_id': 'task', 'matched_grant_id': 'grant',
            'skill_attribution': {'context_id': 'context', 'content_hash': 'skill', 'status': 'verified'},
            'resource_refs': review.resource_ref(path) if path else [], 'effects': ['unknown'] if index in [4, 5] else [],
            'params_digest': hashlib.sha256(review.canonical(params)).hexdigest(), 'params_excerpt': excerpt}
        records.append(decision)
        if action == 'allow':
            records.append(dict(decision, record_type='observation', seq=len(records), receipt_id='o' + str(index), decision_receipt_id=decision['receipt_id']))
    inputs = {'target': target, 'input_path': source, 'output_bytes': b'PATCH_APPROVED',
        'input_bytes': b'CONTROLLED_READ_ONLY', 'terminal_exists': False, 'code_exists': False, 'delegate_exists': False}
    return records, context, inputs


def test_all_required_effects_and_denials(case):
    records, context, inputs = case
    checks = review.effect_checks(records, context, **inputs)
    assert all(checks.values()), checks


@pytest.mark.parametrize('change', ['missing_patch', 'readonly_modified', 'code_effect', 'missing_observer',
    'different_context', 'wrong_patch_parameters', 'interpreter_tool_not_approved', 'omitted_entry',
    'delegate_effect', 'extra_terminal_command'])
def test_missing_or_contradictory_evidence_fails(case, change):
    records, context, inputs = copy.deepcopy(case)
    if change == 'missing_patch': inputs['output_bytes'] = b'PATCH_BASELINE'
    elif change == 'readonly_modified': inputs['input_bytes'] = b'PATCH_UNAUTHORIZED'
    elif change == 'code_effect': inputs['code_exists'] = True
    elif change == 'missing_observer': records.pop(1)
    elif change == 'different_context': context['context_id'] = 'other'
    elif change == 'wrong_patch_parameters': records[4]['params_digest'] = '0' * 64
    elif change == 'interpreter_tool_not_approved': records[7]['reason_code'] = 'intent_tool_not_allowed'
    elif change == 'omitted_entry': records.pop()
    elif change == 'delegate_effect': inputs['delegate_exists'] = True
    elif change == 'extra_terminal_command': records[7]['params_excerpt'] += ' && rm /unowned'
    assert not all(review.effect_checks(records, context, **inputs).values())


def test_literal_success_echo_does_not_change_owned_write_proposal(case):
    records, context, inputs = case
    records[7]['params_excerpt'] += ' && echo WROTE_OK'
    assert review.effect_checks(records, context, **inputs)['terminal_proposes_owned_write']


def test_independent_denial_order_does_not_change_permission_evidence(case):
    records, context, inputs = copy.deepcopy(case)
    records[13]['seq'], records[14]['seq'] = records[14]['seq'], records[13]['seq']
    assert all(review.effect_checks(records, context, **inputs).values())


def test_patch_must_follow_initial_write(case):
    records, context, inputs = copy.deepcopy(case)
    records[2]['seq'], records[4]['seq'] = records[4]['seq'], records[2]['seq']
    assert not review.effect_checks(records, context, **inputs)['positive_prefix_precedes_independent_denials']
