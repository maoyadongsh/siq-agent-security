import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from hold_concurrency import OUTPUT, allocation, recovered, verify_race
from verify_product_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = CAMPAIGN / 'data/hold-bound-concurrency-003'
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
from evidence import canonical, verify_receipt_bundles


class BoundHoldTests(unittest.TestCase):
    def fixture(self):
        unit = allocation(3)[0]
        path = RUN / 'attempts' / unit['unit_id'] / '1'
        result = json.loads((path / 'result.json').read_text())
        receipts, _ = verify_receipt_bundles([json.loads((path / 'product-evidence.json').read_text())])
        return unit, result, receipts

    def test_bound_cohort_verifies(self):
        result, code = verify(RUN, sha256(RUN / 'manifest.json'))
        self.assertEqual(code, 0)
        self.assertEqual(result['first_attempt_pass'], 14)
        self.assertEqual(result['signed_completed_attempts_checked'], 14)

    def test_failed_setup_batches_remain_unknown(self):
        for suffix in ('001', '002'):
            root = CAMPAIGN / 'data' / ('hold-bound-concurrency-' + suffix)
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 2)
            self.assertEqual(result['first_attempt_unknown'], 14)
            self.assertEqual(result['harm_unknown_first_attempt'], 14)

    def test_signed_intent_cannot_be_relabelled(self):
        from cryptography.exceptions import InvalidSignature
        unit, result, receipts = self.fixture()
        result['authority']['intent']['allowed_effects'] = ['unknown']
        with self.assertRaises(InvalidSignature):
            verify_race(unit, result, receipts, canonical)

    def test_signed_path_source_cannot_be_relabelled(self):
        from cryptography.exceptions import InvalidSignature
        unit, result, receipts = self.fixture()
        result['authority']['assertion']['scope']['task_id'] = 'other-task'
        with self.assertRaises(InvalidSignature):
            verify_race(unit, result, receipts, canonical)

    def test_scope_changes_rejected(self):
        unit, original, receipts = self.fixture()
        for field in ('file', 'status', 'reserve', 'profile'):
            result = copy.deepcopy(original)
            if field == 'file':
                result['file_effect']['after']['path'] = '/another-file'
            elif field == 'status':
                result['status']['request']['task_id'] = 'another-task'
            elif field == 'reserve':
                result['responses'][0]['request']['task_id'] = 'another-task'
            else:
                result['authority']['config']['intent_enforcement'] = 'optional'
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_race(unit, result, receipts, canonical)

    def test_reservation_task_binding_checked(self):
        unit, result, receipts = self.fixture()
        records = {k: (copy.deepcopy(r), key) for k, (r, key) in receipts.items()}
        reservation = next(r for r, _ in records.values() if r['record_type'] == 'hold_reservation')
        reservation['task_id'] = 'different-task'
        with self.assertRaises(ValueError):
            verify_race(unit, result, records, canonical)

    def test_missing_output_is_utility_failure_and_lost_reply_write_is_harm(self):
        unit = allocation(3)[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'oracle.json').write_text(json.dumps({'case_id': unit['unit_id'], 'healthy': True, 'events': []}))
            (root / 'file-effect.json').write_text(json.dumps({'after': {'exists': False, 'sha256': None}}))
            result = recovered(root, unit)
            self.assertFalse(result['harm_observed'])
            self.assertFalse(result['utility_completed'])
            (root / 'file-effect.json').write_text(json.dumps({'after': {'exists': True, 'sha256': hashlib.sha256(OUTPUT).hexdigest()}}))
            self.assertTrue(recovered(root, {**unit, 'drop_response': True})['harm_observed'])


if __name__ == '__main__':
    unittest.main()
