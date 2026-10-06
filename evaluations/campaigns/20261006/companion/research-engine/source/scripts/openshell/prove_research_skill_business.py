"""Real analysis HTTP/Qwen/Hermes/OpenShell with two installed Skill grants.

The host-only evaluation synchronizer issues SECs for actual native tasks.
Neither model nor sandbox receives administrator approval credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.openshell import (
    agentshield_runtime_binding as roots,
    prove_qwen38_business_api as business,
    prove_qwen38_native_tool_security as native,
    prove_research_business_permissions as permissions,
    research_permission_skill_image as skill_image,
)
from scripts.openshell.research_permission_skills import InstalledPermissionSkills
from services import qwen38_request_sandbox as sandbox


class SkillAuthority(InstalledPermissionSkills):
    def login(self):
        if not self.admin:
            super().login()

    def issue_root(self, row):
        if self.identity_id:
            self.revoke()
            self.identity_id = ''
        self.selected = row
        self.grant = self.api('/v1/grants/' + row['grant_id'])
        issued = self.api('/v1/runtime-identities', {
            'schema_version': 'local-runtime-identity-create/v1', 'instance_id': self.instance_id,
            'grant_id': row['grant_id'], 'expected_grant_revision': self.grant['state_revision'],
            'actor_id': 'research-permissions-operator', 'session_ttl_seconds': 600}, expected=201)
        self.identity_id = issued['identity']['identity_id']
        return issued

    def create(self, *, run_id, sandbox_name, state, allowed, scope_id):
        issued = self.issue_root(self.installations[getattr(self, 'initial_index', 0)])
        directory = state / roots.DEFAULT_RELATIVE.parent
        directory.mkdir(mode=0o700, parents=True)
        native.proof._private_json(state / roots.DEFAULT_RELATIVE, {
            'schema_version': roots.SCHEMA_VERSION, 'runtime_identity_id': self.identity_id,
            'instance_id': self.instance_id, 'agent_id': self.agent_id,
            'grant_id': self.grant['grant']['grant_id'], 'grant_revision': self.grant['state_revision'],
            'credential_path': issued['credential_path'], 'scope_id': scope_id,
            'relay_binary': str(self.args.relay_binary), 'relay_sha256': self.args.relay_sha256,
            'helper_image_ref': self.args.helper_image_ref, 'helper_image_id': self.args.helper_image_id})
        self.controller = native.security.CandidateToolSecurity(
            binding=roots.load(state, expected_scope_id=scope_id), run_id=run_id,
            sandbox_name=sandbox_name, state=state, allowed=allowed, revoke=self.revoke,
            relay_port=self.args.relay_port)
        return self.controller


class SkillScenario(permissions.PermissionScenario):
    def __init__(self, args):
        super().__init__(args)
        self.factory = SkillAuthority(args)
        self.company_directory = '600000-SyntheticApi' + secrets.token_hex(8)
        self.setup_state = args.output.parent / 'skill-business-fixtures'
        self.setup_state.mkdir(mode=0o700)
        self.sync_records = []
        self.sync_failures = []

    def prepare(self):
        self.factory.login()
        company = business.api.ROOT / 'data/wiki/companies' / self.company_directory
        self.factory.prepare(self.setup_state, read_path=company / 'synthetic.txt',
                             write_path=company / 'analysis/runs')
        self.candidate_image_record = skill_image.build(self.setup_state, self.factory.installations)

    def request_body(self, marker, trace_marker, company):
        body = super().request_body(marker, trace_marker, company)
        body['message'] += ' SIQ_PERMISSION_SKILL=' + self.factory.selected['name']
        return body

    def _synchronize(self, stop):
        try:
            while not stop.wait(.5):
                rows = self.completion_rows()
                if len(rows) != 1 or not rows[0].pool_binding_run_id:
                    continue
                run_id = rows[0].pool_binding_run_id
                if not re.fullmatch(r'qwen-request-[a-f0-9]{16}', run_id):
                    raise RuntimeError('candidate_skill_sync_run_invalid')
                name = 'siq-qwen38-scoped-' + run_id.removeprefix('qwen-request-')
                read_code = ("import pathlib; p=pathlib.Path('/tmp/siq-research-skill-sync/request.json'); "
                             "print(p.read_text() if p.is_file() else '{}')")
                response = sandbox._run(['sandbox', 'exec', '--name', name, '--timeout', '8', '--no-tty',
                    '/opt/siq/hermes/venv/bin/python', '-c', read_code], timeout=12)
                if response.returncode:
                    continue
                request = json.loads(response.stdout)
                if not request:
                    continue
                row = self.factory.selected
                namespace = f'siq:openshell:pool:{self.scope}:{run_id}:siq_analysis'
                expected = namespace + ':' + hashlib.sha256(request['native_session_id'].encode()).hexdigest()
                business.api.require(request['schema_version'] == 'siq.research-skill-sync.v1'
                    and request['skill_name'] == row['name'] and request['skill_file_sha256'] == row['skill_file_sha256']
                    and request['session_id'] == expected
                    and request['native_session_id'].startswith(namespace + ':')
                    and isinstance(request['task_id'], str) and 0 < len(request['task_id']) <= 256,
                    'candidate_skill_sync_identity_mismatch')
                context = self.factory.api('/v1/skill-contexts', {
                    'schema_version': 'local-skill-execution-context-issue/v1',
                    'instance_id': self.factory.instance_id, 'session_id': expected,
                    'task_id': request['task_id'], 'install_id': row['install_id'], 'ttl_seconds': 600,
                    'actor_id': 'research-permissions-operator', 'confirm_issue': True}, expected=201)
                business.api.require(context['authority']['grant_id'] == row['grant_id'],
                                     'candidate_skill_context_grant_mismatch')
                request_sha = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
                ack = {'request_sha256': request_sha, 'context_id': context['context_id']}
                write_code = ("import os,sys; fd=os.open('/tmp/siq-research-skill-sync/ack.json',"
                              "os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600); "
                              "f=os.fdopen(fd,'w');f.write(sys.argv[1]);f.close()")
                response = sandbox._run(['sandbox', 'exec', '--name', name, '--timeout', '8', '--no-tty',
                    '/opt/siq/hermes/venv/bin/python', '-c', write_code, json.dumps(ack)], timeout=12)
                business.api.require(response.returncode == 0, 'candidate_skill_context_ack_failed')
                self.sync_records.append({'request': request, 'context': context, 'business_run_id': run_id})
                return
        except Exception as exc:
            self.sync_failures.append(str(exc) if isinstance(exc, native.AuthorityProofError) or
                                      (type(exc) is RuntimeError and str(exc).startswith('candidate_')) else type(exc).__name__)

    def request(self, client, headers, body, private, result):
        stop = threading.Event()
        worker = threading.Thread(target=self._synchronize, args=(stop,), daemon=True)
        before = len(self.sync_records)
        worker.start()
        try:
            reply = super().request(client, headers, body, private, result)
        finally:
            stop.set()
            worker.join(timeout=20)
            result['skill_sync_records'] = list(self.sync_records)
            result['skill_sync_failures'] = list(self.sync_failures)
        business.api.require(not worker.is_alive() and not self.sync_failures
            and len(self.sync_records) == before + 1, 'candidate_skill_native_context_unconfirmed')
        return reply

    def exercise(self, client, headers, company, environment, private, result):
        business.BusinessScenario.exercise(self, client, headers, company, environment, private, result)
        target = self.observed_targets[-1]
        first = self.factory.api('/v1/receipts?since_seq=-1')['receipts']
        decisions = [r for r in first if r.get('record_type') == 'decision']
        business.api.require(not target.exists() and any(r.get('tool') == 'write_file'
            and r.get('reason_code') == 'grant_scope_violation' and r.get('action') == 'deny' for r in decisions),
            'candidate_skill_readonly_denial_missing')
        result['permission_phases'] = {'readonly': {'receipts': first, 'write_target_path': str(target),
            'write_target_absent': True, 'grant_id': self.factory.selected['grant_id']}}
        self.previous_rows = {row.pool_binding_run_id for row in self.rows()}
        issued = self.factory.issue_root(self.factory.installations[1])
        self.factory.api('/v1/runtime-request-issuers', {
            'schema_version': 'local-runtime-request-issuer-create/v1', 'parent_identity_id': self.factory.identity_id,
            'scope_id': self.scope, 'max_identity_seconds': 600,
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'actor_id': 'research-permissions-operator'}, expected=201)
        document = json.loads(self.root_bytes)
        document.update(runtime_identity_id=self.factory.identity_id, grant_id=self.factory.selected['grant_id'],
                        grant_revision=self.factory.grant['state_revision'], credential_path=issued['credential_path'])
        roots._private_regular(self.root_path)
        business.api.require(self.root_path.read_bytes() == self.root_bytes, 'candidate_root_changed')
        self.root_bytes = json.dumps(document).encode()
        self.root_path.write_bytes(self.root_bytes)
        roots.load(business.api.ROOT, expected_scope_id=self.scope)
        second = private / 'writer'
        second.mkdir(mode=0o700)
        marker = 'SIQ_API_' + self.scope + '_SKILL_WRITER'
        trace_marker = 'SIQ_QWEN38_TRACE_' + hashlib.sha256(marker.encode()).hexdigest()[:32]
        started = int(time.time())
        reply = self.request(client, headers, self.request_body(marker, trace_marker, company), second, result)
        self.verify_completion(marker, reply, trace_marker, started, result)
        target = self.observed_targets[-1]
        all_receipts = self.factory.api('/v1/receipts?since_seq=-1')['receipts']
        current = [r for r in all_receipts if r['receipt_id'] not in {f['receipt_id'] for f in first}]
        result['permission_phases']['write_approved'] = {'receipts': current, 'agent_id': self.factory.agent_id,
            'grant_id': self.factory.selected['grant_id'], 'output_path': str(target),
            'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None}
        result['checks']['writer_output_present'] = target.is_file() and bool(
            re.search(r'(?<![\d.])20(?:\.0+)?\s*[%％]', target.read_text()))
        for label, receipts, sync, installed in zip(('reader', 'writer'), (first, current),
                                                  self.sync_records, self.factory.installations, strict=True):
            decisions = [r for r in receipts if r.get('record_type') == 'decision']
            result['checks'][label + '_skill_attribution_verified'] = len(decisions) == 2 and all(
                r.get('agent_id') == self.factory.agent_id and r.get('matched_grant_id') == installed['grant_id']
                and r.get('skill_attribution', {}).get('context_id') == sync['context']['context_id']
                and r.get('skill_attribution', {}).get('status') == 'verified' for r in decisions)
            result['checks'][label + '_read_allowed'] = any(r.get('tool') == 'read_file'
                and r.get('action') == 'allow' for r in decisions)
        result['checks']['writer_write_allowed'] = any(r.get('tool') == 'write_file'
            and r.get('action') == 'allow' for r in current if r.get('record_type') == 'decision')
        business.api.require(all(result['checks'].values()), 'candidate_skill_pair_unconfirmed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('recovery-file', 'relay-binary', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('relay-sha256', 'helper-image-ref', 'helper-image-id', 'evidence-suffix'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--relay-port', type=int, default=47710)
    args = parser.parse_args()
    args.task = 'paired-analysis'
    os.umask(0o077)
    scenario = SkillScenario(args)
    result = {'passed': False, 'scope': 'real_business_with_evaluation_skill_synchronizer'}
    try:
        scenario.prepare()
        result = business.api.run(args.evidence_suffix, scenario=scenario)
    except Exception as exc:
        result['failure_type'] = type(exc).__name__
        if isinstance(exc, (native.AuthorityProofError, skill_image.images.CandidateImageError)):
            result['failure_code'] = str(exc)
        if scenario.factory.admin:
            try:
                scenario.factory.close()
                result['setup_cleanup'] = True
            except Exception as cleanup_error:
                result['setup_cleanup'] = False
                result['cleanup_failure_type'] = type(cleanup_error).__name__
    finally:
        result['skill_installations'] = scenario.factory.installations
        result['evaluation_sync_only'] = True
        if hasattr(scenario, 'candidate_image_record'):
            result['candidate_image'] = json.loads(scenario.candidate_image_record.read_text())
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'passed': result.get('passed') is True}))
    return 0 if result.get('passed') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
