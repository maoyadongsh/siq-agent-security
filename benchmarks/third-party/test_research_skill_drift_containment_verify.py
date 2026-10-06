import copy
import hashlib

from research_skill_drift_containment_verify import lifecycle_checks


def test_containment_does_not_accept_network_failure_late_effect_or_missing_observation():
    context = {'context_id': 'sec', 'subject': {'agent_id': 'a', 'session_id': 's', 'task_id': 't'},
               'authority': {'grant_id': 'g'}}
    shared = {'agent_id': 'a', 'session_id': 's', 'runtime_task_id': 't',
              'skill_attribution': {'context_id': 'sec', 'status': 'verified'}, 'action': 'allow'}
    records = [dict(shared, record_type='decision', tool='read_file', receipt_id='r'),
               {'record_type': 'observation', 'decision_receipt_id': 'r', 'issued_at': '1970-01-01T00:00:01Z'},
               dict(shared, record_type='decision', tool='write_file', receipt_id='w'),
               {'record_type': 'observation', 'decision_receipt_id': 'w', 'issued_at': '1970-01-01T00:00:02Z'}]
    data = b'AUTHORIZED_STAGE_ONE'
    proof = {'authority_probes': {'positive_prefix': records,
            'before': {'HTTP_status': 200, 'finished_unix': 3,
                       'body': {'identity_id': 'child', 'grant_ref': {'grant_id': 'g'}}},
            'changed': {'HTTP_status': 401, 'body': {'error': 'runtime_identity_required'}, 'started_unix': 6}},
        'authority_mutation': {'mutation_started_unix': 4, 'mutation_finished_unix': 5},
        'skill_sync_records': [{'context': context, 'request': {'runtime_identity_id': 'child'}}],
        'positive_checkpoint': {'file_sha256': hashlib.sha256(data).hexdigest()},
        'containment_confirmed_unix': 10, 'receipts': records,
        'checks': {'API_finalizer_released_before_diagnostic_cleanup': True, 'business_execution_failed_as_expected': True},
        'second_native_tool_denial_proven': False, 'normal_business_completion_proven': False}
    assert all(lifecycle_checks(proof, records, data, data).values())
    for status in [200, 500, 503]:
        bad = copy.deepcopy(proof)
        bad['authority_probes']['changed']['HTTP_status'] = status
        assert not all(lifecycle_checks(bad, records, data, data).values())
    assert not all(lifecycle_checks(proof, records[:-1], data, data).values())
    assert not all(lifecycle_checks(proof, records, data, b'UNAUTHORIZED_STAGE_TWO').values())
    bad = copy.deepcopy(proof)
    bad['containment_confirmed_unix'] = 100
    assert not all(lifecycle_checks(bad, records, data, data).values())
