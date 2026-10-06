"""Run under frozen AgentDojo environment; no model calls or product daemon."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.task_suite.task_suite import (
    functions_stack_trace_from_messages,
    model_output_from_messages,
)
from agentdojo_snapshot import restore_workspace


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.suite = get_suite('v1.2.2', 'workspace')
        self.runtime = FunctionsRuntime(self.suite.tools)

    def restore(self, env):
        return restore_workspace(self.suite.environment_type, json.loads(env.model_dump_json()))

    def test_all_twenty_reference_tasks_keep_utility(self):
        for n in (0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 14, 16, 17, 22, 24, 26, 27, 28, 30, 35):
            with self.subTest(task=n):
                task = self.suite.get_user_task_by_id(f'user_task_{n}')
                before = task.init_environment(self.suite.load_and_inject_default_environment({}))
                _, _, after, messages, _ = GroundTruthPipeline(task).query(task.PROMPT, self.runtime, before.model_copy(deep=True), [], {})
                restored = self.restore(after)
                self.assertEqual(restored.model_dump(mode='json'), after.model_dump(mode='json'))
                self.assertTrue(self.suite._check_user_task_utility(task, model_output_from_messages(messages), self.restore(before), restored, functions_stack_trace_from_messages(messages)))

    def test_actual_target_email_harm_cannot_disappear(self):
        task = self.suite.get_injection_task_by_id('injection_task_0')
        before = self.suite.load_and_inject_default_environment({})
        _, _, after, messages, _ = GroundTruthPipeline(task).query(task.GOAL, self.runtime, before.model_copy(deep=True), [], {})
        # Demonstrate the old loading error on this same positive harm control.
        wrong = self.suite.environment_type.model_validate_json(after.model_dump_json())
        trace = functions_stack_trace_from_messages(messages)
        out = model_output_from_messages(messages)
        self.assertFalse(self.suite._check_injection_task_security(task, out, before, wrong, trace))
        self.assertTrue(self.suite._check_injection_task_security(task, out, self.restore(before), self.restore(after), trace))

    def test_read_delete_and_new_file_mutations_survive(self):
        env = self.suite.load_and_inject_default_environment({})
        for name, args in [('get_unread_emails', {}), ('delete_email', {'email_id': '1'}),
                           ('create_file', {'filename': 'snapshot.txt', 'content': 'synthetic snapshot'}),
                           ('delete_file', {'file_id': '1'})]:
            self.runtime.run_function(env, name, args, raise_on_error=True)
        restored = self.restore(env)
        self.assertNotIn('1', restored.inbox.emails)
        self.assertIn('1', restored.inbox.trash)
        self.assertNotIn('1', restored.cloud_drive.files)
        self.assertEqual(restored.model_dump(mode='json'), env.model_dump(mode='json'))

    def test_missing_mutable_map_fails_instead_of_using_seed(self):
        env = self.suite.load_and_inject_default_environment({}).model_dump(mode='json')
        del env['inbox']['emails']
        with self.assertRaises(ValueError):
            restore_workspace(self.suite.environment_type, env)

    def test_forged_computed_field_rejected(self):
        env = self.suite.load_and_inject_default_environment({}).model_dump(mode='json')
        env['inbox']['sent'] = []
        with self.assertRaises(ValueError):
            restore_workspace(self.suite.environment_type, env)


if __name__ == '__main__':
    unittest.main()
