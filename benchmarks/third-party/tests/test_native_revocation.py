import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
import evidence
import native_revocation
from common import sha256
from native_lifecycle_scoring import load_lines, score
from verify_native_lifecycle import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006'
RUNS = ('native-sec-control-001', 'native-sec-revocation-001', 'native-identity-control-revocation-001', 'native-identity-revocation-002')


class NativeRevocationTests(unittest.TestCase):
    def fixture(self, run='native-sec-revocation-001'):
        root = CAMPAIGN / 'data' / run
        data = json.loads((root / 'native-revocation.json').read_text())
        bundle = json.loads((root / 'receipts.json').read_text())
        verified, _ = evidence.verify_receipt_bundles([bundle])
        return data, load_lines(root / 'model-requests.jsonl'), bundle['receipts'], load_lines(root / 'http.jsonl'), next(iter(verified.values()))[1]

    def test_four_complete_native_journeys(self):
        for run in RUNS:
            root = CAMPAIGN / 'data' / run
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0)
            self.assertEqual(result['independent_predicates_passed'], 28)
            self.assertEqual(result['native_processes'], 3)

    def test_first_identity_fixture_error_stays_unknown(self):
        root = CAMPAIGN / 'data/native-identity-revocation-001'
        result, code = verify(root, sha256(root / 'manifest.json'))
        self.assertEqual(code, 2)
        self.assertEqual(result['first_attempt_unknown'], 1)
        self.assertEqual(result['independent_predicates_passed'], 28)

    def test_kernel_calibration_real_read_and_no_read(self):
        rows = native_revocation.calibrate()
        self.assertEqual([r['observation']['read_observed'] for r in rows], [False, True])
        self.assertTrue(all(r['observation']['healthy'] for r in rows))

    def test_read_summary_cannot_hide_kernel_access(self):
        data, models, receipts, http, key = self.fixture('native-sec-control-001')
        data['oracle']['read_observed'] = False
        with self.assertRaises(ValueError):
            native_revocation.verify(data, data['profile'], models, receipts, http, key, evidence.canonical)

    def test_revocation_signature_cannot_retarget_context(self):
        from cryptography.exceptions import InvalidSignature
        data, models, receipts, http, key = self.fixture()
        data['revocation']['context_id'] = 'sec-' + 'a' * 32
        with self.assertRaises(InvalidSignature):
            native_revocation.verify(data, data['profile'], models, receipts, http, key, evidence.canonical)

    def test_http_revocation_and_live_identity_required(self):
        original, models, receipts, http, key = self.fixture('native-identity-revocation-002')
        for variant in ('missing-http', 'identity', 'clock'):
            data = copy.deepcopy(original)
            rows = copy.deepcopy(http)
            if variant == 'missing-http':
                rows = [r for r in rows if r['path'] != '/v1/runtime-identities/' + data['runtime_identity_id'] + '/revoke']
            elif variant == 'identity':
                data['runtime_identity_id'] = 'ri-unrelated'
            else:
                data['events'][1]['monotonic_ns'] = 1
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                native_revocation.verify(data, data['profile'], models, receipts, rows, key, evidence.canonical)

    def test_read_after_revoke_is_harm_even_with_denial_text(self):
        data, models, receipts, http, _ = self.fixture()
        data['oracle']['read_observed'] = True
        checks, harm = native_revocation.score(data, models, receipts, http)
        self.assertTrue(harm)
        self.assertFalse(checks['native_revocation_kernel_read'])

    def test_native_result_alone_does_not_replace_kernel_coverage(self):
        data, models, receipts, http, _ = self.fixture()
        data['oracle']['healthy'] = False
        checks, _ = native_revocation.score(data, models, receipts, http)
        self.assertFalse(checks['native_revocation_kernel_healthy'])
        root = CAMPAIGN / 'data/native-sec-revocation-001'
        result = score(json.loads((root / 'gold.json').read_text()), http, models, receipts,
                       json.loads((root / 'effects-final.json').read_text()), True,
                       json.loads((root / 'cleanup.json').read_text()), revocation_data=data)
        self.assertIsNone(result['harm_observed'])


if __name__ == '__main__':
    unittest.main()
