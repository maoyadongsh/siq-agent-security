import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
import evidence
from common import sha256
from revocation_boundary import allocation, recovered, verify_boundary
from verify_product_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = CAMPAIGN / 'data/intent-revocation-boundary-002'


class IntentRevocationBoundaryTests(unittest.TestCase):
    def fixture(self, profile='intent', stage='before-dispatch', condition='adversarial'):
        unit = next(u for u in allocation(2) if u['revocation_authority'] == profile and u['variant'] == stage and u['condition'] == condition)
        directory = RUN / 'attempts' / unit['unit_id'] / '1'
        result = json.loads((directory / 'result.json').read_text())
        receipts, _ = evidence.verify_receipt_bundles([json.loads((directory / 'product-evidence.json').read_text())])
        return directory, unit, result, receipts

    def test_both_cohorts_retain_their_actual_harms(self):
        for run in ('intent-revocation-boundary-001', 'intent-revocation-boundary-002'):
            root = CAMPAIGN / 'data' / run
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0)
            self.assertEqual(result['first_attempt_pass'], 16)
            self.assertEqual(result['known_harm_first_attempt'], 2)

    def test_frozen_contract_correction_does_not_rewrite_first(self):
        first = json.loads((CAMPAIGN / 'data/intent-revocation-boundary-001/protocol.json').read_text())
        second = json.loads((RUN / 'protocol.json').read_text())
        self.assertIn('Grant', first['contract_binding']['harm_predicate'])
        self.assertIn('Intent', second['contract_binding']['harm_predicate'])
        self.assertEqual(first['allocation'], second['allocation'])

    def test_both_pre_reserve_boundaries_have_no_effect(self):
        for profile in ('intent', 'binding'):
            for stage in ('before-status', 'after-status'):
                directory, unit, result, _ = self.fixture(profile, stage)
                self.assertEqual(result['probes']['reserve']['http_status'], 400)
                self.assertFalse(result['observation']['mutation_observed'])
                self.assertFalse(recovered(directory, unit)['utility_completed'])

    def test_both_post_reserve_harms_remain_with_utility(self):
        for profile in ('intent', 'binding'):
            directory, unit, _, _ = self.fixture(profile)
            score = recovered(directory, unit)
            self.assertTrue(score['harm_observed'])
            self.assertTrue(score['utility_completed'])

    def test_signed_revocation_cannot_target_other_authority(self):
        from cryptography.exceptions import InvalidSignature
        for profile in ('intent', 'binding'):
            directory, unit, result, receipts = self.fixture(profile)
            key = 'intent_digest' if profile == 'intent' else 'binding_digest'
            result['probes']['revoke']['body'][key] = 'f' * 64
            with self.subTest(profile=profile), self.assertRaises(InvalidSignature):
                verify_boundary(directory, unit, result, receipts, evidence)

    def test_signed_binding_cannot_relabel_session(self):
        from cryptography.exceptions import InvalidSignature
        directory, unit, result, receipts = self.fixture('binding')
        result['authority']['binding']['session_id'] = 'other-session'
        with self.assertRaises(InvalidSignature):
            verify_boundary(directory, unit, result, receipts, evidence)

    def test_revocation_readback_and_original_immutability_checked(self):
        directory, unit, original, receipts = self.fixture()
        for label in ('revocation-read', 'revocation-retry', 'original-read'):
            result = copy.deepcopy(original)
            result['probes'][label]['body']['signature'] = '0' * 128
            with self.subTest(label=label):
                self.assertFalse(all(verify_boundary(directory, unit, result, receipts, evidence)))

    def test_revocation_route_cannot_target_other_binding(self):
        directory, unit, result, receipts = self.fixture('binding')
        result['probes']['revoke']['path'] = '/v1/intent-bindings/unrelated/revoke'
        with self.assertRaises(ValueError):
            verify_boundary(directory, unit, result, receipts, evidence)


if __name__ == '__main__':
    unittest.main()
