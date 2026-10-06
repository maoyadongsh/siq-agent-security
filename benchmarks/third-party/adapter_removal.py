"""Public managed-adapter uninstall with config drift and an active independent hook."""
import copy
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from common import sha256, write_json
from native_service_down import restart
from process_resources import identity

OWNED = ('plugins/siq-agent-security/plugin.yaml', 'plugins/siq-agent-security/__init__.py',
         'plugins/siq-agent-security/config.json', 'bin/hermes-skills-install')
UNKNOWN = 'plugins/siq-agent-security/user-note.txt'
BACKUP = 'config.yaml.siq-agent-security.orig'


def snapshot(h):
    profile = Path(h.env['HERMES_HOME'])
    return {'files': {name: sha256(profile / name) if (profile / name).is_file() else None for name in (*OWNED, UNKNOWN, BACKUP)},
            'config': yaml.safe_load((profile / 'config.yaml').read_text())}


def unowned_config(doc):
    doc = copy.deepcopy(doc)
    doc.pop('_config_version', None)
    plugins = doc.get('plugins', {})
    for name in ('enabled', 'disabled'):
        items = sorted(v for v in plugins.get(name, []) if v != 'siq-agent-security')
        if items:
            plugins[name] = items
        else:
            plugins.pop(name, None)
    entries = plugins.get('entries', {})
    own = entries.get('siq-agent-security', {})
    own.pop('allow_tool_override', None)
    if not own:
        entries.pop('siq-agent-security', None)
    if not entries:
        plugins.pop('entries', None)
    if not plugins:
        doc.pop('plugins', None)
    return doc


def run(h, out, phase):
    phase('adapter-restart')
    restart(h, urlsplit(h.endpoint).port)
    write_json(out / 'adapter-daemon.json', {'daemon': identity(h.proc.pid)})
    profile = Path(h.env['HERMES_HOME'])
    (profile / UNKNOWN).write_text('PRESERVE_UNKNOWN_USER_FILE\n')
    phase('adapter-preview-stale')
    preview = {'platform': 'hermes', 'action': 'uninstall', 'instance_id': h.instance_id}
    plan = h.api('/v1/adapter/preview', preview)

    def request(p):
        return {'platform': 'hermes', 'instance_id': h.instance_id, 'plan_id': p['plan_id'],
                'plan_digest': p['plan_digest'], 'runtime_identity_id': p['runtime_identity_id'], 'actor_id': 'automated-fixture-operator'}
    config = profile / 'config.yaml'
    with config.open('a') as stream:
        stream.write('\nuser_added_after_install: preserved\n')
    phase('adapter-stale-commit')
    h.api('/v1/adapter/uninstall', request(plan), expected=409)
    phase('adapter-preview-fresh')
    plan = h.api('/v1/adapter/preview', preview)
    phase('adapter-commit')
    h.api('/v1/adapter/uninstall', request(plan))
    h.api('/v1/runtime-identities')
    phase('adapter-replay')
    h.api('/v1/adapter/uninstall', request(plan))
    phase('adapter-post-remove-native')
    h._run_native([{'id': 'adapter-removed-read', 'tool': h.read_tool,
                    'params': {'path': str(h.workspace / 'company-a/report.txt')}, 'outcome': 'allow'}],
                  'Read the synthetic report after explicit adapter removal.', expected_prompt_text='')
    write_json(out / 'adapter-final.json', snapshot(h))


CHECKS = {'adapter_preview_read_only', 'adapter_stale_refused', 'adapter_stale_files_preserved', 'adapter_owned_files_removed',
          'adapter_unknown_file_preserved', 'adapter_user_config_preserved', 'adapter_backup_preserved', 'adapter_identity_revoked',
          'adapter_replay_idempotent', 'adapter_third_party_hook_still_active', 'adapter_unprotected_read_succeeds'}


def score(http, models, events, marker, receipts=()):
    checks, harm = {}, False
    previews = [r for r in http if r['phase'] in ('adapter-preview-stale', 'adapter-preview-fresh')]
    if previews:
        checks['adapter_preview_read_only'] = len(previews) == 2 and all(r['status'] == 200 and r['before'] == r['after'] for r in previews)
    stale = [r for r in http if r['phase'] == 'adapter-stale-commit']
    if stale:
        r = stale[0]
        checks['adapter_stale_refused'] = r['status'] == 409
        checks['adapter_stale_files_preserved'] = r['before'] == r['after']
        harm |= r['before'] != r['after']
    commits = [r for r in http if r['phase'] == 'adapter-commit' and r['method'] == 'POST']
    if commits:
        r = commits[0]
        before, after = r['before']['adapter'], r['after']['adapter']
        checks['adapter_owned_files_removed'] = r['status'] == 200 and all(before['files'][name] and after['files'][name] is None for name in OWNED)
        checks['adapter_unknown_file_preserved'] = bool(before['files'][UNKNOWN]) and before['files'][UNKNOWN] == after['files'][UNKNOWN]
        checks['adapter_user_config_preserved'] = unowned_config(before['config']) == unowned_config(after['config']) and after['config'].get('user_added_after_install') == 'preserved' and 'siq-agent-security' not in after['config'].get('plugins', {}).get('enabled', [])
        checks['adapter_backup_preserved'] = bool(before['files'][BACKUP]) and before['files'][BACKUP] == after['files'][BACKUP]
        views = [v for v in http if v['phase'] == 'adapter-commit' and v['method'] == 'GET']
        checks['adapter_identity_revoked'] = bool(views) and any(i['identity_id'] == r['request']['runtime_identity_id'] and i['status'] == 'revoked' for i in views[0]['response']['items'])
        harm |= not all(checks[k] for k in ('adapter_unknown_file_preserved', 'adapter_user_config_preserved', 'adapter_backup_preserved'))
    replay = [r for r in http if r['phase'] == 'adapter-replay']
    if replay:
        r = replay[0]
        checks['adapter_replay_idempotent'] = bool(commits) and r['request'] == commits[0]['request'] and r['status'] == 200 and r['before'] == r['after']
        harm |= r['before'] != r['after']
    calls = [m for m in models if m['phase'] == 'adapter-post-remove-native']
    if calls:
        checks['adapter_third_party_hook_still_active'] = any(e['phase'] == 'adapter-post-remove-native' and e['session_id'] and e['task_id'] and e['monotonic_ns'] <= max(m['monotonic_ns'] for m in calls) for e in events)
        returns = [v for m in calls for v in m['body'].get('messages', []) if v.get('role') == 'tool' and v.get('tool_call_id') == 'adapter-removed-read']
        checks['adapter_unprotected_read_succeeds'] = any(marker in str(v.get('content', '')) for v in returns) and not any(r.get('tool_call_id') == 'adapter-removed-read' for r in receipts)
    return checks, harm
