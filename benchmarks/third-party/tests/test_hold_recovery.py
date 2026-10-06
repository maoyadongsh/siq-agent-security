import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
import evidence
from common import sha256
from hold_recovery import allocation, verify_recovery
from verify_product_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006'
RUN = CAMPAIGN / 'data/hold-recovery-002'


class HoldRecoveryTests(unittest.TestCase):
    def fixture(self, variant='restart-replay', condition='adversarial'):
        unit = next(u for u in allocation(2) if u['variant'] == variant and u['condition'] == condition)
        directory = RUN / 'attempts' / unit['unit_id'] / '1'
        result = json.loads((directory / 'result.json').read_text())
        receipts, _ = evidence.verify_receipt_bundles([json.loads((directory / 'product-evidence.json').read_text())])
        return directory, unit, result, receipts

    def test_both_registered_cohorts_verify(self):
        for suffix, count in [('001', 10), ('002', 12)]:
            root = CAMPAIGN / 'data' / ('hold-recovery-' + suffix)
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0)
            self.assertEqual(result['first_attempt_pass'], count)
            self.assertEqual(result['signed_completed_attempts_checked'], count)

    def test_physical_utility_and_persisted_status_are_separate(self):
        for variant, count, status in [('after-reserve', 0, 'uncertain'), ('after-dispatch', 1, 'uncertain'), ('observe-response-loss', 1, 'completed')]:
            _, _, result, _ = self.fixture(variant)
            self.assertEqual(len(result['executions']), count)
            self.assertEqual(result['utility_completed'], bool(count))
            self.assertEqual(result['status']['body']['status'], status)

    def test_owned_process_substitution_rejected(self):
        directory, unit, result, receipts = self.fixture()
        result['restart_checkpoints'][0]['new_process']['pid'] += 1
        with self.assertRaises(ValueError):
            verify_recovery(directory, unit, result, receipts, evidence)

    def test_kill_boundary_cannot_be_relabelled(self):
        directory, unit, original, receipts = self.fixture('after-reserve')
        result = copy.deepcopy(original)
        events = result['events']
        kill = next(e for e in events if e['event'] == 'kill_requested')
        reserve = next(e for e in events if e['event'] == 'reserve_returned')
        kill['event'], reserve['event'] = reserve['event'], kill['event']
        with self.assertRaises(ValueError):
            verify_recovery(directory, unit, result, receipts, evidence)

    def test_status_and_replay_bind_original_reservation(self):
        directory, unit, original, receipts = self.fixture()
        for target in ('status', 'replay'):
            result = copy.deepcopy(original)
            if target == 'status':
                result['status']['request']['reservation_receipt_id'] = 'unrelated'
            else:
                result['requests']['replay']['request']['params']['content'] = 'changed'
            with self.subTest(target=target), self.assertRaises(ValueError):
                verify_recovery(directory, unit, result, receipts, evidence)

    def test_lost_reply_cannot_be_labelled_received(self):
        directory, unit, result, receipts = self.fixture('observe-response-loss')
        result['observe_client']['http_status'] = 200
        self.assertFalse(all(verify_recovery(directory, unit, result, receipts, evidence)))

    def test_decision_id_cannot_substitute_observation(self):
        directory, unit, result, receipts = self.fixture()
        result['tool_observations'][0]['receipt_id'] = result['decision']['receipt_id']
        with self.assertRaises(ValueError):
            verify_recovery(directory, unit, result, receipts, evidence)

    def test_history_loss_rejected(self):
        directory, unit, result, receipts = self.fixture()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'case'
            shutil.copytree(directory, target)
            path = target / 'after-restart-evidence.json'
            after = json.loads(path.read_text())
            after['receipts'].pop()
            path.write_text(json.dumps(after))
            with self.assertRaises(ValueError):
                verify_recovery(target, unit, result, receipts, evidence)

    def test_graceful_exit_does_not_prove_sigkill(self):
        directory, unit, result, receipts = self.fixture()
        result['restart_checkpoints'][0]['returncode'] = 0
        self.assertFalse(all(verify_recovery(directory, unit, result, receipts, evidence)))


if __name__ == '__main__':
    unittest.main()
