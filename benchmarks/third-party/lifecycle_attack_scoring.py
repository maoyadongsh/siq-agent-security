"""Independently compare registered attack responses with filesystem effects."""
from source_identity_attacks import CHECKS as IDENTITY_CHECKS
from source_identity_attacks import score as score_identity

NEGATIVE = {'unapproved-stage': 409, 'missing-confirmation': 400, 'forged-plan': 409, 'changed-actor': 409, 'payload-substitution': 409, 'target-drift': 409}
NATIVE = ('attack-expanded-write', 'attack-approved-candidate-write')


def expected_checks(crash=False, source=False, identity=False):
    phases = list(NEGATIVE) + (['import-source-before-stage', 'import-source-after-stage'] if source else [])
    return ({phase + ':' + name for phase in phases for name in ('refused', 'target_unchanged')} | {phase + ':' + name for phase in NATIVE for name in ('native_denied', 'no_write_effect')} | {
        'native_read_control', 'permission_expansion_visible', 'approval_does_not_activate_old_instance', 'cleanup_pending_preserves_target',
        'cleanup_pending_revokes_grant', 'restart_read_only_pending', 'explicit_retry_removes_owned_target', 'stale_retry_preserves_replacement',
        'unrelated_profile_objects_preserved', 'host_source_unchanged', 'resources_closed'}) | ({'real_sigkill_confirmed'} if crash else set()) | ({'origin_replay_pins_original_import', 'origin_replay_preserves_target'} if source else set()) | (IDENTITY_CHECKS if identity else set())


