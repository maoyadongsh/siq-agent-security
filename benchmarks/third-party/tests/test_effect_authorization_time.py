import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
import evidence
from common import sha256
from effect_authorization_time import allocation, verify_temporal
from verify_product_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006'
RUN = CAMPAIGN / 'data/effect-time-002'


class EffectTimeTests(unittest.TestCase):
    def fixture(self):
        unit = next(u for u in allocation() if u['condition'] == 'adversarial' and u['restart'] and u['variant'] == 'before-reservation')
        directory = RUN / 'attempts' / unit['unit_id'] / '1'
        result = json.loads((directory / 'result.json').read_text())
        receipts, _ = evidence.verify_receipt_bundles([json.loads((directory / 'product-evidence.json').read_text())])
        return directory, unit, result, receipts

    def test_registered_cohort_keeps_real_harm(self):
        result, code = verify(RUN, sha256(RUN / 'manifest.json'))
        self.assertEqual(code, 0)
        self.assertEqual(result['first_attempt_pass'], 8)
        self.assertEqual(result['known_harm_first_attempt'], 4)

    def test_setup_failure_cohort_preserved(self):
        root = CAMPAIGN / 'data/effect-time-001'
        result, code = verify(root, sha256(root / 'manifest.json'))
        self.assertEqual(code, 2)
        self.assertEqual(result['first_attempt_unknown'], 8)
        self.assertEqual(result['known_harm_first_attempt'], 2)

    def test_receiver_time_cannot_be_shifted_after_reservation(self):
        directory, unit, result, receipts = self.fixture()
        result['observation']['events'][0]['received_at'] = '2099-01-01T00:00:00Z'
        with self.assertRaises(ValueError):
            verify_temporal(directory, unit, result, receipts, evidence)

    def test_effect_cannot_be_relabelled_authorized(self):
        from cryptography.exceptions import InvalidSignature
        directory, unit, result, receipts = self.fixture()
        result['product_observer']['finding_code'] = ''
        with self.assertRaises(InvalidSignature):
            verify_temporal(directory, unit, result, receipts, evidence)

    def test_cross_action_reservation_rejected(self):
        directory, unit, result, receipts = self.fixture()
        result['reserve_request']['decision_receipt_id'] = 'different-decision'
        with self.assertRaises(ValueError):
            verify_temporal(directory, unit, result, receipts, evidence)

    def test_declared_stage_and_process_cannot_be_relabelled(self):
        directory, unit, original, receipts = self.fixture()
        for mutation in ('phase', 'process', 'mode'):
            result = copy.deepcopy(original)
            if mutation == 'phase':
                result['events'][1]['event'] = 'delivery_returned'
            elif mutation == 'process':
                result['restart']['old_process']['pid'] += 1
            else:
                result['authority']['config']['intent_enforcement'] = 'optional'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify_temporal(directory, unit, result, receipts, evidence)

    def test_delivery_time_is_recorded_by_handler(self):
        directory, unit, result, receipts = self.fixture()
        delivery = next(e for e in result['events'] if e['event'] == 'delivery_returned')
        result['observation']['events'][0]['monotonic_ns'] = delivery['monotonic_ns'] + 1
        with self.assertRaises(ValueError):
            verify_temporal(directory, unit, result, receipts, evidence)


if __name__ == '__main__':
    unittest.main()
