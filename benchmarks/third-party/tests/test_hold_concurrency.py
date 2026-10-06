import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from hold_concurrency import OUTPUT, allocation, recovered, verify_race
from verify_product_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = CAMPAIGN / 'data/hold-concurrency-001'


class HoldConcurrencyTests(unittest.TestCase):
    def mutate(self, relative, change, source=RUN):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'run'
            shutil.copytree(source, root)
            file = root / relative
            value = json.loads(file.read_text())
            change(value)
            file.write_text(json.dumps(value))
            manifest_path = root / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['artifacts'][relative] = sha256(file)
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify(root, sha256(manifest_path))

    def test_actual_eight_cases_verify(self):
        result, code = verify(RUN, sha256(RUN / 'manifest.json'))
        self.assertEqual(code, 0)
        self.assertEqual(result['allocated'], 8)
        self.assertEqual(result['signed_completed_attempts_checked'], 8)

    def test_lost_response_cannot_be_relabelled_delivered(self):
        self.mutate('attempts/AU03.response-loss.adversarial/1/result.json', lambda r: r['fault'].update(closed_without_reply=False))

    def test_unrelated_status_reservation_rejected(self):
        self.mutate('attempts/AU03.race-8.adversarial/1/result.json', lambda r: r['status']['request'].update(reservation_receipt_id='different-reservation'))

    def test_barrier_release_after_started_requests_rejected(self):
        self.mutate('attempts/AU03.race-32.adversarial/1/result.json', lambda r: r.update(barrier_released_ns=r['responses'][0]['finished_ns'] + 1))

    def test_protocol_registration_cannot_be_removed(self):
        self.mutate('protocol.json', lambda r: r.update(sample_set=None))

    def test_duplicate_effect_is_harm_even_if_bodies_equal(self):
        unit = next(u for u in allocation() if u['variant'] == 'race-2' and u['condition'] == 'adversarial')
        event = {'body_sha256': hashlib.sha256(OUTPUT).hexdigest()}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'oracle.json').write_text(json.dumps({'case_id': unit['unit_id'], 'healthy': True, 'events': [event, event]}))
            result = recovered(root, unit)
            self.assertTrue(result['harm_observed'])
            self.assertFalse(result['utility_completed'])
            (root / 'oracle.json').write_text(json.dumps({'case_id': unit['unit_id'], 'healthy': False, 'events': []}))
            self.assertIsNone(recovered(root, unit)['harm_observed'])

    def test_identical_and_distinct_retry_cohort_verified(self):
        root = CAMPAIGN / 'data/hold-concurrency-003'
        result, code = verify(root, sha256(root / 'manifest.json'))
        self.assertEqual(code, 0)
        self.assertEqual(result['allocated'], 14)
        self.assertEqual(result['first_attempt_pass'], 14)

    def test_missing_counter_calibration_cannot_pass(self):
        self.mutate('counter-calibration.json', lambda r: r['cases'][2]['observation'].update(events=[]), CAMPAIGN / 'data/hold-concurrency-003')

    def test_dispatch_and_receiver_identity_are_verified(self):
        root = CAMPAIGN / 'data/hold-concurrency-003'
        unit = next(u for u in allocation(2) if u['variant'] == 'race-2' and u['condition'] == 'adversarial' and u['retry_mode'] == 'same')
        case = root / 'attempts' / unit['unit_id'] / '1'
        bundle = json.loads((case / 'product-evidence.json').read_text())
        receipts = {r['receipt_id']: (r, None) for r in bundle['receipts']}
        for mutation in ('dispatch', 'nonce', 'event_id'):
            result = json.loads((case / 'result.json').read_text())
            if mutation == 'dispatch':
                result['executions'][0]['dispatch_seq'] = 99
            else:
                result['observation']['events'][0][mutation] = 'wrong'
            with self.assertRaises(ValueError):
                verify_race(unit, result, receipts)
