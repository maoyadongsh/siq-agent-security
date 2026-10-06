import pytest
from personal_runtime_browser import ref
from personal_runtime_browser_trial import score


def test_ref_requires_fresh_instance_and_control():
    snapshot = '- generic: Hermes · work\n- button "接入此实例" [ref=e14]\n'
    assert ref(snapshot, 'button "接入此实例"', after='Hermes · work') == 'e14'
    with pytest.raises(ValueError):
        ref(snapshot, 'button "接入此实例"', after='Hermes · other')
    with pytest.raises(ValueError):
        ref(snapshot, 'button "取消自检"')


def test_missing_capture_cannot_count_as_browser_success():
    result = score({})
    assert result['total'] == 36
    assert result['passed'] == 0
    assert not result['all_passed']


def test_one_missing_receipt_or_borrowed_filter_fails():
    result = score({'passed': {'receipt_ids': ['r1', 'r2', 'r3', 'r4', 'r5']},
                    'activity_detail': {'receipts': [{'receipt_id': x} for x in ('r1', 'r2', 'r3', 'r4')]},
                    'activity_reference': {'activity': {'binding': {'task_id': 't', 'agent_id': 'a', 'session_id': 's'}}},
                    'filters': {'task': 'other-task', 'agent': 'a', 'session': 's', 'links': 1}})
    assert not result['checks']['detail_exact_receipts']
    assert not result['checks']['return_filters_same_binding']


def test_result_presentation_requires_exact_API_reason_not_just_unknown():
    data = {'stages': {'activity-detail': {'text': '未设置结果核验。此任务未定义可核验的结果要求。当前调用记录不能证明任务完成。'}},
            'security_view': {'actual_result': {'status': 'unknown', 'reason_code': 'not_required'}}}
    assert score(data)['checks']['business_effect_not_falsely_verified']
    data['security_view']['actual_result']['reason_code'] = 'intent_missing'
    assert not score(data)['checks']['business_effect_not_falsely_verified']


def test_receipt_summary_is_exact_projection_with_go_zero_string():
    from review_personal_runtime_browser import PROJECTION_FIELDS, verify_projection
    signed = {k: k for k in PROJECTION_FIELDS if k != 'decision_receipt_id'}
    signed['seq'] = 0
    signed['sig'] = 'signature-not-exposed-by-summary'
    summary = {k: signed.get(k, '') for k in PROJECTION_FIELDS}
    verify_projection([summary], [signed])
    summary['decision_receipt_id'] = None
    with pytest.raises(ValueError):
        verify_projection([summary], [signed])
    summary['decision_receipt_id'] = ''
    summary['action'] = 'forged'
    with pytest.raises(ValueError):
        verify_projection([summary], [signed])
