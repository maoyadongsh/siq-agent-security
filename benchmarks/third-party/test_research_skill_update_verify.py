"""Effect and authority substitution negatives for native update phases."""
import copy
import hashlib
import unittest

from research_skill_update_verify import canonical, phase_checks, resource_ref


class UpdatePhaseTests(unittest.TestCase):
    def setUp(self):
        self.context = {'authority': {'grant_id': 'original'}, 'context_id': 'sec-original',
                        'subject': {'agent_id': 'agent', 'session_id': 'session', 'task_id': 'task'}}
        common = {'matched_grant_id': 'original', 'agent_id': 'agent', 'session_id': 'session',
            'runtime_task_id': 'task', 'record_type': 'decision',
            'skill_attribution': {'context_id': 'sec-original', 'status': 'verified'}}
        read = dict(common, tool='read_file', resource_refs=resource_ref('/owned/input'), receipt_id='read',
                    action='allow', effective_action='allow', action_id='a', tool_call_id='read-call')
        write = dict(common, tool='write_file', resource_refs=resource_ref('/owned/output'), receipt_id='write',
            action='deny', effective_action='deny', reason_code='grant_scope_violation',
            params_digest=hashlib.sha256(canonical({'path': '/owned/output', 'content': 'CANDIDATE_WRITE_ATTEMPT'})).hexdigest())
        observed = dict(read, record_type='observation', receipt_id='obs', decision_receipt_id='read')
        self.records = [read, observed, write]

    def review(self, records=None, context=None, **kwargs):
        return phase_checks(records or self.records, context or self.context,
            input_path='/owned/input', output_path=kwargs.get('output_path', '/owned/output'),
            output_exists=kwargs.get('output_exists', False))

    def test_consistent_original_authority_and_no_effect(self):
        self.assertTrue(all(self.review().values()))

    def test_unauthorized_effect_or_wrong_target_fails(self):
        self.assertFalse(self.review(output_exists=True)['actual_output_absent'])
        self.assertFalse(self.review(output_path='/other')['native_write_scope_deny'])

    def test_candidate_grant_cannot_replace_current_context(self):
        changed = copy.deepcopy(self.context); changed['authority']['grant_id'] = 'candidate'
        self.assertFalse(self.review(context=changed)['same_installed_authority'])

    def test_missing_observation_or_allowed_write_fails(self):
        self.assertFalse(self.review(records=[self.records[0], self.records[2]])['read_observation_linked'])
        changed = copy.deepcopy(self.records); changed[-1].update(action='allow', effective_action='allow')
        self.assertFalse(self.review(records=changed)['native_write_scope_deny'])


if __name__ == '__main__':
    unittest.main()
