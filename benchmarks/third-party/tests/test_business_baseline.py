import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from business_chain_baseline import baseline
from business_chain_trial import load_benchmark

CANDIDATE = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006/private/candidates/5470ab3780f2-fixturefix2'


class BaselineSeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark = load_benchmark(CANDIDATE)

    def test_original_business_methods_and_restore(self):
        from secure_agent import application
        original = application.TaskAuthority
        run = application.SecureApplication.run
        tools = application.ToolAdapters
        audit = {}
        with baseline(self.benchmark, audit):
            self.assertIs(application.SecureApplication.run, run)
            self.assertIs(application.ToolAdapters, tools)
            self.assertIs(application.TaskAuthority.approved_url, original.approved_url)
            self.assertIs(application.TaskAuthority.directory_result, original.directory_result)
        self.assertIs(application.TaskAuthority, original)

    def test_no_siq_http_can_sneak_into_b0(self):
        from secure_agent.security import JsonAPI
        audit = {}
        with baseline(self.benchmark, audit), self.assertRaises(AssertionError):
            JsonAPI('http://127.0.0.1:1', 'test-only').request('/v1/decide', {})
        self.assertEqual(audit['forbidden_security_requests'], ['/v1/decide'])

    def test_dispatch_has_no_fabricated_allow_or_receipt(self):
        from secure_agent import application
        from secure_agent.contracts import TaskState
        observed = []
        state = TaskState('test', 'test', 'fixture')
        def executor(params, token):
            observed.append(token)
            return {'success': True}
        with baseline(self.benchmark, {}):
            gateway = application.ToolGateway(None, {'write_file': executor}, state)
            result = gateway.call('write_file', {'path': 'synthetic'})
        self.assertTrue(result.value['success'])
        self.assertNotIn('action', observed[0])
        self.assertIsNone(observed[0]['receipt_id'])
        self.assertIsNone(state.actions[0]['decision'])
        self.assertTrue(observed[0]['action_id'].startswith('b0-dispatch-'))


if __name__ == '__main__':
    unittest.main()
