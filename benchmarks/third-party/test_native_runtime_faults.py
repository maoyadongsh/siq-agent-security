from native_runtime_faults import checks


def test_missing_timeout_cannot_pass():
    scored = checks({})
    assert not any(scored.values())


def test_killed_host_is_not_product_timeout():
    row = {'terminal': {'status': 'failed', 'reason_code': 'runtime_check_timeout'},
           'elapsed_seconds': 120, 'signals': ['SIGSTOP', 'SIGKILL_cleanup'],
           'intervention_cleanup': True, 'host_after': 'absent', 'observer_stopped': True}
    scored = checks({'variants': {'timeout': row}})
    assert not scored['timeout:deadline_enforced']
    assert not scored['timeout:host_stopped_by_product']


def test_recovery_and_revocation_do_not_share_success_criterion():
    row = {'terminal': {'status': 'passed', 'reason_code': 'runtime_check_passed', 'receipt_ids': ['1','2','3','4','5']}}
    scored = checks({'variants': {'grant-revoked': row, 'recovery': row}})
    assert not scored['grant-revoked:revoked_not_passed']
    assert scored['recovery:recovery_passed']


def test_pidfd_stops_and_resumes_only_owned_child():
    import os
    import signal
    import subprocess
    import time

    from native_runtime_faults import paused_state, pidfd_syscall, send_pidfd

    child = subprocess.Popen(['sleep', '10'])
    fd = pidfd_syscall(434, child.pid, 0)
    try:
        send_pidfd(fd, signal.SIGSTOP)
        deadline = time.monotonic() + 2
        while paused_state(child.pid) not in ('T', 't') and time.monotonic() < deadline:
            time.sleep(0.005)
        assert paused_state(child.pid) in ('T', 't')
        send_pidfd(fd, signal.SIGCONT)
    finally:
        send_pidfd(fd, signal.SIGKILL)
        child.wait(timeout=3)
        os.close(fd)


def test_missing_binding_only_before_attach_failure():
    import copy

    import pytest
    from verify_native_runtime_faults import missing_binding_allowed

    latest = {'result': {'check_id': 'rc-test', 'status': 'failed', 'reason_code': 'runtime_check_timeout'},
              'binding_id': '', 'intent_id': 'rci-test'}
    missing_binding_allowed(latest, [latest], [], [])
    passed = copy.deepcopy(latest)
    passed['result']['status'] = 'passed'
    with pytest.raises(ValueError):
        missing_binding_allowed(passed, [passed], [], [])
    with pytest.raises(ValueError):
        missing_binding_allowed(latest, [latest], [], [{'agent_id': 'rca-test'}])
