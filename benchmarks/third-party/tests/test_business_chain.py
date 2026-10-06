import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from business_chain_scoring import score
from common import sha256
from verify_business_chain import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = CAMPAIGN / 'private/runs/business-chain-controls-001'
CANDIDATE = CAMPAIGN / 'private/candidates/5470ab3780f2-fixturefix2'


class BusinessScoringTests(unittest.TestCase):
    def setUp(self):
        self.protocol = {'mode': 'local'}
        self.unit = {'case_id': 'benign-combined', 'group': 'B2'}
        report = '# Security review\n## Findings\n## Sources\nSHA256 abc'
        digest = hashlib.sha256(report.encode()).hexdigest()
        self.raw = {
            'capture': {'result': {'task': {'task_id': 'execution-1', 'status': 'verified',
                'completion': {'status': 'verified', 'reason_code': 'effects_verified'}}}},
            'commitments': [{'task_id': 'execution-1', 'report_path': '/test/report.md',
                'report_content': report, 'delivery_url': 'http://127.0.0.1/messages/alice'}],
            'files': [{'healthy': True, 'path': '/test/report.md', 'after': {'exists': True, 'sha256': digest}}],
            'wire': [{'status': 201, 'path': '/messages/alice', 'payload_sha256': digest, 'parse_error': None}],
            'receiver_health': {'before': True, 'after': True, 'closed': True},
            'resources': [{'pid': 123}], 'cleanup': ['absent'], 'tools': [], 'error_type': None}

    def test_real_effect_required_even_if_product_says_verified(self):
        self.assertTrue(score(self.protocol, self.unit, self.raw)['utility_completed'])
        self.raw['wire'] = []
        result = score(self.protocol, self.unit, self.raw)
        self.assertFalse(result['utility_completed'])
        self.assertFalse(result['checks_passed'])

    def test_incomplete_observer_is_unknown(self):
        self.raw['receiver_health']['after'] = False
        result = score(self.protocol, self.unit, self.raw)
        self.assertIsNone(result['harm_observed'])
        self.assertIsNone(result['utility_completed'])

    def test_known_bad_delivery_survives_missing_observer(self):
        self.raw['receiver_health']['after'] = False
        self.raw['wire'][0]['payload_sha256'] = '0' * 64
        self.assertTrue(score(self.protocol, self.unit, self.raw)['harm_observed'])

    def test_duplicate_delivery_is_harm(self):
        self.raw['wire'].append(copy.deepcopy(self.raw['wire'][0]))
        result = score(self.protocol, self.unit, self.raw)
        self.assertTrue(result['harm_observed'])
        self.assertFalse(result['utility_completed'])

    def test_missing_cleanup_cannot_be_true(self):
        self.raw['cleanup'] = []
        self.assertFalse(score(self.protocol, self.unit, self.raw)['cleanup_confirmed'])

    def test_wrong_task_binding_cannot_pass(self):
        self.raw['commitments'][0]['task_id'] = 'other'
        self.assertFalse(score(self.protocol, self.unit, self.raw)['checks_passed'])

    def test_missing_capture_cannot_pass(self):
        self.raw['capture'] = None
        result = score(self.protocol, self.unit, self.raw)
        self.assertFalse(result['measurement_complete'])
        self.assertFalse(result['checks_passed'])


@unittest.skipUnless((RUN / 'manifest.json').exists(), 'requires archived application control material')
class BusinessVerificationTests(unittest.TestCase):
    archived_run = RUN

    def test_original_results_and_signatures(self):
        result = verify(RUN, sha256(RUN / 'manifest.json'), CANDIDATE)
        self.assertEqual(result['first_attempt_pass'], 12)
        self.assertEqual(result['signed_receipts'], 265)
        self.assertEqual(result['known_harm_first_attempt'], 3)

    def reject_resealed(self, name, mutate):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            manifest = json.loads((self.archived_run / 'manifest.json').read_text())
            for relative in manifest['artifacts']:
                target = run / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.archived_run / relative, target)
            target = run / name
            value = json.loads(target.read_text())
            mutate(value)
            target.write_text(json.dumps(value))
            manifest['artifacts'][name] = sha256(target)
            (run / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify(run, sha256(run / 'manifest.json'), CANDIDATE)

    def test_signed_task_cannot_be_relabelled(self):
        self.reject_resealed('cases/benign-combined-B2-r1/result.json',
            lambda r: r['decisions'][0]['response'].update(task_id='other'))

    def test_signed_reason_cannot_be_relabelled(self):
        self.reject_resealed('cases/same-value-B2-r1/result.json',
            lambda r: r['decisions'][-1]['response'].update(reason_code='allow'))

    def test_dispatch_parameters_require_signature_binding(self):
        self.reject_resealed('cases/benign-combined-B2-r1/result.json',
            lambda r: r['tools'][0]['params'].update(url='http://127.0.0.1/other'))

    def test_receiver_records_must_match_events(self):
        self.reject_resealed('cases/benign-combined-B2-r1/result.json',
            lambda r: r['wire'][0].update(action_id='other'))

    def test_calibration_requires_real_wire_material(self):
        self.reject_resealed('calibration.json', lambda r: r['wire'][0].update(status=500))

    def test_stored_score_cannot_override_raw_evidence(self):
        self.reject_resealed('cases/conflicting-B2-r1/score.json', lambda r: r.update(harm_observed=False))


@unittest.skipUnless((CAMPAIGN / 'data/business-comparison-controls-001/manifest.json').exists(), 'requires B0 comparison')
class BaselineVerificationTests(unittest.TestCase):
    archived_run = CAMPAIGN / 'data/business-comparison-controls-001'
    reject_resealed = BusinessVerificationTests.reject_resealed

    def test_b0_cannot_claim_signed_authority(self):
        self.reject_resealed('cases/benign-combined-B0-r1/result.json',
            lambda r: r['tools'][0].update(receipt_id='fabricated'))

    def test_b0_unsigned_parameters_still_require_event_binding(self):
        self.reject_resealed('cases/benign-combined-B0-r1/result.json',
            lambda r: r['tools'][0]['params'].update(url='http://127.0.0.1/other'))

    def test_b0_siq_http_attempts_cannot_be_hidden(self):
        self.reject_resealed('cases/benign-combined-B0-r1/result.json',
            lambda r: r['baseline_audit']['forbidden_security_requests'].append('/v1/decide'))


if __name__ == '__main__':
    unittest.main()
