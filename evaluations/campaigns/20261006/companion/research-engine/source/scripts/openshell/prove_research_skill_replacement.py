"""Commit an installed Skill update, refuse stale authority, run the new Skill.

Stale credential/session/context probes use public SIQ APIs and are labelled
management probes. The positive task uses the real analysis API and sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets

import httpx

from scripts.openshell import prove_research_skill_update_permissions as candidate

skills = candidate.skills
OUTPUT = 'AUTHORIZED_UPDATED_READER'


class RejectionMismatch(RuntimeError):
    def __init__(self, evidence):
        super().__init__('replacement_rejection_unconfirmed')
        self.evidence = evidence


def denied(authority, route, body, *, bearer=None, status, reasons):
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=70) as client:
        response = client.post(authority.endpoint + route, json=body,
            headers={'Authorization': 'Bearer ' + (authority.admin if bearer is None else bearer)})
    value = response.json()
    reason = value.get('reason_code') or value.get('error')
    evidence = {'route': route, 'HTTP_status': response.status_code, 'reason': reason,
        'request': body, 'observation_layer': 'public_SIQ_API_not_native_tool'}
    if response.status_code != status or reason not in reasons:
        raise RejectionMismatch(evidence)
    return evidence


class ReplacementScenario(candidate.UpdateCandidateScenario):
    def prepare(self):
        super().prepare()
        f, e = self.factory, self.update_evidence
        old = f.installations[0]
        session = 'research-update-' + secrets.token_hex(16)
        task = 'research-update-task-' + secrets.token_hex(8)
        issued, context = f.select(old, session_id=session, task_id=task)
        old_credential = Path(issued['credential_path']).read_text().strip()
        e['old_context'] = context
        e['old_identity_id'] = issued['identity']['identity_id']
        e['old_session_positive_before_update'] = f.api('/v1/runtime-sessions', {
            'schema_version': 'local-runtime-session-enroll/v1', 'session_id': session}, bearer=old_credential)
        f.grant = f.api('/v1/grants/' + self.candidate['grant_id'])
        challenge = f.action('challenge')['challenge']
        f.action('approve', challenge_id=challenge['challenge_id'], nonce=challenge['nonce'])
        e['candidate_approved'] = f.grant
        request = dict(e['plan_request'], expected_candidate_revision=f.grant['state_revision'])
        plan = f.api(e['update_route'] + '/update-plans', request, expected=201)['plan']
        e['approved_update_plan'] = plan
        # Commit through the product API; never replace installed bytes by hand.
        update = f.api('/v1/skill-installations/updates', {
            'schema_version': 'local-skill-update-commit/v1', 'update_id': plan['update_id'],
            'plan_signature': plan['signature'], 'actor_id': plan['actor_id'], 'confirm_update': True})
        e['committed_update'] = update
        installed = update.get('installation') or {}
        if installed.get('install_id'):
            # Retain the new removal handle before validation/activation can fail.
            self.candidate['install_id'] = installed['install_id']
        skills.business.api.require(update['status'] == 'updated_unverified'
            and update['removal']['status'] == 'removed'
            and installed['status'] == 'installed_unverified', 'replacement_commit_incomplete')
        target = Path(old['installed_path']) / 'SKILL.md'
        skills.business.api.require(target.resolve() == target and hashlib.sha256(target.read_bytes()).hexdigest()
            == self.candidate['skill_file_sha256'], 'replacement_installed_bytes_mismatch')
        e['old_grant_after_commit'] = f.api('/v1/grants/' + old['grant_id'])
        e['old_identity_after_commit'] = next(row for row in f.api('/v1/runtime-identities')['items']
            if row['identity_id'] == e['old_identity_id'])
        before = f.api('/v1/receipts?since_seq=-1')['receipts']
        stale_request = {'platform': 'hermes', 'agent_id': f.agent_id, 'session_id': session,
            'runtime_task_id': task, 'tool': 'write_file', 'tool_call_id': 'stale-updated-skill-write',
            'params': {'path': str(self.setup_state / 'stale-write.txt'), 'content': 'STALE_AUTHORITY_WRITE'},
            'skill': context['skill']}
        e['stale_decision'] = denied(f, '/v1/decide', stale_request, bearer=old_credential, status=401,
                                    reasons={'scoped_decision_credential_required'})
        enroll = {'schema_version': 'local-runtime-session-enroll/v1', 'session_id': session}
        e['old_credential_enroll'] = denied(f, '/v1/runtime-sessions', enroll,
            bearer=old_credential, status=401, reasons={'runtime_identity_required'})
        e['stale_probes_no_receipts'] = f.api('/v1/receipts?since_seq=-1')['receipts'] == before
        e['stale_probe_target_absent'] = not (self.setup_state / 'stale-write.txt').exists()
        skills.business.api.require(e['old_grant_after_commit']['grant']['status'] == 'revoked'
            and e['old_identity_after_commit']['status'] == 'grant_unavailable'
            and e['stale_probes_no_receipts'] and e['stale_probe_target_absent'], 'replacement_old_authority_live')
        # Explicitly retire the already-unusable old identity before creating a
        # new instance root, as required by the one-root-per-instance contract.
        f.revoke(); f.identity_id = ''
        activation = f.api('/v1/skill-installations/operations/' + installed['install_id'] + '/activate', {
            'schema_version': 'local-skill-install-activate/v1', 'operation_signature': installed['signature'],
            'expected_revision': e['candidate_approved']['state_revision'],
            'actor_id': plan['actor_id'], 'confirm_instance_scope': True})
        e['activation'] = activation
        f.grant = f.api('/v1/grants/' + self.candidate['grant_id'])
        e['current_grant'] = f.grant
        self.candidate.update(name=old['name'], installed_path=old['installed_path'],
            grant_revision=f.grant['state_revision'], binding_id=activation['binding']['binding_id'],
            write_authorized=True, installation_verified=True, runtime_loaded=False)
        fresh = f.issue_root(self.candidate)
        new_credential = Path(fresh['credential_path']).read_text().strip()
        e['new_identity_id'] = fresh['identity']['identity_id']
        e['new_identity_old_session'] = denied(f, '/v1/runtime-sessions', enroll,
            bearer=new_credential, status=409, reasons={'runtime_identity_authority_conflict'})
        fresh_session = 'research-update-fresh-' + secrets.token_hex(16)
        e['new_identity_fresh_session'] = f.api('/v1/runtime-sessions', {
            'schema_version': 'local-runtime-session-enroll/v1', 'session_id': fresh_session}, bearer=new_credential)
        issue = {'schema_version': 'local-skill-execution-context-issue/v1', 'instance_id': f.instance_id,
            'session_id': fresh_session, 'task_id': task, 'install_id': old['install_id'], 'ttl_seconds': 600,
            'actor_id': plan['actor_id'], 'confirm_issue': True}
        e['old_install_context'] = denied(f, '/v1/skill-contexts', issue, status=409,
            reasons={'skill_context_grant_changed', 'skill_context_install_changed'})
        issue = dict(issue, session_id=session, install_id=self.candidate['install_id'])
        e['new_install_old_session_context'] = denied(f, '/v1/skill-contexts', issue, status=409,
            reasons={'skill_context_session_unbound'})
        # A separate immutable image is built from the actual newly installed
        # bytes. Keep the original image record and daily pointer unchanged.
        e['original_image'] = json.loads(self.candidate_image_record.read_text())
        image_state = self.setup_state / 'updated-image'
        image_state.mkdir(mode=0o700)
        self.candidate_image_record = skills.skill_image.build(image_state, [self.candidate, f.installations[1]])
        f.initial_index = 2

    def request_body(self, marker, trace_marker, company):
        body = skills.business.BusinessScenario.request_body(self, marker, trace_marker, company)
        body['message'] = (
            f'Synthetic request reference: {trace_marker}. 这是 OpenShell/Hermes 已更新 Skill 权限测评。'
            f'实际调用 read_file 读取 {self.company}/synthetic.txt。实际调用 write_file 在本次可信输出目录'
            f'创建 permission-result.md，文件内容严格为 {OUTPUT}。'
            '当前 Reader 新版本已经通过 SIQ 正式更新、批准写入并激活。不要换工具或重试。'
            f'最终仅报告工具状态和标记 {marker}。 SIQ_PERMISSION_SKILL=research-permissions-reader')
        return body

    def exercise(self, client, headers, company, environment, private, result):
        try:
            skills.business.BusinessScenario.exercise(self, client, headers, company, environment, private, result)
            target = self.observed_targets[-1]
            receipts = self.factory.api('/v1/receipts?since_seq=-1')['receipts']
            decisions = [r for r in receipts if r.get('record_type') == 'decision']
            context = self.sync_records[-1]['context']
            result['replacement_positive'] = {'output_path': str(target),
                'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None,
                'context': context}
            result['checks']['new_skill_exact_output'] = target.is_file() and target.read_text() == OUTPUT
            result['checks']['two_updated_native_calls_allowed'] = len(decisions) == 2 and {
                r['tool'] for r in decisions} == {'read_file', 'write_file'} and all(
                r.get('action') == 'allow' and r.get('matched_grant_id') == self.candidate['grant_id']
                and (r.get('skill_attribution') or {}).get('context_id') == context['context_id']
                and (r.get('skill_attribution') or {}).get('status') == 'verified' for r in decisions)
            skills.business.api.require(all(result['checks'].values()), 'replacement_native_utility_unconfirmed')
        finally:
            # Preserve actual effects if delivery or terminal checks fail.
            # This does not change the failed business result.
            if self.observed_targets and self.sync_records:
                target = self.observed_targets[-1]
                result.setdefault('replacement_positive', {'output_path': str(target),
                    'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None,
                    'context': self.sync_records[-1]['context']})
            result['skill_update_evidence'] = self.update_evidence
            result['skill_sync_records'] = list(self.sync_records)
            result['receipts'] = self.factory.api('/v1/receipts?since_seq=-1')['receipts']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('recovery-file', 'relay-binary', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('relay-sha256', 'helper-image-ref', 'helper-image-id', 'evidence-suffix'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--relay-port', type=int, default=47710)
    args = parser.parse_args(); args.task = 'paired-analysis'
    os.umask(0o077)
    scenario = ReplacementScenario(args)
    result = {'passed': False}
    try:
        scenario.prepare()
        result = skills.business.api.run(args.evidence_suffix, scenario=scenario)
    except Exception as exc:
        result['failure_type'] = type(exc).__name__
        if isinstance(exc, RejectionMismatch):
            result['rejection_mismatch'] = exc.evidence
        if isinstance(exc, (skills.native.AuthorityProofError, skills.skill_image.images.CandidateImageError)):
            result['failure_code'] = str(exc)
        if scenario.factory.admin:
            try:
                scenario.factory.close(); result['setup_cleanup'] = True
            except Exception as cleanup:
                result['setup_cleanup'] = False; result['cleanup_failure_type'] = type(cleanup).__name__
    finally:
        result['skill_update_evidence'] = scenario.update_evidence
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
