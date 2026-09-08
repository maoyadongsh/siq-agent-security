import copy
import json
import unittest
from pathlib import Path

from recovery_evidence import timestamp, verify_chain


class RecoveryEvidenceTest(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        root = Path(__file__).resolve().parents[2] / "apps/agentshield/testdata/contracts"
        self.pending = json.loads((root / "file-observation-pending.sample.json").read_text())
        self.history = [json.loads((root / f"file-observation-recovery-{i}.sample.json").read_text()) for i in (1, 2)]
        self.key = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32).public_key()

    def test_fixed_chain_and_missing_or_reordered_history(self):
        self.assertEqual(verify_chain(self.pending, self.history, self.key), self.history[-1]["owner_digest"])
        for history in (self.history[1:], self.history[::-1], self.history * 33):
            with self.assertRaises(ValueError):
                verify_chain(self.pending, history, self.key)

    def test_tampering_cannot_reassign_owner_or_extend_expiry(self):
        from cryptography.exceptions import InvalidSignature
        for field in ("owner_digest", "expires_at"):
            pending = copy.deepcopy(self.pending)
            pending[field] = "f" * 64 if field == "owner_digest" else "2099-01-01T00:00:00Z"
            with self.assertRaises(InvalidSignature):
                verify_chain(pending, self.history, self.key)
        history = copy.deepcopy(self.history)
        history[0]["owner_digest"] = "f" * 64
        with self.assertRaises(InvalidSignature):
            verify_chain(self.pending, history, self.key)

    def test_nanosecond_expiry_precision_is_retained(self):
        self.assertEqual(timestamp("2026-09-08T00:00:00.123456789Z") -
                         timestamp("2026-09-08T00:00:00.123456788Z"), 1)
