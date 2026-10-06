"""Passive hooks installed only into the owned evaluation Hermes profile."""
import json
import os
import threading
import time
from pathlib import Path

LOCK = threading.Lock()
FIELDS = {'session_id', 'task_id', 'tool_name', 'tool_call_id', 'parent_session_id', 'parent_turn_id',
          'parent_subagent_id', 'child_session_id', 'child_subagent_id', 'child_role', 'child_status',
          'child_summary', 'duration_ms', 'tool_call_history'}


def record(event, **kwargs):
    value = {k: v for k, v in kwargs.items() if k in FIELDS}
    value.update(event=event, pid=os.getpid(), monotonic_ns=time.monotonic_ns())
    with LOCK:
        path = Path(os.environ['EVALUATION_DELEGATION_OBSERVER'])
        with path.open('a') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, default=str) + '\n')
            stream.flush()


def register(ctx):
    for event in ('pre_llm_call', 'pre_tool_call', 'post_tool_call', 'subagent_start', 'subagent_stop'):
        def callback(*, _event=event, **kwargs):
            return record(_event, **kwargs)
        ctx.register_hook(event, callback)
    record('observer_registered')
