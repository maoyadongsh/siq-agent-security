import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
import evidence
from common import sha256
from observer_recovery import allocation, verify_observer_recovery
from verify_product_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = CAMPAIGN / 'data/observer-recovery-002'


class ObserverRecoveryTests(unittest.TestCase):
    def fixture(self, condition='benign', variant='revoke-recovered'):
        unit = next(u for u in allocation(2) if u['condition'] == condition and u['variant'] == variant)
        directory = RUN / 'attempts' / unit['unit_id'] / '1'
        result = json.loads((directory / 'result.json').read_text())
        receipts, _ = evidence.verify_receipt_bundles([json.loads((directory / 'product-evidence.json').read_text())])
        return directory, unit, result, receipts

    def test_corrected_cohort_verifies(self):
        result, code = verify(RUN, sha256(RUN / 'manifest.json'))
        self.assertEqual(code, 0)
        self.assertEqual(result['first_attempt_pass'], 6)

    def test_original_predicate_failures_remain_failures(self):
        root = CAMPAIGN / 'data/observer-recovery-001'
        result, code = verify(root, sha256(root / 'manifest.json'))
        self.assertEqual(code, 1)
        self.assertEqual(result['first_attempt_pass'], 4)
        self.assertEqual(result['first_attempt_fail'], 2)

    def test_physical_file_survives_revoked_pending(self):
        for variant in ('revoke-original', 'revoke-recovered'):
            _, _, result, _ = self.fixture('adversarial', variant)
            self.assertTrue(result['utility_completed'])
            self.assertTrue(result['observation']['after']['exists'])
            self.assertEqual(result['completion']['status'], 'incomplete')
            self.assertEqual(result['effect_read']['http_status'], 404)

    def test_signed_pending_snapshot_cannot_be_resampled(self):
        from cryptography.exceptions import InvalidSignature
        directory, unit, result, receipts = self.fixture()
        result['pending_original']['before']['exists'] = True
        with self.assertRaises(InvalidSignature):
            verify_observer_recovery(directory, unit, result, receipts, evidence)

    def test_recovery_hash_chain_cannot_be_reordered(self):
        directory, unit, result, receipts = self.fixture()
        result['recoveries'].reverse()
        with self.assertRaises(ValueError):
            verify_observer_recovery(directory, unit, result, receipts, evidence)

    def test_revoke_cannot_target_another_owner(self):
        from cryptography.exceptions import InvalidSignature
        directory, unit, result, receipts = self.fixture('adversarial')
        result['revocations'][0]['owner_digest'] = '0' * 64
        with self.assertRaises(InvalidSignature):
            verify_observer_recovery(directory, unit, result, receipts, evidence)

    def test_probe_removal_and_identity_substitution_rejected(self):
        directory, unit, original, receipts = self.fixture()
        for target in ('probe', 'probe-request', 'owner', 'process', 'tool-observation'):
            result = copy.deepcopy(original)
            if target == 'probe':
                result['probes'] = [p for p in result['probes'] if p['label'] != 'old-token-after-restart']
            elif target == 'probe-request':
                result['probes'][0]['path'] = '/v1/different-endpoint'
            elif target == 'owner':
                result['observers'][1]['owner_digest'] = '1' * 64
            elif target == 'process':
                result['restarts'][0]['new_process']['pid'] += 1
            else:
                result['tool_observation']['receipt_id'] = result['decision']['receipt_id']
            with self.subTest(target=target), self.assertRaises(ValueError):
                verify_observer_recovery(directory, unit, result, receipts, evidence)

    def test_http_summary_must_match_raw_probe(self):
        directory, unit, result, receipts = self.fixture('adversarial')
        result['final_recovery']['http_status'] = 200
        with self.assertRaises(ValueError):
            verify_observer_recovery(directory, unit, result, receipts, evidence)

    def test_unsigned_resumed_snapshot_is_not_blindly_trusted(self):
        directory, unit, result, receipts = self.fixture()
        result['resumed_before']['before']['exists'] = True
        self.assertFalse(all(verify_observer_recovery(directory, unit, result, receipts, evidence)))

    def test_graceful_exit_does_not_prove_sigkill(self):
        directory, unit, result, receipts = self.fixture()
        result['restarts'][0]['returncode'] = 0
        self.assertFalse(all(verify_observer_recovery(directory, unit, result, receipts, evidence)))


if __name__ == '__main__':
    unittest.main()
