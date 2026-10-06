"""Registered attack journey against owned installation and update state."""
from pathlib import Path

from common import write_json
from process_resources import identity
from source_identity_attacks import clone_candidate, cross_approve, stage_unapproved


def run(h, out):
    observations = {}
    server, thread, _, _ = h._start_context_controller()
    target = Path(h.env['HERMES_HOME']) / 'skills/intent-fixture'
    install_route = '/v1/skill-installations/operations/' + h.current_install
    write_path = h.workspace / 'company-b/forbidden-write.txt'

    def capture(name):
        observations[name] = {'effects': h.effects(), 'old_grant': h.api(old_route), 'removal': h.api(install_route + '/removal')}
        write_json(out / ('stage-' + name + '.json'), observations[name])

    def native_write(name):
        h.eval_phase(name)
        h._run_native([{'id': name, 'tool': h.write_tool, 'params': {'path': str(write_path), 'content': 'UNAPPROVED_WRITE'}, 'outcome': 'deny'}], 'Write the synthetic note.', expected_prompt_text='intent-fixture', skills=('intent-fixture',))
        capture(name)

    try:
        h._native_read('r04-v1-read', 'intent-fixture', 'intent-fixture')
        old = h.api(install_route)
        old_route = '/v1/grants/' + old['plan']['grant_id']
        source, imported, _candidate_route, candidate, action = h._candidate()
        candidate = action('patch-desired', tools=[h.read_tool, h.write_tool], filesystem={'read_only': [str(h.workspace)], 'read_write': [str(h.workspace / 'company-b')]})
        h.eval_phase('expanded-comparison')
        compare = {'schema_version': 'local-skill-update-compare/v1', 'operation_signature': old['operation']['signature'], 'candidate_grant_id': candidate['grant']['grant_id'], 'expected_candidate_revision': candidate['state_revision']}
        comparison = h.api(install_route + '/update-comparison', compare)
        removal = h.api(install_route + '/removal')
        plan_request = {'schema_version': 'local-skill-update-stage-create/v1', 'request_id': 'up-' + 'f' * 32, 'operation_signature': old['operation']['signature'],
                        'candidate_grant_id': candidate['grant']['grant_id'], 'expected_candidate_revision': candidate['state_revision'],
                        'expected_previous_revision': comparison['previous_revision'], 'expected_binding_signature': removal['binding_signature'], 'actor_id': 'automated-fixture-operator'}
        h.eval_phase('unapproved-stage')
        h.api(install_route + '/update-plans', plan_request, expected=409)
        native_write('attack-expanded-write')
        if getattr(h, 'source_identity', False):
            clone_route, clone = clone_candidate(h, source)
        h.eval_phase('approve-candidate')
        challenge = action('challenge')['challenge']
        if getattr(h, 'source_identity', False):
            cross_approve(h, clone_route, clone, challenge)
            h.eval_phase('approve-candidate')
        candidate = action('approve', challenge_id=challenge['challenge_id'], nonce=challenge['nonce'])
        native_write('attack-approved-candidate-write')
        plan_request['expected_candidate_revision'] = candidate['state_revision']
        if getattr(h, 'source_identity', False):
            stage_unapproved(h, install_route, clone_route, clone, plan_request)
        if getattr(h, 'source_integrity', False):
            origin = source / 'SKILL.md'
            origin_bytes = origin.read_bytes()
            h.eval_phase('origin-replay')
            h.inject('replace_local_origin', origin, lambda: origin.write_text('CHANGED_LOCAL_ORIGIN_AFTER_APPROVAL\n'))
            h.api('/v1/skill-imports', {'schema_version': 'local-skill-import-create/v1', 'import_id': imported['import_id'], 'source_kind': 'local_dir', 'path': str(source), 'actor_id': 'automated-fixture-operator'})
            h.inject('restore_local_origin', origin, lambda: origin.write_bytes(origin_bytes))
            imported_payload = h.state / 'skill-imports/blobs' / imported['import_id'] / 'payload/SKILL.md'
            imported_bytes = imported_payload.read_bytes()
            h.eval_phase('import-source-before-stage')
            h.inject('replace_import_before_stage', imported_payload, lambda: imported_payload.write_text('CHANGED_APPROVED_IMPORT_PAYLOAD\n'))
            h.api(install_route + '/update-plans', plan_request, expected=409)
            h.inject('restore_import_before_stage', imported_payload, lambda: imported_payload.write_bytes(imported_bytes))
        h.eval_phase('prepare-approved')
        plan = h.api(install_route + '/update-plans', plan_request, expected=201)['plan']
        commit = {'schema_version': 'local-skill-update-commit/v1', 'update_id': plan['update_id'], 'plan_signature': plan['signature'], 'actor_id': plan['actor_id'], 'confirm_update': True}
        if getattr(h, 'source_integrity', False):
            h.eval_phase('import-source-after-stage')
            h.inject('replace_import_after_stage', imported_payload, lambda: imported_payload.write_text('CHANGED_APPROVED_IMPORT_PAYLOAD\n'))
            h.api('/v1/skill-installations/updates', commit, expected=409)
            h.inject('restore_import_after_stage', imported_payload, lambda: imported_payload.write_bytes(imported_bytes))
        h.eval_phase('missing-confirmation')
        h.api('/v1/skill-installations/updates', {**commit, 'confirm_update': False}, expected=400)
        h.eval_phase('forged-plan')
        h.api('/v1/skill-installations/updates', {**commit, 'plan_signature': '0' * 128}, expected=409)
        h.eval_phase('changed-actor')
        h.api('/v1/skill-installations/updates', {**commit, 'actor_id': 'different-operator'}, expected=409)
        payload = h.state / 'skill-installations/update-stages' / plan['update_id'] / 'payload/SKILL.md'
        original = payload.read_bytes()
        h.eval_phase('payload-substitution')
        h.inject('replace_staged_payload', payload, lambda: payload.write_text('ATTACKER_REPLACED_PREPARED_SKILL\n'))
        h.api('/v1/skill-installations/updates', commit, expected=409)
        h.inject('restore_owned_fixture_payload', payload, lambda: payload.write_bytes(original))
        h.eval_phase('target-drift')
        notes = target / 'user-notes.txt'
        h.inject('add_unknown_user_notes', notes, lambda: notes.write_text('PRESERVE_USER_NOTES\n'))
        h.api('/v1/skill-installations/updates', commit, expected=409)
        capture('target-drift')
        h.eval_phase('remove-conflict')
        view = h.api(install_route + '/removal')
        remove_request = {'schema_version': 'local-skill-install-remove/v1', 'operation_signature': view['record']['operation']['signature'], 'expected_grant_revision': view['state_revision'],
                          'expected_binding_signature': view['binding_signature'], 'actor_id': 'automated-fixture-operator', 'confirm_remove': True}
        h.api(install_route + '/removal', remove_request)
        capture('remove-conflict')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        # Keep the independent hook file. Disable only our test observer before restart.
        h.command([str(h.args.hermes_cli), 'plugins', 'disable', 'sec-bootstrap'], cwd=h.workspace, env=h.env)
    h.eval_phase('restart-query')
    if getattr(h, 'restart_mode', 'graceful') == 'sigkill':
        ref = identity(h.proc.pid)
        before = h.proc.poll()
        h.proc.kill()
        exit_code = h.proc.wait(timeout=10)
        write_json(out / 'crash.json', {'daemon': ref, 'alive_before': before is None, 'signal': 'SIGKILL', 'exit_code': exit_code, 'scope': 'owned daemon with cleanup_pending installation; native tool processes already exited'})
    h.stop()
    h.start()
    capture('restart-query')
    h.eval_phase('preserve-and-retry')
    h.inject('owner_moves_notes_to_safe_location', notes, lambda: notes.rename(h.root / 'preserved-user-notes.txt'))
    h.api(install_route + '/removal', remove_request)
    capture('preserve-and-retry')
    h.eval_phase('replacement-directory')

    def replace():
        target.mkdir()
        (target / 'new-user-file.txt').write_text('NEW_USER_DIRECTORY_CONTENT\n')
    h.inject('owner_recreates_target_directory', target, replace)
    h.api(install_route + '/removal', remove_request)
    capture('replacement-directory')
    write_json(out / 'attack-observations.json', observations)
    return {'checks': list(observations), 'scope': 'owned HTTP and native negative journey; restart_mode=' + getattr(h, 'restart_mode', 'graceful'), 'candidate_source_path': str(source)}
