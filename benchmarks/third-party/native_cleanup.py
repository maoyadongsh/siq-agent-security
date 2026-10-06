"""Observe owned native descendants draining; never signal unrelated processes."""
import os
import time
from itertools import pairwise

from process_resources import members


def observe_cleanup(daemon_stopped, *, grace_seconds=5, poll_seconds=0.1):
    if not 0 <= grace_seconds <= 10 or not 0 < poll_seconds <= 1:
        raise ValueError('invalid cleanup observation bound')
    pid = os.getpid()
    if os.getpgrp() != pid:
        raise ValueError('cleanup requires an isolated owned process group')
    started = time.monotonic_ns()
    deadline = time.monotonic() + grace_seconds
    observations = []
    while True:
        remaining = members(pid, exclude=(pid,))
        observations.append({'monotonic_ns': time.monotonic_ns(), 'members': remaining})
        if not remaining or time.monotonic() >= deadline:
            break
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
    return {'remaining_group_members': remaining, 'daemon_stopped': daemon_stopped,
            'observation_version': 1, 'grace_seconds': grace_seconds,
            'window_start_ns': started, 'observations': observations,
            'policy': 'observe only; persistent members fail cleanup; no signals sent'}


def verify_cleanup(data, grace_seconds):
    observations = data.get('observations', [])
    if data.get('observation_version') != 1 or data.get('grace_seconds') != grace_seconds or not observations:
        raise ValueError('native cleanup observation contract differs')
    times = [data['window_start_ns']] + [row['monotonic_ns'] for row in observations]
    if any(a > b for a, b in pairwise(times)):
        raise ValueError('native cleanup observation clock differs')
    if data['remaining_group_members'] != observations[-1]['members']:
        raise ValueError('native cleanup final members differ')
    if any(not row['members'] for row in observations[:-1]):
        raise ValueError('native cleanup continued after clean observation')
    if data['remaining_group_members'] and (times[-1] - times[0]) / 1e9 < grace_seconds:
        raise ValueError('native cleanup ended before registered grace')
