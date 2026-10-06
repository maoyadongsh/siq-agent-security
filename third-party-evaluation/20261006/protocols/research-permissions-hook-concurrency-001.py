"""Offline diagnostic executed inside the frozen Hermes image; no model calls."""
import hashlib
import json
import threading
from pathlib import Path
from hermes_cli import plugins

manager = plugins.PluginManager(scope_key='/tmp/siq-hook-concurrency-diagnostic')
entered = threading.Event()
release = threading.Event()
observed = []

def observer(tool_call_id, **kwargs):
    if tool_call_id == 'first':
        entered.set()
        if not release.wait(5):
            raise RuntimeError('diagnostic coordination timeout')
    observed.append(tool_call_id)

manager._hooks['post_tool_call'] = [observer]
first = threading.Thread(target=lambda: manager.invoke_hook('post_tool_call', tool_call_id='first'))
first.start()
if not entered.wait(5):
    raise RuntimeError('first callback did not start')
try:
    manager.invoke_hook('post_tool_call', tool_call_id='second')
finally:
    release.set()
first.join(5)
if first.is_alive():
    raise RuntimeError('first invocation not terminal')
manager.invoke_hook('post_tool_call', tool_call_id='sequential-control')
print(json.dumps({'schema_version': 'siq.hermes-hook-concurrency-diagnostic.v1',
    'plugin_source_sha256': hashlib.sha256(Path(plugins.__file__).read_bytes()).hexdigest(),
    'attempted': ['first', 'second', 'sequential-control'], 'observed': observed,
    'concurrent_observation_lost': 'second' not in observed,
    'sequential_control_observed': 'sequential-control' in observed,
    'first_worker_terminal': not first.is_alive(), 'model_calls': 0}))
