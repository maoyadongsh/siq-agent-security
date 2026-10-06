import copy

from native_runtime_snapshot import checks


def test_missing_capture_cannot_satisfy_snapshot_contract():
    result = checks({}, 'plugin-entry')
    assert not result['snapshot_capture_complete']
    assert not result['snapshot_expected_old_status']
    assert not result['snapshot_fresh_check_passed']


def test_restored_bytes_cannot_revive_invalidated_history():
    obs = {'after_change': {'status': 'invalidated', 'reason_code': 'runtime_check_snapshot_changed'},
           'after_restore': {'status': 'passed'}, 'old_after_fresh': {'status': 'passed'}}
    result = checks(obs, 'plugin-entry')
    assert result['snapshot_expected_old_status']
    assert not result['snapshot_restore_old_status']
    assert not result['snapshot_old_stays_after_fresh']


def test_business_authority_loss_is_not_plugin_invalidation():
    obs = {'after_change': {'status': 'passed', 'reason_code': 'runtime_check_passed'},
           'after_restore': {'status': 'passed'}, 'old_after_fresh': {'status': 'passed'}}
    assert checks(obs, 'business-grant')['snapshot_expected_old_status']
    assert not checks(copy.deepcopy(obs), 'plugin-entry')['snapshot_expected_old_status']
