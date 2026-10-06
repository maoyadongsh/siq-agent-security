"""Actual delivery requires receiver and execution evidence in all three phases."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enterprise_runtime import evaluate


def fixture():
    result = {}
    for stage in ('before', 'applied', 'rolled_back'):
        allow = stage != 'applied'
        control, business = '/control/' + stage, '/business/' + stage
        events = [{'ready': True}, {'path': control}]
        if allow:
            events.append({'path': business})
        result['effect_' + stage] = {'receiver_id': 'receiver-1', 'target': 'sandbox-1', 'control_path': control, 'business_path': business,
                                     'receiver_stdout': '\n'.join(json.dumps(x) for x in events), 'control_exit_code': 0, 'exit_code': 0 if allow else 22, 'stdout': business if allow else ''}
    return result


def test_three_phase_effect_control():
    assert all(evaluate(fixture()).values())


@pytest.mark.parametrize('mutation', ['delivered_while_denied', 'receiver_down', 'wrong_stdout', 'duplicate_delivery', 'other_target', 'false_cli_success', 'old_nonce'])
def test_false_protection_or_utility_rejected(mutation):
    o = fixture()
    if mutation == 'delivered_while_denied': o['effect_applied']['receiver_stdout'] += '\n' + json.dumps({'path': '/business/applied'})
    if mutation == 'receiver_down': o['effect_applied']['control_exit_code'] = 1
    if mutation == 'wrong_stdout': o['effect_before']['stdout'] = ''
    if mutation == 'duplicate_delivery': o['effect_before']['receiver_stdout'] += '\n' + json.dumps({'path': '/business/before'})
    if mutation == 'other_target': o['effect_rolled_back']['target'] = 'other'
    if mutation == 'false_cli_success': o['effect_applied']['exit_code'] = 0
    if mutation == 'old_nonce': o['effect_rolled_back']['receiver_stdout'] = o['effect_before']['receiver_stdout']
    assert not all(evaluate(o).values())
