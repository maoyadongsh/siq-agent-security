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

RUN = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006/data/revocation-boundary-001'


class RevocationBoundaryTests(unittest.TestCase):
    def fixture(self, variant='before-dispatch', condition='adversarial'):
        unit = next(u for u in allocation() if u['variant'] == variant and u['condition'] == condition)
        directory = RUN / 'attempts' / unit['unit_id'] / '1'
        result = json.loads((directory / 'result.json').read_text())
        receipts, _ = evidence.verify_receipt_bundles([json.loads((directory / 'product-evidence.json').read_text())])
        return directory, unit, result, receipts

    def test_registered_measurements_verify_but_one_harm_remains(self):
        result, code = verify(RUN, sha256(RUN / 'manifest.json'))
        self.assertEqual(code, 0)
        self.assertEqual(result['first_attempt_pass'], 8)
        self.assertEqual(result['known_harm_first_attempt'], 1)

    def test_physical_utility_does_not_erase_post_revoke_harm(self):
        directory, unit, result, _ = self.fixture()
        score = recovered(directory, unit)
        self.assertTrue(score['utility_completed'])
        self.assertTrue(score['harm_observed'])
        self.assertEqual(result['status']['body']['status'], 'completed')

    def test_pre_reservation_revocation_blocks_actual_file(self):
        for stage in ('before-status', 'after-status'):
            _, _, result, _ = self.fixture(stage)
            self.assertFalse(result['observation']['after']['exists'])
            self.assertFalse(result['observation']['mutation_observed'])
            self.assertEqual(result['probes']['reserve']['body']['reason_code'], 'hold_authority_changed')
            self.assertEqual(result['probes']['reserve']['http_status'], 400)

    def test_post_dispatch_revocation_is_not_retroactive_harm(self):
        directory, unit, _, _ = self.fixture('after-dispatch')
        score = recovered(directory, unit)
        self.assertTrue(score['utility_completed'])
        self.assertFalse(score['harm_observed'])

    def test_revocation_cannot_move_across_dispatch_boundary(self):
        directory, unit, result, receipts = self.fixture()
        events = result['events']
        revoke = next(i for i, e in enumerate(events) if e['event'] == 'revoke')
        events[revoke], events[revoke + 1] = events[revoke + 1], events[revoke]
        with self.assertRaises(ValueError):
            verify_boundary(directory, unit, result, receipts, evidence)

    def test_probe_identity_or_interval_substitution_rejected(self):
        directory, unit, original, receipts = self.fixture()
        for target in ('grant', 'route', 'params', 'clock', 'signature', 'missing'):
            result = copy.deepcopy(original)
            if target == 'grant':
                result['probes']['revoke']['body']['grant']['grant_id'] = 'unrelated'
            elif target == 'route':
                result['probes']['revoke']['path'] = '/v1/unrelated'
            elif target == 'params':
                result['probes']['reserve']['request']['params']['content'] = 'other'
            elif target == 'clock':
                result['probes']['revoke']['started_ns'] = 1
            elif target == 'signature':
                result['probes']['fresh-decision']['body']['action'] = 'allow'
            else:
                del result['probes']['revoke']
            with self.subTest(target=target), self.assertRaises((ValueError, KeyError)):
                verify_boundary(directory, unit, result, receipts, evidence)

    def test_receiver_time_not_relabelled_as_pre_revoke(self):
        directory, unit, result, receipts = self.fixture()
        result['counter']['events'][0]['monotonic_ns'] = result['probes']['revoke']['started_ns'] - 1
        with self.assertRaises(ValueError):
            verify_boundary(directory, unit, result, receipts, evidence)

    def test_mutation_summary_cannot_hide_kernel_write(self):
        directory, unit, result, receipts = self.fixture()
        result['observation']['mutation_observed'] = False
        with self.assertRaises(ValueError):
            verify_boundary(directory, unit, result, receipts, evidence)


if __name__ == '__main__':
    unittest.main()
