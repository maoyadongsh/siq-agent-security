"""Negative evidence checks use independent signed fixtures, not scenario labels."""
import copy
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from evidence import canonical, verify_global_revocation


class GlobalRevocationEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
        self.revocation = {"schema_version": "intent-revocation/v1", "intent_id": "intent-1",
                           "intent_digest": "a" * 64, "revoked_at": "2026-09-08T01:00:00Z",
                           "reason_code": "intent_revoked", "signing_schema": "local_canonical/v1"}
        self.revocation["signature"] = self.key.sign(canonical(self.revocation)).hex()
        self.checks = {"revocation": self.revocation, "before_receipt_ids": ["before1", "before2"],
                       "second_denied_receipt_id": "after2"}
        self.actions = {}
        for identity, session, action in (("before1", "s1", "allow"), ("before2", "s2", "allow"),
                                          ("after1", "s1", "deny"), ("after2", "s2", "deny"),
                                          ("benign", "s3", "allow")):
            self.actions[identity] = ({"record_type": "decision", "intent_id": "intent-1",
                                      "intent_digest": "a" * 64, "session_id": session,
                                      "action": action, "reason_code": "intent_revoked" if action == "deny" else "allowed"},
                                     self.key.public_key())
        self.actions["benign"][0]["intent_id"] = "other-intent"

    def check(self, checks=None, actions=None):
        verify_global_revocation(checks or self.checks, actions or self.actions, "after1", "benign")

    def test_valid_two_session_withdrawal(self):
        self.check()

    def test_signed_revocation_tampering_rejected(self):
        for field, value in (("intent_digest", "b" * 64), ("revoked_at", "2026-09-09T01:00:00Z"),
                             ("signature", "0" * 128)):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.checks)
                bad["revocation"][field] = value
                with self.assertRaises((InvalidSignature, ValueError)):
                    self.check(checks=bad)

    def test_missing_duplicate_or_unrelated_probes_rejected(self):
        for field, value in (("before_receipt_ids", ["before1", "before1"]),
                             ("before_receipt_ids", ["before1"]),
                             ("second_denied_receipt_id", "missing")):
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(self.checks)
                bad[field] = value
                with self.assertRaises((KeyError, ValueError)):
                    self.check(checks=bad)
        for identity, field, value in (("after2", "session_id", "s1"), ("before2", "action", "deny"),
                                       ("after2", "action", "allow"), ("after2", "reason_code", "intent_binding_revoked"),
                                       ("after1", "intent_digest", "b" * 64), ("benign", "intent_id", "intent-1")):
            with self.subTest(identity=identity, field=field):
                actions = {key: (dict(record), public) for key, (record, public) in self.actions.items()}
                actions[identity][0][field] = value
                with self.assertRaises(ValueError):
                    self.check(actions=actions)
