import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
import evidence
import native_held_intent
import native_hold_boundary
from common import canonical, sha256
from native_lifecycle_scoring import load_lines
from verify_native_lifecycle import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006'
RUNS = tuple(f'native-held-{kind}-{profile}-001' for kind in ('intent', 'binding') for profile in native_hold_boundary.PROFILES)


class NativeHeldIntentTests(unittest.TestCase):
    def fixture(self, kind='intent', profile='after-reserve'):
        root = CAMPAIGN / 'data' / f'native-held-{kind}-{profile}-001'
        data = json.loads((root / 'native-hold-boundary.json').read_text())
        bundle = json.loads((root / 'receipts.json').read_text())
        signed, _ = evidence.verify_receipt_bundles([bundle])
        return data, load_lines(root / 'model-requests.jsonl'), bundle['receipts'], load_lines(root / 'http.jsonl'), next(iter(signed.values()))[1]

    def test_sixteen_native_journeys_keep_two_real_harms(self):
        harms = 0
        for name in RUNS:
            root = CAMPAIGN / 'data' / name
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0)
            self.assertEqual(result['independent_predicates_passed'], 30)
            self.assertEqual(result['native_processes'], 3)
            harms += result['known_harm_first_attempt']
        self.assertEqual(harms, 2)

    def test_actual_chinese_intent_requires_product_canonical_bytes(self):
        from cryptography.exceptions import InvalidSignature
        data, _, _, _, key = self.fixture()
        signed = data['authority_subject']['intent']
        self.assertTrue(any(ord(c) > 127 for c in signed['purpose']))
        payload = {k: v for k, v in signed.items() if k != 'signature'}
        with self.assertRaises(InvalidSignature):
            key.verify(bytes.fromhex(signed['signature']), canonical(payload))
        key.verify(bytes.fromhex(signed['signature']), native_held_intent.signed_canonical(payload))
        unsigned = {k: v for k, v in payload.items() if k != 'digest'}
        self.assertEqual(hashlib.sha256(native_held_intent.signed_canonical(unsigned)).hexdigest(), signed['digest'])
        # These controlled string parameters use Go json.Marshal, not signature canonicalization.
        params = {'content': '中文', 'path': '/tmp/测试.txt'}
        expected_params = '{"content":"中文","path":"/tmp/测试.txt"}'.encode()
        self.assertEqual(native_hold_boundary.canonical(params), expected_params)
        self.assertNotEqual(native_held_intent.signed_canonical(params), expected_params)

    def test_modified_intent_or_binding_fails_signature(self):
        from cryptography.exceptions import InvalidSignature
        for kind in ('intent', 'binding'):
            data, models, receipts, http, key = self.fixture(kind)
            data['authority_subject'][kind]['task_id'] = 'unrelated-task'
            with self.assertRaises(InvalidSignature):
                native_hold_boundary.verify(data, data['profile'], models, receipts, http, key)

    def test_actual_native_enrollment_required(self):
        data, models, receipts, http, key = self.fixture('binding')
        data['wire'] = [w for w in data['wire'] if w['path'] != '/v1/runtime-sessions']
        with self.assertRaises(ValueError):
            native_hold_boundary.verify(data, data['profile'], models, receipts, http, key)

    def test_revocation_signature_cannot_be_retargeted(self):
        from cryptography.exceptions import InvalidSignature
        for kind in ('intent', 'binding'):
            data, models, receipts, http, key = self.fixture(kind)
            old = copy.deepcopy(data['revocation'])
            data['revocation'][kind + '_id'] = 'unrelated'
            for row in http:
                if row['response'] == old:
                    row['response'] = copy.deepcopy(data['revocation'])
            with self.assertRaises(InvalidSignature):
                native_hold_boundary.verify(data, data['profile'], models, receipts, http, key)

    def test_idempotent_retry_must_be_after_effect_window(self):
        data, models, receipts, http, key = self.fixture()
        route, _ = native_held_intent.request(data['authority_subject'], data['authority'])
        rows = [r for r in http if r['path'] == route]
        self.assertEqual(len(rows), 2)
        rows[1]['monotonic_ns'] = data['oracle']['window_start_ns']
        with self.assertRaises(ValueError):
            native_hold_boundary.verify(data, data['profile'], models, receipts, http, key)

    def test_original_authority_cannot_change_after_revoke(self):
        for kind in ('intent', 'binding'):
            data, models, receipts, http, key = self.fixture(kind)
            data['authority_history']['original']['task_id'] = 'changed-after-revocation'
            self.assertFalse(native_held_intent.confirmed(data))
            with self.assertRaises(ValueError):
                native_hold_boundary.verify(data, data['profile'], models, receipts, http, key)

    def test_control_requires_missing_revocation_not_generic_error(self):
        data, models, receipts, http, key = self.fixture('binding', 'after-reserve-control')
        data['authority_history']['revocation']['error'] = 'database_unavailable'
        self.assertFalse(native_held_intent.confirmed(data))
        with self.assertRaises(ValueError):
            native_hold_boundary.verify(data, data['profile'], models, receipts, http, key)

    def test_readback_and_retry_cannot_be_omitted(self):
        for suffix in ('/revocation', '/revoke'):
            data, models, receipts, http, key = self.fixture()
            late = [r for r in http if r['path'].endswith(suffix) and r['monotonic_ns'] > data['oracle']['window_end_ns']]
            self.assertTrue(late)
            http.remove(late[0])
            with self.assertRaises(ValueError):
                native_hold_boundary.verify(data, data['profile'], models, receipts, http, key)

    def test_incomplete_authority_capture_does_not_confirm(self):
        for kind in ('intent', 'binding'):
            self.assertFalse(native_held_intent.confirmed({'authority': kind, 'authority_subject': None, 'authority_history': None}))


if __name__ == '__main__':
    unittest.main()
