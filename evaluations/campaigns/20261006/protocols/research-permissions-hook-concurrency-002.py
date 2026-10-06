"""Real PluginManager concurrency diagnostic; offline, without model traffic."""
import contextvars
import hashlib
import json
import threading
from pathlib import Path
from hermes_cli import plugins

manager = plugins.PluginManager(scope_key='/tmp/siq-hook-diagnostic')
entered, release, waiting = (threading.Event() for _ in range(3))
scope = contextvars.ContextVar('diagnostic_scope')
observed, results = [], {}
def observer(tool_call_id):
    if tool_call_id == 'first':
        entered.set()
        if not release.wait(5):
            raise RuntimeError('diagnostic_release_timeout')
    observed.append([tool_call_id, scope.get()])
    return tool_call_id
manager._hooks['post_tool_call'] = [observer]
def invoke(name):
    scope.set(name)
    results[name] = manager.invoke_hook('post_tool_call', tool_call_id=name)
first = threading.Thread(target=invoke, args=('first',))
second = threading.Thread(target=invoke, args=('second',))
first.start()
if not entered.wait(5):
    raise RuntimeError('diagnostic_start_timeout')
event = manager._hook_running_callbacks[('post_tool_call', id(observer))]
if isinstance(event, threading.Event):
    original_wait = event.wait
    def tracked_wait(timeout=None):
        if threading.current_thread() is second:
            waiting.set()
        return original_wait(timeout)
    event.wait = tracked_wait
try:
    second.start()
    queued = waiting.wait(2)
finally:
    release.set()
    first.join(5)
    second.join(5)
checks = {'both_callbacks_delivered': observed == [['first','first'],['second','second']],
    'return_values_correct': results == {'first':['first'],'second':['second']},
    'workers_terminal': not first.is_alive() and not second.is_alive()}
print(json.dumps({'schema_version':'siq.hermes-hook-concurrency-diagnostic.v2',
    'plugin_source_sha256':hashlib.sha256(Path(plugins.__file__).read_bytes()).hexdigest(),
    'observed':observed,'results':results,'wait_observed':queued,'checks':checks,
    'passed':all(checks.values()),'model_calls':0}))
