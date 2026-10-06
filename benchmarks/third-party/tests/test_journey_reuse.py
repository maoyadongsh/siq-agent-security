import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_journey_reuse import inspect_run, reconcile, verify_oracle_calibration

C = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'


class JourneyReuseTests(unittest.TestCase):
    def test_legacy_external_anchor_is_used(self):
        r = inspect_run(C, 'A-fixturefix2-001')
        self.assertEqual(r['status'], 'verified_original_evidence')
        self.assertEqual(r['anchor_ref'], 'inventory/A-fixturefix2-001-local-anchor.json')
        self.assertIsNotNone(r['candidate_identity']['candidate_manifest_sha256'])

    def test_original_incomplete_is_not_a_pass(self):
        r = inspect_run(C, 'business-pii-recovery-001')
        self.assertEqual(r['status'], 'verified_preserved_incomplete')
        self.assertEqual(r['original_outcome_exit_code'], 2)
        self.assertEqual(r['verification']['original_summary']['first_attempt_unknown'], 3)

    def test_original_invalid_event_sequence_is_not_integrity_pass(self):
        r = inspect_run(C, 'governance-http-001')
        self.assertEqual(r['status'], 'sealed_original_invalid_run')
        self.assertTrue(r['verification']['byte_integrity_verified'])
        self.assertFalse(r['verification']['event_integrity_verified'])
        self.assertEqual(r['original_outcome_exit_code'], 1)

    def test_failed_cohort_stays_failed_after_valid_verification(self):
        r = inspect_run(C, 'issuer-ingress-001')
        self.assertEqual(r['status'], 'verified_original_evidence')
        self.assertEqual(r['original_outcome_exit_code'], 1)
        self.assertEqual(r['verification']['first_attempt_fail'], 5)

    def test_cannot_derive_anchor_from_modified_manifest(self):
        name = 'issuer-ingress-002'
        with tempfile.TemporaryDirectory() as temporary:
            c = Path(temporary)
            target = c / 'data' / name
            target.mkdir(parents=True)
            (target / 'manifest.json').write_text('{}')
            (c / 'inventory/anchors').mkdir(parents=True)
            shutil.copyfile(C / 'inventory/anchors' / (name + '.json'), c / 'inventory/anchors' / (name + '.json'))
            with self.assertRaisesRegex(ValueError, 'external manifest anchor mismatch'):
                inspect_run(c, name)

    def test_run_path_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'single component'):
            inspect_run(C, '../private')

    def test_reconciliation_never_closes_journey_or_hides_unknown(self):
        spec = {'journeys': [{'journey_id': 'RB01', 'evidence_blocks': [{'runs': ['good', 'bad']}], 'remaining': ['future test']}]}
        good = {'status': 'verified_original_evidence', 'candidate_identity': {'profile_sha256': 'a'}}
        with patch('review_journey_reuse.inspect_run', side_effect=[ValueError('missing'), copy.deepcopy(good)]):
            r = reconcile(C, spec)
        self.assertEqual(r['totals']['runs_unresolved'], 1)
        self.assertFalse(r['journeys'][0]['journey_complete'])
        self.assertEqual(r['journeys'][0]['review_status'], 'verification_incomplete')
        self.assertEqual(r['totals']['new_executions'], 0)

    def test_calibration_cannot_turn_unknown_into_utility(self):
        root = C / 'data/business-observer-calibration-001'
        p = json.loads((root / 'protocol.json').read_text())
        self.assertEqual(verify_oracle_calibration(root, p)['checks'], 18)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'run'
            shutil.copytree(root, target)
            path = target / 'receiver-disconnect/result.json'
            r = json.loads(path.read_text()); r['score']['utility_completed'] = True
            path.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError, 'calibration score differs'):
                verify_oracle_calibration(target, p)


if __name__ == '__main__':
    unittest.main()
