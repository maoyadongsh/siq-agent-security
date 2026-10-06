"""Real target exclusivity and current authorization probes on owned resources."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

from common import write_json

VARIANTS = ('removed', 'empty', 'expired', 'wrong_asset', 'wrong_gateway', 'shared')
CASES = {'authority_other_instance': 201, 'authority_duplicate_binding': 409,
         'authority_impact': 200, 'authority_changed_submit': 409}
CASES.update({f'authority_{phase}_{variant}': 409 if phase == 'preview' else 502
              for phase in ('preview', 'rollback') for variant in VARIANTS})
ASSERTIONS = ['authority_duplicate_refused', 'authority_impact_honest', 'authority_stale_digest_refused',
              'authority_faults_verified'] + [f'authority_{phase}_{variant}_no_effect'
                                             for phase in ('preview', 'rollback') for variant in VARIANTS]


def catalog_digest(catalog):
    return hashlib.sha256((json.dumps(catalog, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest()


def altered(original, variant):
    result = copy.deepcopy(original)
    if variant == 'removed':
        return None
    if variant == 'empty':
        result['assignments'] = []
    elif variant == 'expired':
        now = datetime.now(timezone.utc)
        result['issued_at'] = (now - timedelta(hours=2)).isoformat()
        result['expires_at'] = (now - timedelta(hours=1)).isoformat()
    elif variant == 'wrong_asset':
        result['assignments'][0]['asset_id'] = 'different-owned-fixture-asset'
    elif variant == 'wrong_gateway':
        result['assignments'][0]['gateway_name_sha256'] = '0' * 64
    elif variant == 'shared':
        result['assignments'].append({**result['assignments'][0], 'id': 'conflicting-assignment', 'tenant_id': 'tp07-b'})
    else:
        raise ValueError('unknown authority variant')
    return result


def state(sql):
    # Failed rollback may append audit/diagnostics; effective state must not change.
    return {'bindings': sql('SELECT id,tenant_id,asset_id,agent_instance_id,backend_target_id,status FROM runtime_binding ORDER BY id'),
            'deployments': sql('SELECT id,status,to_revision FROM deployment ORDER BY id'),
            'changes': sql('SELECT id,status FROM change_request ORDER BY id'),
            'policies': sql('SELECT id,status FROM desired_policy ORDER BY id')}


def observe_no_effect(case, action, sql, record, readback, fixture=None):
    record(case + '_before_state', state(sql))
    readback(case + '_before_backend')
    record(case, action())
    record(case + '_after_state', state(sql))
    readback(case + '_after_backend')
    if fixture:
        record(case + '_effect', fixture.effect(case))


def fault_probes(phase, request, sql, record, readback, auth, fixture, original, body_or_path):
    path = fixture.root / 'operator-authority.json'
    raw = path.read_bytes()
    record('authority_' + phase + '_original_sha256', hashlib.sha256(raw).hexdigest())
    try:
        for variant in VARIANTS:
            case = f'authority_{phase}_{variant}'
            catalog = altered(original, variant)
            if catalog is None:
                path.unlink()
            else:
                write_json(path, catalog, exclusive=False)
            record(case + '_catalog', catalog)
            record(case + '_file_sha256', hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None)
            if phase == 'preview':
                action = lambda case=case: request(case, 'POST', '/api/v1/deployment-preview', auth,
                                         {**body_or_path, 'schema_version': 'deployment-preview-request/v1'})
            else:
                record(case + '_audit_before', sql("SELECT id FROM audit_event WHERE action='deployment.rollback_fail' ORDER BY id"))
                action = lambda case=case: request(case, 'POST', body_or_path + '/rollback', auth)
            observe_no_effect(case, action, sql, record, readback, fixture if phase == 'rollback' else None)
            if phase == 'rollback':
                record(case + '_audit_after', sql("SELECT id FROM audit_event WHERE action='deployment.rollback_fail' ORDER BY id"))
            path.write_bytes(raw)
    finally:
        path.write_bytes(raw)
        record('authority_' + phase + '_restored_sha256', hashlib.sha256(path.read_bytes()).hexdigest())


def before_deploy(request, sql, record, readback, auth, env, fixture, assets, asset, original, body, preview):
    other = next(item for item in assets if item['name'] == 'fixture-a' and item['id'] != asset['id'])
    instance = record('authority_other_instance', request('authority_other_instance', 'POST', f"/api/v1/assets/{other['id']}/instances", auth,
                      {'environment_id': env['id'], 'runtime': 'openshell'}))
    observe_no_effect('authority_duplicate_binding', lambda: request('authority_duplicate_binding', 'POST', '/api/v1/runtime-bindings', auth,
                      {'agent_instance_id': instance['id'], 'environment_id': env['id'], 'backend': 'openshell-cli', 'backend_target_id': fixture.target}),
                      sql, record, readback)
    record('authority_original_preview', preview)
    record('authority_selection', body.copy())
    record('authority_impact', request('authority_impact', 'POST', '/api/v1/deployment-preview/impact', auth,
           {**body, 'schema_version': 'enterprise-deployment-impact-request/v1', 'preview_digest': preview['preview_digest']}))
    fault_probes('preview', request, sql, record, readback, auth, fixture, original, body)
    # A valid replacement assignment still changes the exact authorization digest.
    path = fixture.root / 'operator-authority.json'
    raw = path.read_bytes()
    replacement = copy.deepcopy(original)
    replacement['assignments'][0]['id'] = 'valid-replacement-assignment'
    try:
        write_json(path, replacement, exclusive=False)
        record('authority_replacement_catalog', replacement)
        record('authority_replacement_sha256', hashlib.sha256(path.read_bytes()).hexdigest())
        observe_no_effect('authority_changed_submit', lambda: request('authority_changed_submit', 'POST', '/api/v1/deployment-preview/submit', auth,
                          {**body, 'schema_version': 'deployment-preview-submit/v1', 'preview_digest': preview['preview_digest']}), sql, record, readback)
    finally:
        path.write_bytes(raw)
        record('authority_submit_restored_sha256', hashlib.sha256(path.read_bytes()).hexdigest())


def before_rollback(request, sql, record, readback, auth, fixture, original, endpoint):
    fault_probes('rollback', request, sql, record, readback, auth, fixture, original, endpoint)


def unchanged(o, case):
    return o[case + '_before_state'] == o[case + '_after_state'] and o[case + '_before_backend'] == o[case + '_after_backend']


def evaluate(o):
    original = o['operator_assignment']
    item = original['assignments'][0]
    impact = o['authority_impact']
    subject = impact.get('registered_subject', {})
    replacement = copy.deepcopy(original)
    replacement['assignments'][0]['id'] = 'valid-replacement-assignment'
    results = {
        'authority_duplicate_refused': o['authority_duplicate_binding'].get('detail') == 'binding_target_conflict' and unchanged(o, 'authority_duplicate_binding'),
        'authority_impact_honest': impact.get('coverage') == 'registered_binding_only' and impact.get('shared_runtime_occupants') == 'unknown'
        and impact.get('skill_isolation') == 'not_established' and impact.get('execution_confirmation_supported') is False
        and all(subject.get(k) == item[k] for k in ('environment_id', 'asset_id', 'agent_instance_id'))
        and subject.get('binding_id') == o['authority_selection']['binding_id'] and impact.get('preview') == o['authority_original_preview'],
        'authority_stale_digest_refused': o['authority_changed_submit'].get('detail') == 'deployment_preview_changed'
        and unchanged(o, 'authority_changed_submit') and o['authority_replacement_catalog'] == replacement
        and o['authority_replacement_sha256'] == catalog_digest(replacement) != o['authority_preview_original_sha256']
        and o['authority_submit_restored_sha256'] == o['authority_preview_original_sha256'],
    }
    faults_ok = True
    nonces = []
    for phase in ('preview', 'rollback'):
        faults_ok &= o[f'authority_{phase}_original_sha256'] == o[f'authority_{phase}_restored_sha256'] == catalog_digest(original)
        for variant in VARIANTS:
            case = f'authority_{phase}_{variant}'
            catalog = o[case + '_catalog']
            if variant == 'expired':
                # Compare against initial issuance, not wall clock during offline review.
                equivalent = copy.deepcopy(catalog)
                issued, expires = (datetime.fromisoformat(equivalent.pop(k)) for k in ('issued_at', 'expires_at'))
                expected = {k: v for k, v in original.items() if k not in ('issued_at', 'expires_at')}
                faults_ok &= equivalent == expected and issued < expires < datetime.fromisoformat(original['issued_at'])
            else:
                faults_ok &= catalog == altered(original, variant)
            faults_ok &= (o[case + '_file_sha256'] is None) if catalog is None else (o[case + '_file_sha256'] == catalog_digest(catalog) != o[f'authority_{phase}_original_sha256'])
            response = o[case].get('detail', '')
            ok = unchanged(o, case)
            if phase == 'preview':
                ok &= response == 'deployment_target_authority_unverified'
            else:
                r = o[case + '_effect']
                nonces.append(r['business_path'])
                seen = [json.loads(line) for line in r['receiver_stdout'].splitlines()]
                ok &= response.startswith('openshell_rollback_failed: ') and r['exit_code'] != 0 and r['control_exit_code'] == 0
                ok &= sum(x.get('path') == r['control_path'] for x in seen) == 1 and not any(x.get('path') == r['business_path'] for x in seen)
                ok &= r['receiver_id'] == o['effect_applied']['receiver_id'] and r['target'] == o['effect_applied']['target']
                previous, current = o[case + '_audit_before'], o[case + '_audit_after']
                ok &= len(current) == len(previous) + 1 and {x[0] for x in previous} < {x[0] for x in current}
                ok &= o[case + '_before_backend'] == o['applied']
            results[case + '_no_effect'] = bool(ok)
    results['authority_faults_verified'] = bool(faults_ok and len(set(nonces)) == len(VARIANTS))
    if set(results) != set(ASSERTIONS):
        raise ValueError('authority assertion allocation differs')
    return results
