import copy
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research_skill_update_signature_review import INSTALLATION_SCHEMAS, verify_authority
from research_skill_install_verify import canonical


class InstallationSignatureTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()

    def signed(self, schema):
        doc = {'schema_version': schema, 'actor_id': 'fixture', 'candidate_revision': 2,
               'platform_changes': False, 'nested': {'signature': 'original-inner-signature'}}
        doc['signature'] = self.key.sign(canonical(doc)).hex()
        return doc

    def test_schema_specific_signature_without_grant_field(self):
        for schema in INSTALLATION_SCHEMAS:
            verify_authority(self.key.public_key(), self.signed(schema))

    def test_tampered_nested_signed_fact_is_rejected(self):
        for schema in INSTALLATION_SCHEMAS:
            doc = self.signed(schema); changed = copy.deepcopy(doc)
            changed['nested']['signature'] = 'substituted'
            with self.assertRaises(InvalidSignature):
                verify_authority(self.key.public_key(), changed)

    def test_unknown_schema_cannot_bypass_grant_context_rules(self):
        with self.assertRaises(ValueError):
            verify_authority(self.key.public_key(), self.signed('arbitrary/v1'))

    def test_installation_cannot_invent_signing_schema(self):
        doc = self.signed('local-skill-update-plan/v1'); doc['signing_schema'] = 'local_canonical/v1'
        with self.assertRaises(ValueError):
            verify_authority(self.key.public_key(), doc)


if __name__ == '__main__':
    unittest.main()
