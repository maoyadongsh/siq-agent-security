import copy

from scripts.openshell import prove_research_skill_drift_containment as drift


def test_first_effect_requires_both_real_observations_before_mutation():
    records = [
        {'record_type': 'decision', 'tool': 'read_file', 'action': 'allow', 'receipt_id': 'r'},
        {'record_type': 'observation', 'decision_receipt_id': 'r'},
        {'record_type': 'decision', 'tool': 'write_file', 'action': 'allow',
         'receipt_id': 'w', 'tool_call_id': 'first-write'},
        {'record_type': 'observation', 'decision_receipt_id': 'w'},
    ]
    checkpoint = {'tool_call_id': 'first-write'}
    assert drift.positive_prefix(records, checkpoint)
    assert not drift.positive_prefix(records[:-1], checkpoint)
    assert not drift.positive_prefix(records, {'tool_call_id': 'other-write'})
    invalid = copy.deepcopy(records)
    invalid[3]['decision_receipt_id'] = 'r'
    assert not drift.positive_prefix(invalid, checkpoint)


def test_interruption_cannot_be_reported_as_successful_business_completion():
    scenario = drift.ContainmentScenario.__new__(drift.ContainmentScenario)
    assert scenario.expected_status == 'failed'
    assert scenario.terminal_check_key == 'business_execution_failed_as_expected'
    assert not scenario.verify_reply('marker', 'marker: completed successfully')
    assert scenario.verify_reply('marker', '[失败] 任务执行连接中断，无法确认完整结果。请先核对已产生的文件或操作记录。')
    assert scenario.verify_reply('marker', '[失败] 任务执行权限或运行状态已变化，无法确认完整结果。请先核对已产生的文件或操作记录。')
    assert not scenario.verify_reply('marker', '当前会话已有请求正在处理，请等待当前结果完成后再试。')
