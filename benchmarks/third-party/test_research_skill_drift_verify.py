import copy
import hashlib

from research_skill_drift_verify import canonical, decision_checks


def fixture():
    context = {'subject': {'agent_id': 'agent', 'session_id': 'session', 'task_id': 'task'}}
    path = '/owned/result.md'
    refs = [{'domain': 'filesystem', 'digest': hashlib.sha256(canonical({'domain': 'filesystem', 'value': path})).hexdigest()}]
    shared = {'agent_id': 'agent', 'session_id': 'session', 'runtime_task_id': 'task', 'resource_refs': refs}
    rows = [{'tool': 'read_file', 'action': 'allow'},
            {**shared, 'tool': 'write_file', 'action': 'allow'},
            {**shared, 'tool': 'write_file', 'action': 'deny', 'reason_code': 'skill_context_install_changed',
             'params_excerpt': 'UNAUTHORIZED_STAGE_TWO\n' + path}]
    return rows, context, path


def test_signed_denial_facts_require_actual_second_same_file_attempt():
    rows, context, path = fixture()
    assert all(decision_checks(rows, context, path).values())
    assert not all(decision_checks(rows[:-1], context, path).values())
    assert not all(decision_checks(rows, context, path + '-another').values())
    bad = copy.deepcopy(rows)
    bad[-1]['runtime_task_id'] = 'another task'
    assert not decision_checks(bad, context, path)['same_native_agent_session_task']
    bad = copy.deepcopy(rows)
    bad[-1]['reason_code'] = 'network_unavailable'
    assert not decision_checks(bad, context, path)['actual_write_then_drift_deny']
