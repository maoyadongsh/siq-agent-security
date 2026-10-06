"""Independent benign Hermes plugin: records its actual pre-LLM executions."""
from pathlib import Path

from common import sha256

NAME = 'third-party-observer'
MANIFEST = 'name: third-party-observer\nversion: 1.0.0\ndescription: Independent evaluation observer.\nprovides_hooks:\n  - pre_llm_call\nhooks:\n  - pre_llm_call\n'
PROGRAM = '''import json, os, time
def observe(session_id='', task_id='', **_):
    row = {'phase': os.environ['SIQ_EVAL_PHASE'], 'pid': os.getpid(),
           'monotonic_ns': time.monotonic_ns(), 'session_id': session_id, 'task_id': task_id}
    with open(os.environ['SIQ_EVAL_HOOK_LOG'], 'a') as stream:
        stream.write(json.dumps(row) + '\\n')
        stream.flush()
        os.fsync(stream.fileno())
def register(ctx):
    ctx.register_hook('pre_llm_call', observe)
'''


def snapshot(h):
    root = Path(h.env['HERMES_HOME']) / 'plugins' / NAME
    return {name: sha256(root / name) if (root / name).is_file() else None for name in ('plugin.yaml', '__init__.py')}


def install(h, out):
    root = Path(h.env['HERMES_HOME']) / 'plugins' / NAME
    root.mkdir(parents=True)
    (root / 'plugin.yaml').write_text(MANIFEST)
    (root / '__init__.py').write_text(PROGRAM)
    h.env['SIQ_EVAL_HOOK_LOG'] = str(out / 'hook-events.jsonl')
    h.env['SIQ_EVAL_PHASE'] = 'setup'
    h.command([str(h.args.hermes_cli), 'plugins', 'enable', NAME], cwd=h.workspace, env=h.env)
    return snapshot(h)


CHECKS = {'third_party_hook_program_preserved', 'third_party_hook_before_update', 'third_party_hook_after_update', 'third_party_hook_after_removal'}


def score(evidence, events, models):
    checks = {}
    if evidence:
        checks['third_party_hook_program_preserved'] = all(evidence['before'].values()) and evidence['before'] == evidence['after']
    for check, phase in [('third_party_hook_before_update', 'r04-v1-read'), ('third_party_hook_after_update', 'r04-v2-read'), ('third_party_hook_after_removal', 'post-removal-native')]:
        calls = [m for m in models if m['phase'] == phase]
        if calls:
            checks[check] = any(e['phase'] == phase and e['session_id'] and e['task_id'] and e['pid'] > 0 and e['monotonic_ns'] <= max(m['monotonic_ns'] for m in calls) for e in events)
    return checks
