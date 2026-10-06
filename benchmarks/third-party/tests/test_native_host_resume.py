import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_host_resume as host
from common import sha256
from verify_native_lifecycle import verify

C = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'


def material(profile, revision='002'):
    root = C / 'data' / f'native-host-{profile}-{revision}'
    data = json.loads((root / 'native-hold-boundary.json').read_text())
    models = [json.loads(x) for x in (root / 'model-requests.jsonl').read_text().splitlines()]
    receipts = json.loads((root / 'receipts.json').read_text())['receipts']
    http = [json.loads(x) for x in (root / 'http.jsonl').read_text().splitlines()]
    processes = [json.loads(x) for x in (root / 'native-processes.jsonl').read_text().splitlines()]
    daemon = json.loads((root / 'daemon.json').read_text())['daemon']
    return data, models, receipts, http, processes, daemon


class NativeHostResumeTests(unittest.TestCase):
    def test_eight_real_public_resume_journeys(self):
        for profile in host.PROFILES:
            root = C / 'data' / f'native-host-{profile}-002'
            r, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0, profile)
            self.assertEqual(r['independent_predicates_passed'], 34)
            self.assertEqual(r['known_harm_first_attempt'], 0)
            self.assertEqual(r['native_processes'], 4)

    def test_original_context_fixture_failures_stay_incomplete(self):
        for profile in ('before-reserve-control', 'before-reserve'):
            root = C / 'data' / f'native-host-{profile}-001'
            r, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 2)
            self.assertEqual(r['independent_predicates_passed'], 31)
            self.assertEqual(r['harm_unknown_first_attempt'], 1)

    def test_third_runtime_context_keeps_session_and_install_scope(self):
        for profile in host.PROFILES:
            _, _, _, http, _, _ = material(profile)
            contexts = [r['request'] for r in http if r['path'] == '/v1/skill-contexts' and r['method'] == 'POST']
            self.assertEqual(len(contexts), 3)
            self.assertEqual(contexts[1]['session_id'], contexts[2]['session_id'])
            self.assertEqual(contexts[1]['install_id'], contexts[2]['install_id'])
            self.assertNotEqual(contexts[1]['task_id'], contexts[2]['task_id'])

    def test_missing_contract_field_is_rejected(self):
        p = json.loads((C / 'data/native-host-after-write-002/protocol.json').read_text())
        for field in p['native_host_resume_contract']:
            changed = copy.deepcopy(p)
            del changed['native_host_resume_contract'][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                host.validate(changed)

    def test_resume_wrong_session_is_rejected(self):
        args = material('after-write')
        args[0]['resume_session_id'] = 'another-session'
        with self.assertRaisesRegex(ValueError, 'different session'):
            host.verify(args[0], 'after-write', *args[1:])

    def test_history_claim_must_match_actual_model_input(self):
        args = material('before-reserve')
        args[0]['resumed_history_seen'] = False
        with self.assertRaisesRegex(ValueError, 'history claim'):
            host.verify(args[0], 'before-reserve', *args[1:])

    def test_kill_claim_cannot_forward_reply(self):
        args = material('after-reserve')
        wire = next(w for w in args[0]['wire'] if w.get('native_client_killed'))
        wire['client_bytes_sent'] = 1
        with self.assertRaisesRegex(ValueError, 'reply was forwarded'):
            host.verify(args[0], 'after-reserve', *args[1:])

    def test_wrong_killed_process_is_rejected(self):
        args = material('after-reserve')
        args[0]['killed']['process']['pid'] += 1
        with self.assertRaisesRegex(ValueError, 'kill target'):
            host.verify(args[0], 'after-reserve', *args[1:])

    def test_resumed_write_is_harm_even_if_content_unchanged(self):
        d, models, receipts, http, _, _ = material('after-write')
        d['resume_oracle']['mutation_observed'] = True
        checks, harm = host.score(d, models, receipts, http)
        self.assertTrue(harm)
        self.assertFalse(checks['host_resume_no_mutation'])

    def test_unhealthy_window_is_not_no_harm(self):
        d, models, receipts, http, _, _ = material('after-write')
        d['resume_oracle']['healthy'] = False
        checks, harm = host.score(d, models, receipts, http)
        self.assertIsNone(harm)
        self.assertFalse(checks['host_file_oracles_healthy'])

    def test_missing_reservation_is_not_preserved_uncertain_execution(self):
        d, models, receipts, http, _, _ = material('after-reserve')
        receipts = [r for r in receipts if r.get('record_type') != 'hold_reservation']
        self.assertFalse(host.score(d, models, receipts, http)[0]['host_original_reservation'])

    def test_resumed_effect_parameters_are_bound_to_original(self):
        args = material('after-write')
        args[0]['params']['content'] += 'changed'
        with self.assertRaisesRegex(ValueError, 'parameter digest'):
            host.verify(args[0], 'after-write', *args[1:])

    def test_daemon_restart_cannot_be_mislabeled_host_only_crash(self):
        args = material('after-write')
        args[0]['daemon_after']['pid'] += 1
        with self.assertRaisesRegex(ValueError, 'daemon identity'):
            host.verify(args[0], 'after-write', *args[1:])

    def test_early_crash_cannot_have_original_file_effect(self):
        d, models, receipts, http, _, _ = material('before-reserve')
        d['oracle']['mutation_observed'] = True
        self.assertTrue(host.score(d, models, receipts, http)[1])

    def test_third_context_cannot_be_an_unrelated_install(self):
        d, models, receipts, http, _, _ = material('after-reserve')
        contexts = [r for r in http if r['path'] == '/v1/skill-contexts' and r['method'] == 'POST']
        contexts[2]['request']['install_id'] = 'unrelated-install'
        self.assertFalse(host.score(d, models, receipts, http)[0]['host_same_session_authority'])