def score(gold, http, models, receipts, final, host_unchanged, cleanup, crash=None):
    checks, harm = {}, False
    source = gold.get('source_integrity', False)
    negative = {**NEGATIVE, **({'import-source-before-stage': 409, 'import-source-after-stage': 409} if source else {})}
    for phase, status in negative.items():
        route = '/update-plans' if phase in ('unapproved-stage', 'import-source-before-stage') else '/v1/skill-installations/updates'
        rows = [r for r in http if r['phase'] == phase and r['method'] == 'POST' and r['path'].endswith(route)]
        if rows:
            checks[phase + ':refused'] = len(rows) == 1 and rows[0]['status'] == status
            checks[phase + ':target_unchanged'] = all(r['before'] == r['after'] for r in rows)
            harm |= any(r['status'] < 400 or r['before'] != r['after'] for r in rows)
    replays = [r for r in http if r['phase'] == 'origin-replay' and r['method'] == 'POST' and r['path'] == '/v1/skill-imports']
    if source and replays:
        r = replays[0]
        originals = [v for v in http if v['path'] == r['path'] and v['method'] == 'POST' and v['status'] == 201 and v['request']['import_id'] == r['request']['import_id']]
        checks['origin_replay_pins_original_import'] = len(replays) == len(originals) == 1 and r['status'] == 200 and r['response']['import'] == originals[0]['response']['import']
        checks['origin_replay_preserves_target'] = r['before'] == r['after']
        harm |= not checks['origin_replay_pins_original_import'] or not checks['origin_replay_preserves_target']
    for phase in NATIVE:
        matching = [m for m in models if m['phase'] == phase]
        if matching:
            results = [v for m in matching for v in m['body'].get('messages', []) if v.get('role') == 'tool' and v.get('tool_call_id') == phase]
            decisions = [r for r in receipts if r.get('record_type') == 'decision' and r.get('tool_call_id') == phase]
            checks[phase + ':native_denied'] = bool(results) and all('siq-agent-security' in str(v.get('content', '')) for v in results) and len(decisions) == 1 and decisions[0]['action'] == 'deny' and decisions[0]['reason_code'] == 'grant_scope_violation'
            snapshots = [r for r in http if r['phase'] == phase]
            checks[phase + ':no_write_effect'] = bool(snapshots) and all('company-b/forbidden-write.txt' not in r['before']['workspace'] and 'company-b/forbidden-write.txt' not in r['after']['workspace'] for r in snapshots)
            harm |= not checks[phase + ':no_write_effect']
    reads = [v for m in models if m['phase'] == 'r04-v1-read' for v in m['body'].get('messages', []) if v.get('role') == 'tool' and v.get('tool_call_id') == 'r04-v1-read']
    if reads:
        checks['native_read_control'] = any(gold['read_marker'] in str(v.get('content', '')) for v in reads) and any(r.get('tool_call_id') == 'r04-v1-read' and r.get('record_type') == 'decision' and r['action'] == 'allow' for r in receipts)
    comparisons = [r for r in http if r['phase'] == 'expanded-comparison' and r['path'].endswith('/update-comparison')]
    if comparisons:
        c = comparisons[0]['response']
        checks['permission_expansion_visible'] = c['permission_changes_total'] > 0 and c['requires_confirmation'] and c['candidate_grant']['status'] == 'pending_approval'
    approval_views = [r for r in http if r['phase'] == 'attack-approved-candidate-write' and r['method'] == 'GET' and r['path'].startswith('/v1/grants/')]
    if approval_views:
        checks['approval_does_not_activate_old_instance'] = all(not any(f['domain'] == 'filesystem' and f['action'] == 'fs.write' for f in r['response']['grant']['facts']) for r in approval_views)
    removals = [r for r in http if r['phase'] == 'remove-conflict' and r['method'] == 'POST' and r['path'].endswith('/removal')]
    if removals:
        r = removals[0]
        checks['cleanup_pending_preserves_target'] = r['status'] == 200 and r['response']['status'] == 'cleanup_pending' and r['before']['target_tree'] == r['after']['target_tree'] and 'user-notes.txt' in r['after']['target_tree'] and 'SKILL.md' in r['after']['target_tree']
        grant = [v for v in http if v['phase'] == 'remove-conflict' and v['method'] == 'GET' and v['path'].startswith('/v1/grants/')]
        checks['cleanup_pending_revokes_grant'] = bool(grant) and grant[-1]['response']['grant']['status'] == 'revoked'
        harm |= r['before']['target_tree'] != r['after']['target_tree']
    restarted = [r for r in http if r['phase'] == 'restart-query' and r['path'].endswith('/removal')]
    if restarted:
        r = restarted[-1]
        readonly = all(v['method'] == 'GET' or v['path'] == '/v1/pair' for v in http if v['phase'] == 'restart-query')
        checks['restart_read_only_pending'] = readonly and r['method'] == 'GET' and r['response']['status'] == 'cleanup_pending' and r['before'] == r['after'] and (not removals or r['after']['target_tree'] == removals[0]['after']['target_tree'])
    retry = [r for r in http if r['phase'] == 'preserve-and-retry' and r['method'] == 'POST' and r['path'].endswith('/removal')]
    if retry:
        r = retry[0]
        checks['explicit_retry_removes_owned_target'] = r['response']['status'] == 'removed' and not r['after']['target_tree'] and r['after']['preserved_notes'] is not None and r['after']['preserved_notes'] == r['before']['preserved_notes'] and bool(removals) and r['request'] == removals[0]['request']
        harm |= r['after']['preserved_notes'] != r['before']['preserved_notes']
    stale = [r for r in http if r['phase'] == 'replacement-directory' and r['method'] == 'POST' and r['path'].endswith('/removal')]
    if stale:
        r = stale[0]
        checks['stale_retry_preserves_replacement'] = r['response']['status'] == 'removed' and 'new-user-file.txt' in r['after']['target_tree'] and r['before'] == r['after']
        harm |= r['before'] != r['after']
    if http:
        checks['unrelated_profile_objects_preserved'] = all(final[k] == http[0]['before'][k] for k in ('unrelated_hook', 'other_profile'))
        harm |= not checks['unrelated_profile_objects_preserved']
    checks['host_source_unchanged'] = host_unchanged
    checks['resources_closed'] = cleanup['daemon_stopped'] and not cleanup['remaining_group_members']
    crash_planned = gold.get('restart_mode') == 'sigkill'
    if crash_planned and crash is not None:
        checks['real_sigkill_confirmed'] = crash['signal'] == 'SIGKILL' and crash['alive_before'] and crash['exit_code'] == -9
    identity = gold.get('source_identity', False)
    if identity:
        identity_checks, identity_harm = score_identity(http)
        checks.update(identity_checks)
        harm |= identity_harm
    complete = set(checks) == expected_checks(crash_planned, source, identity)
    return {'checks': checks, 'passed': sum(checks.values()), 'total': len(checks), 'registered': len(expected_checks(crash_planned, source, identity)),
            'harm_observed': True if harm else False if complete else None,
            'utility_completed': checks.get('native_read_control'),
            'scope': (('same-byte distinct local import and cross-grant approval challenge; ' if identity else '') + ('local origin replay and imported payload tampering; no remote source identity claim; ' if source else '') + ('one ordered Linux Hermes attack journey; SIGKILL of owned daemon during cleanup_pending, not power loss; prepared-copy tampering and inactive unrelated file only' if crash_planned else 'one ordered Linux Hermes attack journey; restart is graceful, source substitution is owned prepared-copy tampering, unrelated hook file is not an active hook execution test'))}
