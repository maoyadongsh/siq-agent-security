"""Causal public-API check of installed-content drift and runtime authority.

No model, sandbox, or business execution. Keep this diagnosis separate from
native tool denial: successful restoration does not make a failed run pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

from scripts.openshell import prove_research_skill_drift as drift


def inspect_self(authority, credential):
    started = time.time()
    request = urllib.request.Request(authority.endpoint + '/v1/runtime-identity/self',
        headers={'Authorization': 'Bearer ' + credential})
    try:
        response = authority.http.open(request, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        raw = response.read(16385)
        if len(raw) > 16384 or credential.encode() in raw:
            raise RuntimeError('candidate_drift_self_response_invalid')
        value = json.loads(raw)
        if response.status == 200:
            if (value.get('schema_version') != 'local-runtime-identity-self/v1'
                    or value.get('identity_id') != credential.split('.')[0]
                    or value.get('status') != 'active'):
                raise RuntimeError('candidate_drift_self_identity_invalid')
            projection = {k: value[k] for k in ('schema_version', 'identity_id', 'instance_id',
                          'agent_id', 'grant_ref', 'status', 'runtime_state')}
        elif response.status == 401 and value == {'error': 'runtime_identity_required'}:
            projection = value
        else:
            raise RuntimeError('candidate_drift_self_unexpected_response')
        return {'started_unix': started, 'finished_unix': time.time(),
                'HTTP_status': response.status, 'body': projection,
                'response_sha256': hashlib.sha256(raw).hexdigest()}


def restore(scenario):
    if scenario.original_installed is None:
        return
    path, raw, mode, backup = scenario.original_installed
    expected = (scenario.mutation or {}).get('after_sha256')
    if (path.resolve() != path or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            or backup.resolve() != backup or backup.read_bytes() != raw
            or backup.stat().st_mode & 0o777 != mode):
        raise RuntimeError('candidate_drift_restore_changed')
    os.replace(backup, path)
    scenario.original_installed = None


def paired_checks(before, changed, restored, mutation):
    return {
        'same_identity_active_before_and_after_restoration': before['HTTP_status'] == 200
            and restored['HTTP_status'] == 200 and before['body'] == restored['body'],
        'changed_install_rejected_by_runtime_authority': changed['HTTP_status'] == 401
            and changed['body'] == {'error': 'runtime_identity_required'},
        'distinct_installed_content': mutation['before_sha256'] != mutation['after_sha256'],
        'ordered_probes': before['finished_unix'] <= mutation['mutation_started_unix']
            <= mutation['mutation_finished_unix'] <= changed['started_unix']
            <= changed['finished_unix'] <= restored['started_unix'],
    }


def main():
    args = drift.arguments()
    os.umask(0o077)
    scenario = drift.DriftScenario(args)
    factory = scenario.factory
    result = {'schema_version': 'siq.research-skill-drift-authority.v1', 'passed': False,
              'scope': 'public_authority_api_only', 'model_calls': 0,
              'business_HTTP_attempted': False, 'native_tool_denial_proven': False, 'checks': {}}
    try:
        factory.login()
        source = scenario.setup_state / 'synthetic.txt'
        source.write_text('Synthetic permission fixture.\n')
        output = scenario.setup_state / 'output'
        output.mkdir(mode=0o700)
        factory.prepare(scenario.setup_state, read_path=source, write_path=output)
        factory.selected = factory.installations[1]
        issued, context = factory.select(factory.selected,
            session_id='drift-diagnosis-' + secrets.token_hex(16), task_id='drift-authority-diagnosis')
        credential = Path(issued['credential_path']).read_text().strip()
        result['context'] = context
        before = inspect_self(factory, credential)
        result['before'] = before
        scenario.mutation = scenario.mutate(context)
        result['mutation'] = scenario.mutation
        changed = inspect_self(factory, credential)
        result['changed'] = changed
        restore(scenario)
        restored = inspect_self(factory, credential)
        result['restored'] = restored
        result['checks'].update(paired_checks(before, changed, restored, scenario.mutation))
    except Exception as exc:
        result['failure_type'] = type(exc).__name__
        if type(exc) is RuntimeError and re.fullmatch('candidate_[a-z_]+', str(exc)):
            result['failure_code'] = str(exc)
    finally:
        try:
            restore(scenario)
            result['checks']['owned_installation_restored'] = True
            if factory.admin:
                factory.close()
            result['checks']['owned_grants_installations_identity_removed'] = bool(factory.installations) and all(
                row.get('removed_and_grant_revoked') is True for row in factory.installations)
        except Exception as exc:
            result['cleanup_failure_type'] = type(exc).__name__
        result['installations'] = factory.installations
        result['passed'] = not result.get('failure_type') and not result.get('cleanup_failure_type') and all(
            result['checks'].values()) and len(result['checks']) == 6
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'passed': result['passed'], 'checks': result['checks']}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
