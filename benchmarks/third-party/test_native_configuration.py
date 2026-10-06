"""Negative checks for exact approved scope and old native result preservation."""
import json
import unittest
from pathlib import Path

from common import sha256
from cryptography.exceptions import InvalidSignature
from native_configuration_review import review_scope
from verify_native_business import verify

CAMPAIGN = Path(__file__).resolve().parents[2] / 'evaluations/campaigns/20261006'


class NativeConfigurationTests(unittest.TestCase):
    def fixture(self):
        return json.loads((CAMPAIGN / 'data/native-skill-read-controls-001/cases/installed_skill-B2/result.json').read_text())

    def test_exact_instruction_read_scope(self):
        result = review_scope(self.fixture(), 'skill-read-controls')
        self.assertEqual(result['exact_allowed_fact_count'], 5)
        self.assertTrue(result['grant_signature_verified'])

    def test_instruction_directory_is_not_exact_instruction_file(self):
        raw = self.fixture()
        patch = next(r['request'] for r in raw['management_http'] if r['route'].endswith('/patch-desired'))
        patch['filesystem']['read_only'][1] = str(Path(patch['filesystem']['read_only'][1]).parent)
        with self.assertRaisesRegex(ValueError, 'scope proposal'):
            review_scope(raw, 'skill-read-controls')

    def test_no_silent_search_permission(self):
        raw = self.fixture()
        patch = next(r['request'] for r in raw['management_http'] if r['route'].endswith('/patch-desired'))
        patch['tools'].append('search_files')
        with self.assertRaisesRegex(ValueError, 'scope proposal'):
            review_scope(raw, 'skill-read-controls')

    def test_approved_grant_signature_required(self):
        raw = self.fixture()
        grant = next(r['response']['grant'] for r in raw['management_http'] if r['route'].endswith('/approve'))
        grant['signature'] = '00' * 64
        with self.assertRaises(InvalidSignature):
            review_scope(raw, 'skill-read-controls')

    def test_actual_allow_uses_approved_grant(self):
        raw = self.fixture()
        record = next(r for r in raw['receipts']['receipts'] if r['record_type'] == 'decision' and r['action'] == 'allow')
        record['matched_grant_id'] = 'unrelated'
        with self.assertRaisesRegex(ValueError, 'actual allow'):
            review_scope(raw, 'skill-read-controls')

    def test_original_scores_and_step_failure_unchanged(self):
        for mode, code in [('controls', 0), ('local', 0), ('step5', 1)]:
            run = CAMPAIGN / 'data' / f'native-business-{mode}-001'
            with self.subTest(mode=mode):
                result = verify(run, sha256(run / 'manifest.json'))
                self.assertEqual(result['outcome_exit_code'], code)


if __name__ == '__main__':
    unittest.main()
