import copy

from bound_runtime_faults import checks, first_read_seen, stage_measured


def checkpoint():
    decision = {'agent_id': 'rca-test', 'session_id': 's1', 'receipt_id': 'd1', 'action_id': 'a1', 'record_type': 'decision', 'tool_call_id': 'rc-first', 'action': 'allow'}
    observation = {'agent_id': 'rca-test', 'record_type': 'observation', 'tool_call_id': 'rc-first', 'decision_receipt_id': 'd1', 'action_id': 'a1'}
    return {'plan': {'check_id': 'rc-test'}, 'paused_state': 'T', 'before_injection': {'status': 'running'}, 'receipts_before': [decision, observation]}


def test_checkpoint_requires_own_correlated_observation():
    row = checkpoint()
    assert first_read_seen(row['receipts_before'], 'rc-test')
    assert not first_read_seen(row['receipts_before'], 'rc-another')
    assert stage_measured(row)
    row['receipts_before'][1]['decision_receipt_id'] = 'other-decision'
    assert not stage_measured(row)


def test_finished_or_late_pause_cannot_satisfy_checkpoint():
    row = checkpoint()
    row['before_injection']['status'] = 'passed'
    assert not stage_measured(row)
    row['before_injection']['status'] = 'running'
    row['receipts_before'].append({'agent_id': 'rca-test', 'record_type': 'decision', 'tool_call_id': 'rc-last'})
    assert not stage_measured(row)


def test_previous_allow_does_not_hide_new_allow_after_revoke():
    row = checkpoint()
    original = copy.deepcopy(row['receipts_before'])
    obs = {'variants': {'grant-revoked': row}, 'receipts': {'receipts': original}}
    assert checks(obs)['grant-revoked:no_new_allow']
    obs['receipts']['receipts'].append({'agent_id': 'rca-test', 'record_type': 'decision', 'tool_call_id': 'rc-last', 'action': 'allow'})
    assert not checks(obs)['grant-revoked:no_new_allow']


def test_missing_agent_attribution_cannot_hide_session_allow():
    row = checkpoint()
    obs = {'variants': {'grant-revoked': row}, 'receipts': {'receipts': copy.deepcopy(row['receipts_before']) + [
        {'agent_id': None, 'session_id': 's1', 'action': 'allow'}]}}
    assert not checks(obs)['grant-revoked:no_new_allow']
