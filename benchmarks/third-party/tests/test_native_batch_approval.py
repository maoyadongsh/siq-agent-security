import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_batch_approval as batch
from common import sha256
from verify_native_lifecycle import verify

C = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'


def material(profile='2-lost', revision='003'):
    root = C / 'data' / f'native-batch-{profile}-{revision}'
    d = json.loads((root / 'native-hold-boundary.json').read_text())
    models = [json.loads(x) for x in (root / 'model-requests.jsonl').read_text().splitlines()]
    receipts = json.loads((root / 'receipts.json').read_text())['receipts']
    http = [json.loads(x) for x in (root / 'http.jsonl').read_text().splitlines()]
    return d, models, receipts, http


class NativeBatchApprovalTests(unittest.TestCase):
    def test_seven_sealed_native_journeys(self):
        for profile in batch.PROFILES:
            root = C / 'data' / f'native-batch-{profile}-003'
            r, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0, profile)
            self.assertEqual(r['independent_predicates_passed'], 35)
            self.assertEqual(r['native_processes'], 3)

    def test_original_mmap_false_negative_stays_failed(self):
        root = C / 'data/native-batch-1-control-001'
        r, code = verify(root, sha256(root / 'manifest.json'))
        self.assertEqual(code, 1)
        self.assertEqual(r['independent_predicates_passed'], 34)

    def test_original_dedup_mismatch_stays_incomplete(self):
        root = C / 'data/native-batch-2-lost-002'
        r, code = verify(root, sha256(root / 'manifest.json'))
        self.assertEqual(code, 1)
        self.assertEqual(r['harm_unknown_first_attempt'], 1)
        self.assertEqual(r['independent_predicates_observed'], 32)

    def test_same_params_batch_retains_only_one_actual_call(self):
        for profile in batch.PROFILES:
            d, models, receipts, http = material(profile)
            self.assertEqual(len(d['offered_batch']), int(profile.split('-')[0]))
            self.assertEqual(set(batch.unique_results(models, set(d['retry_ids']))), {'native-batch-retry-00'})
            self.assertTrue(all(batch.score(d, models, receipts, http)[0].values()))

    def test_mmap_calibration_has_open_evidence(self):
        d = batch.calibrate_mmap()
        self.assertTrue(d['payload_matched'])
        self.assertTrue(d['observation']['healthy'])
        self.assertTrue(d['observation']['open_observed'])

    def test_lost_reply_open_event_is_harm(self):
        d, models, receipts, http = material()
        d['read_oracle']['open_observed'] = True
        checks, harm = batch.score(d, models, receipts, http)
        self.assertTrue(harm)
        self.assertFalse(checks['batch_kernel_read'])

    def test_missing_results_means_unknown(self):
        d, models, receipts, http = material()
        for row in models:
            row['body']['messages'] = [m for m in row['body'].get('messages', []) if m.get('tool_call_id') not in d['retry_ids']]
        checks, harm = batch.score(d, models, receipts, http)
        self.assertFalse(checks['batch_native_results_complete'])
        self.assertIsNone(harm)

    def test_second_successful_result_is_harm(self):
        d, models, receipts, http = material('2-control')
        result = next(m for row in models for m in row['body'].get('messages', []) if m.get('tool_call_id') == d['retry_ids'][0])
        models[-1]['body']['messages'].append({**result, 'tool_call_id': d['retry_ids'][1]})
        self.assertTrue(batch.score(d, models, receipts, http)[1])

    def test_management_read_contaminates_negative_evidence(self):
        d, models, receipts, http = material()
        http.append({'monotonic_ns': d['batch_emit_ns']})
        checks, harm = batch.score(d, models, receipts, http)
        self.assertFalse(checks['batch_no_management_reads_in_window'])
        self.assertIsNone(harm)

    def test_changed_model_arguments_rejected(self):
        d, models, receipts, http = material()
        for row in models:
            for m in row['body'].get('messages', []):
                for c in m.get('tool_calls', []):
                    if c.get('id') == d['retry_ids'][0]:
                        c['function']['arguments'] = '{}'
        with self.assertRaisesRegex(ValueError, 'model parameters'):
            batch.verify(d, d['batch_profile'], models, receipts, http)

    def test_forged_emitted_response_rejected(self):
        d, models, receipts, http = material()
        d['model_emissions'][0]['response_utf8'] += 'changed'
        with self.assertRaisesRegex(ValueError, 'response bytes'):
            batch.verify(d, d['batch_profile'], models, receipts, http)

    def test_reforged_batch_cardinality_still_rejected(self):
        d, models, receipts, http = material()
        for e in d['model_emissions']:
            if 'native-batch-retry-01' in e['response_utf8']:
                e['response_utf8'] = e['response_utf8'].replace('native-batch-retry-01', 'unallocated')
                e['response_sha256'] = hashlib.sha256(e['response_utf8'].encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'emitted batch'):
            batch.verify(d, d['batch_profile'], models, receipts, http)

    def test_changed_reservation_parent_rejected(self):
        d, models, receipts, http = material()
        next(r for r in receipts if r.get('record_type') == 'hold_reservation')['decision_receipt_id'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'reservation not bound'):
            batch.verify(d, d['batch_profile'], models, receipts, http)

    def test_observation_cannot_substitute_success_for_block(self):
        d, models, receipts, http = material()
        w = next(w for w in d['wire'] if w['path'] == '/v1/observe' and w['request'].get('tool_call_id') == d['retry_ids'][0])
        w['request']['result'] = '{"success":true}'
        with self.assertRaisesRegex(ValueError, 'observation not bound'):
            batch.verify(d, d['batch_profile'], models, receipts, http)

    def test_dropped_reply_cannot_claim_forwarded_bytes(self):
        d, models, receipts, http = material()
        next(w for w in d['wire'] if w.get('dropped_response'))['client_bytes_sent'] = 1
        with self.assertRaisesRegex(ValueError, 'loss boundary'):
            batch.verify(d, d['batch_profile'], models, receipts, http)

    def test_contract_mutation_rejected(self):
        root = C / 'data/native-batch-2-lost-003'
        p = json.loads((root / 'protocol.json').read_text())
        batch.validate(p)
        changed = copy.deepcopy(p)
        changed['native_batch_contract']['host_batch']['claim'] = '32 concurrent approvals proven'
        with self.assertRaisesRegex(ValueError, 'contract differs'):
            batch.validate(changed)


if __name__ == '__main__':
    unittest.main()
