import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("journey", Path(__file__).with_name("openshell-b3-candidate-journey.py"))
journey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journey)

class ScopeTests(unittest.TestCase):
    def test_legacy_or_overclaiming_response_rejected(self):
        for response in ({}, {"scope": None, "task_executed": None}, {"scope": "policy_apply", "task_executed": True}, {"scope": "policy_apply", "task_executed": 0}):
            with self.subTest(response=response), self.assertRaises(journey.StepFailure):
                journey.require_policy_apply_response(response)

    def test_explicit_policy_only_response_accepted(self):
        journey.require_policy_apply_response({"scope": "policy_apply", "task_executed": False})

class NegativeJourneyTests(unittest.TestCase):
    def fixture(self, action, after):
        j = object.__new__(journey.Journey)
        j.policy_read_revision = '1'
        j.grant_id = j.grant_digest = j.fingerprint = 'fixture'
        j.expected_revision = '1'
        j.binary_paths = ['/usr/bin/python3']
        j.build_params = lambda *args: {}
        j.decide = lambda *args: {'action': action}
        j.record = lambda *args: None
        def read(*args):
            j.policy_read_revision = after
            return {'revision': after}
        j.policy_read = read
        return j

    def test_denied_operation_must_not_change_revision(self):
        with self.assertRaises(journey.StepFailure):
            self.fixture('deny', '2').leg_j60()

    def test_allow_is_not_a_denial(self):
        with self.assertRaises(journey.StepFailure):
            self.fixture('allow', '1').leg_j60()

    def test_unchanged_denial_passes(self):
        self.fixture('deny', '1').leg_j60()
