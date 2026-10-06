"""Native installed-Skill drift: loss of runtime authority must contain the run.

This separately frozen case measures the actual coupled Grant/identity
contract. It does not reclassify the original second-tool-denial failures.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from scripts.openshell import prove_research_skill_drift as drift
from scripts.openshell import prove_research_skill_drift_authority as authority
from scripts.openshell import enterprise_data_scope

skills = drift.withdrawal.skills


def positive_prefix(records, checkpoint):
    decisions = [r for r in records if r.get('record_type') == 'decision']
    observations = [r for r in records if r.get('record_type') == 'observation']
    return (len(records) == 4 and len(decisions) == 2 and len(observations) == 2
        and [(r.get('tool'), r.get('action')) for r in decisions] == [('read_file', 'allow'), ('write_file', 'allow')]
        and decisions[-1]['tool_call_id'] == checkpoint['tool_call_id']
        and {r['decision_receipt_id'] for r in observations} == {r['receipt_id'] for r in decisions})


class ContainmentScenario(drift.DriftScenario):
    expected_status = 'failed'
    terminal_check_key = 'business_execution_failed_as_expected'
    marker_check_key = 'business_reply_reports_unconfirmed_interruption'

    def __init__(self, args):
        super().__init__(args)
        self.authority_probes = {}

    def verify_reply(self, marker, reply):
        return reply in {
            '[失败] 任务执行连接中断，无法确认完整结果。请先核对已产生的文件或操作记录。',
            '[失败] 任务执行权限或运行状态已变化，无法确认完整结果。请先核对已产生的文件或操作记录。',
        }

    def mutate(self, context):
        # The sync hook now finishes post-tool observers before waiting at the
        # next operation. Require their real receipts before changing authority.
        deadline = time.monotonic() + 20
        while True:
            records = self.factory.api('/v1/receipts?since_seq=-1')['receipts']
            if positive_prefix(records, self.checkpoint):
                self.authority_probes['positive_prefix'] = records
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('candidate_drift_positive_observation_missing')
            time.sleep(.1)
        run_id = self.sync_records[0]['business_run_id']
        directory = drift.startup.location(run_id)
        identity = skills.business.identity
        # Load the existing child reference using the owning runtime validator;
        # never issue a replacement credential or mutate the running identity.
        manifest = json.loads((directory / 'supervisor.json').read_bytes())
        prepared = identity.PreparedIdentity(directory, manifest['agentshield_identity']['record_sha256'])
        binding, _ = identity.load(prepared, run_id=run_id,
            scope=enterprise_data_scope.parse_scope(manifest['scope']),
            execution_binding=manifest['api_execution_lease'])
        skills.business.api.require(binding.runtime_identity_id == self.sync_records[0]['request']['runtime_identity_id'],
                                    'candidate_drift_child_identity_mismatch')
        credential = identity.api._credential(binding)
        self.authority_probes['before'] = authority.inspect_self(self.factory, credential)
        skills.business.api.require(self.authority_probes['before']['HTTP_status'] == 200,
                                    'candidate_drift_child_not_active_before_mutation')
        result = super().mutate(context)
        self.authority_probes['changed'] = authority.inspect_self(self.factory, credential)
        self.authority_probes['mutation_finished_unix'] = result['mutation_finished_unix']
        return result

    def exercise(self, client, headers, company, environment, private, result):
        try:
            skills.business.BusinessScenario.exercise(self, client, headers, company, environment, private, result)
            records = self.factory.api('/v1/receipts?since_seq=-1')['receipts']
            target = self.observed_targets[-1]
            probes = self.authority_probes
            finished = time.time()
            result['checks'].update({
                'complete_positive_prefix_before_mutation': positive_prefix(probes['positive_prefix'], self.checkpoint),
                'child_identity_authorized_before_drift': probes['before']['HTTP_status'] == 200,
                'child_identity_rejected_after_drift': probes['changed']['HTTP_status'] == 401
                    and probes['changed']['body'] == {'error': 'runtime_identity_required'},
                'no_later_authorized_effect': records == probes['positive_prefix'],
                'original_file_bytes_preserved': target.is_file()
                    and hashlib.sha256(target.read_bytes()).hexdigest() == self.checkpoint['file_sha256'],
                'business_finalizer_within_90_seconds': 0 <= finished - probes['mutation_finished_unix'] <= 90,
            })
            result['containment_confirmed_unix'] = finished
            result['output_path'] = str(target)
            result['output_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            result['receipts'] = records
            skills.business.api.require(all(result['checks'].values()), 'candidate_drift_containment_unconfirmed')
        finally:
            result['authority_probes'] = self.authority_probes
            result['positive_checkpoint'] = self.checkpoint
            result['authority_mutation'] = self.mutation
            result['permission_control'] = self.control
            result['claim_scope'] = 'installed_content_drift_runtime_authority_loss_and_native_containment'
            result['second_native_tool_denial_proven'] = False
            result['normal_business_completion_proven'] = False


def main():
    args = drift.arguments()
    os.umask(0o077)
    scenario = ContainmentScenario(args)
    result = {'passed': False}
    try:
        scenario.prepare()
        result = skills.business.api.run(args.evidence_suffix, scenario=scenario)
    except Exception as exc:
        result['failure_type'] = type(exc).__name__
        if scenario.factory.admin:
            try:
                scenario.factory.close()
                result['setup_cleanup'] = True
            except Exception as cleanup:
                result['cleanup_failure_type'] = type(cleanup).__name__
    finally:
        result['skill_installations'] = scenario.factory.installations
        result['evaluation_sync_only'] = True
        if hasattr(scenario, 'candidate_image_record'):
            result['candidate_image'] = json.loads(scenario.candidate_image_record.read_text())
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'passed': result.get('passed') is True}))
    return 0 if result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
