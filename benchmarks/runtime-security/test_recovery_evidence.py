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


class PendingActionBindingTest(unittest.TestCase):
    def test_signed_chain_and_scope_are_both_required(self):
        import base64
        import hashlib

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from evidence import canonical, verify_receipt_bundles
        from recovery_evidence import verify_pending_action
        private = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
        scope = {"platform": "hermes", "session_id": "s", "agent_id": "a", "task_id": "t"}
        pending = {"scope": scope, "action_id": "act", "decision_receipt_id": "rcp", "before": {
            "captured_at": "2026-09-08T00:00:01Z", "resource_ref": "filesystem:sha256:" + "a" * 64}}
        decision = {**scope, "record_type": "decision", "action": "allow", "action_id": "act",
                    "receipt_id": "rcp", "authority_status": "valid", "effects": ["file.write"],
                    "resource_refs": [{"domain": "filesystem", "digest": "a" * 64}],
                    "issued_at": "2026-09-08T00:00:00Z", "chain_id": "local", "seq": 0, "prev_hash": "0" * 64}
        digest = hashlib.sha256(canonical(decision)).hexdigest()
        record = decision | {"hash": digest, "sig": private.sign(digest.encode()).hex()}
        bundle = {"public_key": base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
                  "receipts": [record]}
        actions, count = verify_receipt_bundles([bundle])
        self.assertEqual(count, 1)
        verify_pending_action(pending, actions["rcp"][0])
        for patch in ({"action": "deny"}, {"task_id": "other"}, {"session_id": "other"},
                      {"agent_id": "other"}, {"action_id": "other"}, {"resource_refs": []},
                      {"issued_at": "2026-09-08T00:00:02Z"}, {"effects": ["file.read"]}):
            with self.assertRaises(ValueError):
                verify_pending_action(pending, decision | patch)
        altered = copy.deepcopy(bundle)
        altered["receipts"][0]["action"] = "deny"
        with self.assertRaises(ValueError):
            verify_receipt_bundles([altered])
        with self.assertRaises(ValueError):
            verify_receipt_bundles([bundle, bundle])
