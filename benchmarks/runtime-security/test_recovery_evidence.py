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


class RevocationBindingTest(unittest.TestCase):
    def test_valid_signature_does_not_replace_owner_or_time_binding(self):
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from evidence import canonical
        from recovery_evidence import verify_revocation
        private = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
        recovery = {"owner_digest": "a" * 64, "recovered_at": "2026-09-08T00:00:00.123456789Z"}
        unsigned = {"schema_version": "effect-observer-revocation/v1", "owner_digest": "a" * 64,
                    "revoked_at": "2026-09-08T00:00:01Z", "signing_schema": "local_canonical/v1"}

        def seal(value):
            return value | {"signature": private.sign(canonical(value)).hex()}

        record = seal(unsigned)
        verify_revocation(record, recovery, private.public_key())
        for patch in ({"owner_digest": "b" * 64}, {"revoked_at": "2026-09-08T00:00:00.123456788Z"}):
            with self.assertRaises(ValueError):
                verify_revocation(seal(unsigned | patch), recovery, private.public_key())
        with self.assertRaises(InvalidSignature):
            verify_revocation(record | {"signature": "0" * 128}, recovery, private.public_key())
