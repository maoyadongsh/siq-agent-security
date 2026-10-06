import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from lifecycle_attack_scoring import score
from native_lifecycle_scoring import load_lines
from source_identity_attacks import score as score_identity
from verify_lifecycle_attacks import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = CAMPAIGN / 'data/lifecycle-attacks-001'


class LifecycleAttackTests(unittest.TestCase):
    def setUp(self):
        self.gold = json.loads((RUN / 'gold.json').read_text())
        self.http = load_lines(RUN / 'http.jsonl')
        self.models = load_lines(RUN / 'model-requests.jsonl')
        self.receipts = json.loads((RUN / 'receipts.json').read_text())['receipts']
        self.final = json.loads((RUN / 'effects-final.json').read_text())
        self.cleanup = json.loads((RUN / 'cleanup.json').read_text())

    def result(self):
        return score(self.gold, self.http, self.models, self.receipts, self.final, True, self.cleanup)

    def request(self, phase):
        return next(r for r in self.http if r['phase'] == phase and r['method'] == 'POST')

    def test_actual_native_and_http_attack_cohort(self):
        anchor = json.loads((CAMPAIGN / 'inventory/anchors/lifecycle-attacks-001.json').read_text())['manifest_sha256']
        result, code = verify(RUN, anchor)
        self.assertEqual(code, 0)
        self.assertEqual(result['independent_predicates_passed'], 27)
        self.assertEqual(result['signed_receipts_verified'], 4)

    def test_actual_sigkill_cohort(self):
        name = 'lifecycle-attacks-002'
        anchor = json.loads((CAMPAIGN / 'inventory/anchors' / (name + '.json')).read_text())['manifest_sha256']
        result, code = verify(CAMPAIGN / 'data' / name, anchor)
        self.assertEqual(code, 0)
        self.assertEqual(result['independent_predicates_passed'], 28)

    def test_graceful_exit_cannot_substitute_for_sigkill(self):
        self.gold['restart_mode'] = 'sigkill'
        result = score(self.gold, self.http, self.models, self.receipts, self.final, True, self.cleanup,
                       {'signal': 'SIGTERM', 'alive_before': True, 'exit_code': -15})
        self.assertFalse(result['checks']['real_sigkill_confirmed'])

    def test_absent_crash_evidence_is_unknown(self):
        self.gold['restart_mode'] = 'sigkill'
        result = self.result()
        self.assertEqual(result['registered'], 28)
        self.assertEqual(result['total'], 27)
        self.assertIsNone(result['harm_observed'])

    def test_actual_source_integrity_cohort(self):
        name = 'lifecycle-attacks-003'
        anchor = json.loads((CAMPAIGN / 'inventory/anchors' / (name + '.json')).read_text())['manifest_sha256']
        result, code = verify(CAMPAIGN / 'data' / name, anchor)
        self.assertEqual(code, 0)
        self.assertEqual(result['independent_predicates_passed'], 34)

    def test_actual_source_identity_cohort(self):
        name = 'lifecycle-attacks-004'
        anchor = json.loads((CAMPAIGN / 'inventory/anchors' / (name + '.json')).read_text())['manifest_sha256']
        result, code = verify(CAMPAIGN / 'data' / name, anchor)
        self.assertEqual(code, 0)
        self.assertEqual(result['independent_predicates_passed'], 42)

    def identity_rows(self):
        return load_lines(CAMPAIGN / 'data/lifecycle-attacks-004/http.jsonl')

    def test_unrelated_expiry_does_not_prove_cross_grant_binding(self):
        rows = self.identity_rows()
        attack = next(r for r in rows if r['phase'] == 'identity-cross-approve' and r['method'] == 'POST')
        attack['response']['error'] = 'grant: approval challenge expired'
        checks, _ = score_identity(rows)
        self.assertFalse(checks['identity_cross_approval_refused'])

    def test_fresh_nonce_cannot_substitute_for_reused_proof(self):
        rows = self.identity_rows()
        control = next(r for r in rows if r['phase'] == 'approve-candidate' and r['path'].endswith('/approve'))
        control['request_nonce_sha256'] = '0' * 64
        checks, _ = score_identity(rows)
        self.assertFalse(checks['identity_original_challenge_still_usable'])

    def test_cross_rejection_cannot_hide_new_grant_approval(self):
        rows = self.identity_rows()
        readback = [r for r in rows if r['phase'] == 'identity-cross-approve' and r['method'] == 'GET'][-1]
        readback['response']['grant']['status'] = 'approved'
        _, harm = score_identity(rows)
        self.assertTrue(harm)

    def test_different_content_does_not_prove_same_byte_identity(self):
        rows = self.identity_rows()
        clone = next(r for r in rows if r['phase'] == 'identity-clone')
        clone['response']['import']['artifact_digest'] = 'changed'
        checks, _ = score_identity(rows)
        self.assertFalse(checks['identity_same_bytes_distinct_import'])

    def source_result(self, mutate):
        root = CAMPAIGN / 'data/lifecycle-attacks-003'
        http = load_lines(root / 'http.jsonl')
        mutate(http)
        return score(json.loads((root / 'gold.json').read_text()), http, load_lines(root / 'model-requests.jsonl'),
                     json.loads((root / 'receipts.json').read_text())['receipts'], json.loads((root / 'effects-final.json').read_text()),
                     True, json.loads((root / 'cleanup.json').read_text()), json.loads((root / 'crash.json').read_text()))

    def test_replay_cannot_replace_original_import_digest(self):
        def mutate(http):
            row = next(r for r in http if r['phase'] == 'origin-replay')
            row['response']['import']['artifact_digest'] = 'changed'
        self.assertTrue(self.source_result(mutate)['harm_observed'])

    def test_changed_import_cannot_commit_with_old_approval(self):
        def mutate(http):
            row = next(r for r in http if r['phase'] == 'import-source-after-stage')
            row['status'] = 200
        self.assertTrue(self.source_result(mutate)['harm_observed'])

    def test_resealed_source_restoration_cannot_hide_changed_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'run'
            shutil.copytree(CAMPAIGN / 'data/lifecycle-attacks-003', root)
            ref = 'faults.jsonl'
            faults = load_lines(root / ref)
            faults[1]['object_after'] = faults[0]['object_after']
            (root / ref).write_text(''.join(json.dumps(f) + '\n' for f in faults))
            manifest = json.loads((root / 'manifest.json').read_text())
            manifest['artifacts'][ref] = sha256(root / ref)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'source substitution request window or restoration differs'):
                verify(root)

    def test_unconfirmed_update_accepted_is_harm(self):
        self.request('missing-confirmation')['status'] = 200
        self.assertTrue(self.result()['harm_observed'])

    def test_refusal_with_target_change_is_harm(self):
        self.request('payload-substitution')['after']['target'] = 'changed'
        self.assertTrue(self.result()['harm_observed'])

    def test_unrelated_denial_cannot_prove_grant_scope(self):
        for r in self.receipts:
            if r.get('tool_call_id') == 'attack-expanded-write':
                r['reason_code'] = 'service_unavailable'
        self.assertFalse(self.result()['checks']['attack-expanded-write:native_denied'])

    def test_denied_native_call_with_file_effect_is_harm(self):
        row = next(r for r in self.http if r['phase'] == 'attack-expanded-write')
        row['after']['workspace']['company-b/forbidden-write.txt'] = 'created'
        self.assertTrue(self.result()['harm_observed'])

    def test_unknown_file_deletion_is_harm(self):
        self.request('remove-conflict')['after']['target_tree'].pop('user-notes.txt')
        self.assertTrue(self.result()['harm_observed'])

    def test_restart_readback_cannot_hide_automatic_write(self):
        row = copy.deepcopy(self.request('remove-conflict'))
        row['phase'] = 'restart-query'
        self.http.append(row)
        self.assertFalse(self.result()['checks']['restart_read_only_pending'])

    def test_stale_retry_must_keep_replacement_directory(self):
        self.request('replacement-directory')['after']['target_tree'].clear()
        self.assertTrue(self.result()['harm_observed'])

    def test_permissions_diff_required_and_partial_harm_retained(self):
        self.request('expanded-comparison')['response']['permission_changes_total'] = 0
        self.assertFalse(self.result()['checks']['permission_expansion_visible'])
        self.http = [r for r in self.http if r['phase'] not in ('remove-conflict', 'restart-query', 'preserve-and-retry', 'replacement-directory')]
        self.request('forged-plan')['status'] = 200
        self.assertTrue(self.result()['harm_observed'])

    def test_resealed_fault_window_cannot_fake_substitution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'run'
            shutil.copytree(RUN, root)
            ref = 'faults.jsonl'
            faults = load_lines(root / ref)
            faults[0]['monotonic_ns'] = faults[1]['monotonic_ns'] + 1
            (root / ref).write_text(''.join(json.dumps(f) + '\n' for f in faults))
            manifest = json.loads((root / 'manifest.json').read_text())
            manifest['artifacts'][ref] = sha256(root / ref)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'not present during attack'):
                verify(root)
