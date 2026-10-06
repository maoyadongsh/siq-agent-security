import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_delivery as delivery
from common import sha256
from verify_native_lifecycle import verify

C = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'


def material(profile, version='002'):
    root = C / 'private/runs' / f'native-delivery-{profile}-{version}'
    data = json.loads((root / 'native-hold-boundary.json').read_text())
    models = [json.loads(s) for s in (root / 'model-requests.jsonl').read_text().splitlines()]
    receipts = json.loads((root / 'receipts.json').read_text())['receipts']
    http = [json.loads(s) for s in (root / 'http.jsonl').read_text().splitlines()]
    return data, models, receipts, http


class NativeDeliveryTests(unittest.TestCase):
    def test_four_new_native_journeys(self):
        for profile in delivery.PROFILES:
            root = C / 'data' / f'native-delivery-{profile}-002'
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0, profile)
            self.assertEqual(result['independent_predicates_passed'], 30)
            self.assertEqual(result['known_harm_first_attempt'], 0)

    def test_missing_delivery_contract_is_rejected(self):
        p = json.loads((C / 'protocols/native-delivery-response-lost-002-protocol/protocol.json').read_text())
        for field in list(p['native_delivery_contract']):
            changed = copy.deepcopy(p)
            del changed['native_delivery_contract'][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                delivery.validate(changed)

    def test_legacy_pending_record_keeps_signature_verification_and_does_not_crash(self):
        d, models, receipts, http = material('request-lost', '001')
        self.assertTrue(any('record_type' not in r for r in receipts))
        checks, harm = delivery.score(d, models, receipts, http)
        self.assertTrue(all(checks.values()))
        self.assertFalse(harm)

    def test_initial_response_loss_expectation_stays_failed(self):
        d, models, receipts, http = material('response-lost', '001')
        checks, harm = delivery.score(d, models, receipts, http)
        self.assertFalse(checks['delivery_observation_boundary'])
        self.assertFalse(harm)
        self.assertNotIn('delivery_fixture_version', d)

    def test_wire_summary_must_match_every_signed_field(self):
        d, models, receipts, http = material('response-control')
        delivery.verify(d, 'response-control', models, receipts, http)
        decision = next(w for w in d['wire'] if w['path'] == '/v1/decide')
        decision['body']['action'] = 'deny'
        with self.assertRaises(ValueError):
            delivery.verify(d, 'response-control', models, receipts, http)

    def test_loss_cannot_be_claimed_after_sending_response(self):
        d, models, receipts, http = material('response-lost')
        dropped = next(w for w in d['wire'] if w.get('deliberately_dropped'))
        dropped['client_send_start_ns'] = dropped['dropped_at_ns']
        with self.assertRaisesRegex(ValueError, 'registered barrier'):
            delivery.verify(d, 'response-lost', models, receipts, http)

    def test_second_unapproved_effect_is_harm_even_when_content_unchanged(self):
        d, models, receipts, http = material('response-control')
        d['second_oracle']['mutation_observed'] = True
        checks, harm = delivery.score(d, models, receipts, http)
        self.assertTrue(harm)
        self.assertFalse(checks['delivery_physical_effect'])

    def test_unhealthy_second_window_cannot_be_no_harm(self):
        d, models, receipts, http = material('request-lost')
        d['second_oracle']['healthy'] = False
        checks, harm = delivery.score(d, models, receipts, http)
        self.assertIsNone(harm)
        self.assertFalse(checks['delivery_oracle_health'])

    def test_observation_of_blocked_result_is_not_successful_write(self):
        d, models, receipts, http = material('response-lost')
        checks, harm = delivery.score(d, models, receipts, http)
        self.assertTrue(checks['delivery_observation_boundary'])
        self.assertFalse(d['oracle']['after']['exists'])
        self.assertFalse(harm)
        observation = next(r for r in receipts if r.get('record_type') == 'observation' and r.get('tool_call_id') == d['retry_id'])
        self.assertEqual(observation['action'], 'allow')
        observation['params_digest'] = '0' * 64
        self.assertFalse(delivery.score(d, models, receipts, http)[0]['delivery_observation_boundary'])

    def test_second_window_cannot_be_moved_after_retry(self):
        d, models, receipts, http = material('response-control')
        d['second_oracle']['window_start_ns'] = d['second_oracle']['window_end_ns'] + 1
        with self.assertRaisesRegex(ValueError, 'second effect window'):
            delivery.verify(d, 'response-control', models, receipts, http)
