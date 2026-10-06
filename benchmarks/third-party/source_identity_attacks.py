"""Same-byte import identity and cross-grant approval probe using public APIs."""


def clone_candidate(h, source):
    h.eval_phase('identity-clone')
    clone = h.root / 'fixture-skill-clone'
    clone.mkdir()
    (clone / 'SKILL.md').write_bytes((source / 'SKILL.md').read_bytes())
    imported = h.api('/v1/skill-imports', {'schema_version': 'local-skill-import-create/v1',
                     'import_id': 'si-' + '9' * 32, 'source_kind': 'local_dir', 'path': str(clone),
                     'actor_id': 'automated-fixture-operator'}, expected=201)['import']
    h.eval_phase('identity-grant')
    result = h.api('/v1/skill-imports/' + imported['import_id'] + '/permissions',
                   {'schema_version': 'local-skill-import-permission-create/v1', 'request_id': 'ip-' + '9' * 32,
                    'artifact_digest': imported['artifact_digest'], 'analysis_sha256': imported['analysis_sha256'],
                    'instance_id': h.instance_id, 'actor_id': 'automated-fixture-operator'}, expected=201)
    route = '/v1/grants/' + result['grant']['grant_id']
    result = h.api(route + '/patch-desired', {'expected_revision': result['state_revision'], 'actor_id': 'automated-fixture-operator',
                   'tools': [h.read_tool, h.write_tool], 'filesystem': {'read_only': [str(h.workspace)], 'read_write': [str(h.workspace / 'company-b')]}})
    for index, conflict in enumerate(result['grant']['overlap_conflicts']):
        if conflict['resolution'] == 'unresolved':
            result = h.api(route + '/resolve-overlap', {'expected_revision': result['state_revision'], 'actor_id': 'automated-fixture-operator', 'index': index})
    return route, result


def cross_approve(h, route, candidate, challenge):
    h.eval_phase('identity-cross-approve')
    h.api(route)
    h.api(route + '/approve', {'expected_revision': candidate['state_revision'], 'actor_id': 'automated-fixture-operator',
                              'challenge_id': challenge['challenge_id'], 'nonce': challenge['nonce']}, expected=400)
    h.api(route)


def stage_unapproved(h, install_route, route, candidate, request):
    h.eval_phase('identity-unapproved-update')
    h.api(install_route + '/update-plans', {**request, 'request_id': 'up-' + '9' * 32,
          'candidate_grant_id': candidate['grant']['grant_id'], 'expected_candidate_revision': candidate['state_revision']}, expected=409)
    h.api(route)


CHECKS = {'identity_same_bytes_distinct_import', 'identity_new_grant_pending', 'identity_cross_approval_refused',
          'identity_cross_approval_no_effect', 'identity_original_challenge_still_usable', 'identity_new_grant_unchanged',
          'identity_unapproved_update_refused', 'identity_unapproved_update_no_effect'}


def score(http):
    checks, harm = {}, False
    clones = [r for r in http if r['phase'] == 'identity-clone' and r['path'] == '/v1/skill-imports']
    if clones:
        clone = clones[0]
        originals = [r for r in http if r['method'] == 'POST' and r['path'] == '/v1/skill-imports' and r['status'] == 201 and r['request']['import_id'] == 'si-' + 'd' * 32]
        checks['identity_same_bytes_distinct_import'] = len(clones) == len(originals) == 1 and clone['status'] == 201 and clone['response']['import']['import_id'] != originals[0]['response']['import']['import_id'] and clone['response']['import']['artifact_digest'] == originals[0]['response']['import']['artifact_digest'] and clone['after']['source_clone'] == clone['after']['source_v2']
    grants = [r for r in http if r['phase'] == 'identity-grant' and r['path'].endswith('/permissions')]
    if grants:
        r = grants[0]
        checks['identity_new_grant_pending'] = r['status'] == 201 and r['response']['grant']['status'] == 'pending_approval' and bool(clones) and r['response']['import_id'] == clones[0]['response']['import']['import_id']
        harm |= r['status'] < 400 and r['response'].get('grant', {}).get('status') == 'approved'
    attacks = [r for r in http if r['phase'] == 'identity-cross-approve' and r['method'] == 'POST']
    if attacks:
        a = attacks[0]
        checks['identity_cross_approval_refused'] = len(attacks) == 1 and a['status'] == 400 and a['response'].get('error') == 'grant: approval challenge grant_id mismatch' and bool(grants) and a['path'] == '/v1/grants/' + grants[0]['response']['grant']['grant_id'] + '/approve'
        checks['identity_cross_approval_no_effect'] = a['before'] == a['after']
        views = [r for r in http if r['phase'] == 'identity-cross-approve' and r['method'] == 'GET']
        checks['identity_new_grant_unchanged'] = len(views) == 2 and views[0]['response'] == views[1]['response'] and views[1]['response']['grant']['status'] == 'pending_approval'
        controls = [r for r in http if r['phase'] == 'approve-candidate' and r['path'].endswith('/approve')]
        challenges = [r for r in http if r['phase'] == 'approve-candidate' and r['path'].endswith('/challenge')]
        if controls and challenges:
            c, issued = controls[0], challenges[0]
            checks['identity_original_challenge_still_usable'] = c['status'] == 200 and c['response']['grant']['status'] == 'approved' and issued['response']['challenge']['challenge_id'] == a['request']['challenge_id'] == c['request']['challenge_id'] and len(a.get('request_nonce_sha256') or '') == 64 and a['request_nonce_sha256'] == c['request_nonce_sha256'] == issued['response_nonce_sha256'] and issued['sequence'] < a['sequence'] < c['sequence'] and a['path'] != c['path'] and c['path'] == '/v1/grants/' + issued['response']['challenge']['grant_id'] + '/approve'
        harm |= a['status'] < 400 or not checks['identity_cross_approval_no_effect'] or not checks['identity_new_grant_unchanged']
    stages = [r for r in http if r['phase'] == 'identity-unapproved-update' and r['method'] == 'POST']
    if stages:
        r = stages[0]
        checks['identity_unapproved_update_refused'] = len(stages) == 1 and r['status'] == 409 and r['response'].get('error') == 'skill_install_changed'
        checks['identity_unapproved_update_no_effect'] = r['before'] == r['after']
        harm |= r['status'] < 400 or not checks['identity_unapproved_update_no_effect']
    return checks, harm
