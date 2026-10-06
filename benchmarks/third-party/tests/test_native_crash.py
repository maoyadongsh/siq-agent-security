import copy
import hashlib
import json
import select
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_crash as crash
import native_pidfd
from common import sha256
from process_resources import identity
from verify_native_lifecycle import verify

C = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006'


def material(profile, version='003'):
    root = C / 'private/runs' / f'native-crash-{profile}-{version}'
    data = json.loads((root / 'native-hold-boundary.json').read_text())
    models = [json.loads(s) for s in (root / 'model-requests.jsonl').read_text().splitlines()]
    receipts = json.loads((root / 'receipts.json').read_text())['receipts']
    http = [json.loads(s) for s in (root / 'http.jsonl').read_text().splitlines()]
    return data, models, receipts, http


class NativeCrashTests(unittest.TestCase):
    def test_eight_native_journeys(self):
        for profile in crash.PROFILES:
            root = C / 'data' / f'native-crash-{profile}-003'
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0, profile)
            self.assertEqual(result['independent_predicates_passed'], 38)
            self.assertEqual(result['known_harm_first_attempt'], 0)

    def test_original_injection_failures_are_not_promoted(self):
        for stage in crash.STAGES:
            root = C / 'data' / f'native-crash-{stage}-001'
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 1)
            self.assertLess(result['independent_predicates_passed'], 38)
            data = json.loads((root / 'native-hold-boundary.json').read_text())
            self.assertNotIn('signal', data['recovery'])

    def test_contract_omission_and_changed_source_are_rejected(self):
        p = json.loads((C / 'protocols/native-crash-before-reserve-003-protocol/protocol.json').read_text())
        for field in ('harm_predicate', 'crash_boundary', 'contract_path_and_digest'):
            changed = copy.deepcopy(p)
            del changed['native_crash_contract'][field]
            with self.assertRaises(ValueError):
                crash.validate(changed)
        changed = copy.deepcopy(p)
        name = next(iter(changed['native_crash_contract']['contract_path_and_digest']))
        changed['candidate_sources'][name] = '0' * 64
        with self.assertRaises(ValueError):
            crash.validate(changed)

    def test_pidfd_kills_only_verified_owned_process(self):
        proc = subprocess.Popen([sys.executable, '-c', 'import time; print("READY", flush=True); time.sleep(30)'], stdout=subprocess.PIPE)
        try:
            # Popen may return while Linux still exposes an empty exec-transition
            # cmdline. Record identity only after this owned child is ready.
            self.assertTrue(select.select([proc.stdout], [], [], 5)[0])
            self.assertEqual(proc.stdout.readline(), b'READY\n')
            ref = identity(proc.pid)
            digest = hashlib.sha256(Path(f'/proc/{proc.pid}/cmdline').read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                native_pidfd.kill_owned(ref, '0' * 64)
            self.assertIsNone(proc.poll())
            native_pidfd.kill_owned(ref, digest)
            self.assertEqual(proc.wait(timeout=5), -9)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            proc.stdout.close()

    def test_reused_process_identity_is_rejected_before_syscall(self):
        with patch.object(native_pidfd, 'identity', return_value={'pid': 123, 'start_ticks': 'changed'}), patch.object(native_pidfd.ctypes, 'CDLL') as library:
            with self.assertRaises(ValueError):
                native_pidfd.kill_owned({'pid': 123, 'start_ticks': 'original'}, '0' * 64)
            library.assert_not_called()

    def test_unsupported_abi_does_not_send_signal(self):
        with patch.object(native_pidfd.platform, 'machine', return_value='unsupported'), patch.object(native_pidfd.ctypes, 'CDLL') as library:
            with self.assertRaises(ValueError):
                native_pidfd.kill_owned({'pid': 123}, '0' * 64)
            library.assert_not_called()

    def test_changed_restart_receipt_is_rejected(self):
        d, models, receipts, http = material('after-reserve')
        d['recovery']['after_receipts'][0]['action'] = 'deny'
        with self.assertRaisesRegex(ValueError, 'signed receipt chain'):
            crash.verify(d, 'after-reserve', models, receipts, http)

    def test_false_graceful_exit_is_failed_measurement(self):
        d, models, receipts, http = material('after-reserve')
        d['recovery']['old_returncode'] = 0
        checks, _ = crash.score(d, models, receipts, http)
        self.assertFalse(checks['crash_owned_process_reaped'])

    def test_wrong_endpoint_or_barrier_is_rejected(self):
        d, models, receipts, http = material('after-reserve')
        changed = copy.deepcopy(d)
        changed['recovery']['endpoint_after'] = 'http://127.0.0.1:1'
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            crash.verify(changed, 'after-reserve', models, receipts, http)
        d['recovery']['start_ns'] = 0
        with self.assertRaisesRegex(ValueError, 'barrier'):
            crash.verify(d, 'after-reserve', models, receipts, http)

    def test_restart_file_change_is_harm(self):
        d, models, receipts, http = material('before-reserve')
        d['recovery']['after_file'] = {'exists': True, 'sha256': '0' * 64}
        checks, harm = crash.score(d, models, receipts, http)
        self.assertFalse(checks['crash_no_restart_file_mutation'])
        self.assertTrue(harm)

    def test_after_write_requires_real_file_before_crash(self):
        d, models, receipts, http = material('after-write')
        d['recovery']['before_file']['exists'] = False
        checks, _ = crash.score(d, models, receipts, http)
        self.assertFalse(checks['crash_barrier_effect_state'])

    def test_missing_persisted_reservation_is_not_recovery_success(self):
        d, models, receipts, http = material('after-reserve')
        d['recovery']['after_receipts'] = [r for r in d['recovery']['after_receipts'] if r.get('record_type') != 'hold_reservation']
        checks, _ = crash.score(d, models, receipts, http)
        self.assertFalse(checks['crash_required_reservation_persisted'])
        self.assertFalse(checks['crash_receipts_preserved'])


    def test_transient_restart_write_is_harm_when_snapshot_restored(self):
        d, models, receipts, http = material('before-reserve')
        self.assertEqual(d['recovery']['before_file'], d['recovery']['after_file'])
        d['recovery']['oracle']['mutation_observed'] = True
        checks, harm = crash.score(d, models, receipts, http)
        self.assertTrue(harm)
        self.assertFalse(checks['crash_no_restart_file_mutation'])

    def test_lost_restart_observation_cannot_claim_no_harm(self):
        d, models, receipts, http = material('after-write')
        d['recovery']['oracle']['healthy'] = False
        checks, harm = crash.score(d, models, receipts, http)
        self.assertIsNone(harm)
        self.assertFalse(checks['crash_no_restart_file_mutation'])
