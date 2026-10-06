"""Owned child-process fault safety; not evidence of SIQ tool enforcement."""
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from scripts.openshell import research_owned_relay_fault as fault


@pytest.fixture
def child():
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        yield process
    finally:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGCONT)
            process.terminate()
        process.wait(timeout=5)


def test_pause_resumes_exact_owned_child_on_exception(child):
    identity = fault.snapshot(child.pid)
    guard = fault.PausedRelay(identity, timeout=2)
    with pytest.raises(ValueError):
        with guard:
            guard.assert_paused()
            raise ValueError('synthetic evaluator failure')
    assert fault.snapshot(child.pid)['state'] not in {'T', 't'}
    assert guard.evidence['watchdog_exit_code'] == 0
    assert guard.evidence['paused_unix'] <= guard.evidence['resumed_unix']


def test_watchdog_independently_resumes_when_evaluator_stalls(child):
    with fault.PausedRelay(fault.snapshot(child.pid), timeout=1) as guard:
        deadline = time.monotonic() + 4
        while guard.watchdog.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert guard.watchdog.poll() == 23
        assert fault.snapshot(child.pid)['state'] not in {'T', 't'}
        with pytest.raises(fault.RelayFaultError, match='window_ended'):
            guard.assert_paused()


def test_changed_process_identity_never_stops_child(child):
    identity = fault.snapshot(child.pid)
    identity['start_ticks'] += 1
    with pytest.raises(fault.RelayFaultError, match='process_changed'):
        with fault.PausedRelay(identity):
            pytest.fail('changed identity accepted')
    assert fault.snapshot(child.pid)['state'] not in {'T', 't'}


def test_watchdog_resumes_on_evaluator_pipe_loss(child):
    with fault.PausedRelay(fault.snapshot(child.pid), timeout=5) as guard:
        os.close(guard.release_fd)
        guard.release_fd = None
        assert guard.watchdog.wait(timeout=2) == 0
        assert fault.snapshot(child.pid)['state'] not in {'T', 't'}


@pytest.mark.parametrize('changed', ['uid', 'exe', 'cgroup', 'state', 'digest', 'unit'])
def test_rejects_nonowned_or_changed_relay(tmp_path, changed):
    binary = tmp_path / 'relay'
    binary.write_bytes(b'controlled binary fixture')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    unit = 'siq-qwen38-api-supervisor@' + 'a' * 16 + '.service'
    identity = {'uid': os.geteuid(), 'exe': str(binary), 'state': 'S', 'cgroup': '0::/user/' + unit + '\n'}
    fault.validate_owner(identity, unit=unit, binary=binary, expected_sha256=digest)
    if changed == 'digest':
        digest = '0' * 64
    elif changed == 'unit':
        unit = 'daily-relay.service'
    else:
        identity[changed] = {'uid': os.geteuid() + 1, 'exe': '/another/binary',
                             'cgroup': '0::/user/daily-relay.service\n', 'state': 'T'}[changed]
    with pytest.raises(fault.RelayFaultError, match='owner_invalid'):
        fault.validate_owner(identity, unit=unit, binary=binary, expected_sha256=digest)
