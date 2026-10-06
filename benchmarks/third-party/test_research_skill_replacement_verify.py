import copy
import hashlib
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research_skill_replacement_verify import OUTPUT, canonical, native_checks, resource_ref, signed


class ReplacementChecks(unittest.TestCase):
    def setUp(self):
        self.context = {'authority': {'grant_id': 'new-grant'}, 'context_id': 'new-context',
            'skill': {'content_hash': 'new-bytes'},
            'subject': {'agent_id': 'agent', 'session_id': 'new-session', 'task_id': 'new-task'}}
        self.records = []
        for tool, path in [('read_file', '/input'), ('write_file', '/output')]:
            row = {'record_type': 'decision', 'receipt_id': tool, 'tool': tool,
                'action': 'allow', 'effective_action': 'allow', 'resource_refs': resource_ref(path),
                'matched_grant_id': 'new-grant', 'agent_id': 'agent', 'session_id': 'new-session',
                'runtime_task_id': 'new-task', 'action_id': 'act-' + tool, 'tool_call_id': 'call-' + tool,
                'skill_attribution': {'context_id': 'new-context', 'content_hash': 'new-bytes', 'status': 'verified'}}
            if tool == 'write_file':
                row['params_digest'] = hashlib.sha256(canonical({'path': path, 'content': OUTPUT.decode()})).hexdigest()
            self.records += [row, dict(row, record_type='observation', receipt_id=tool + '-obs', decision_receipt_id=tool)]

    def review(self, *, records=None, context=None, raw=OUTPUT):
        return native_checks(self.records if records is None else records,
            self.context if context is None else context, input_path='/input', output_path='/output', output_bytes=raw)

    def test_consistent_new_version_effect(self):
        self.assertTrue(all(self.review().values()))

    def test_missing_or_wrong_effect_rejected(self):
        for raw in (None, b'', b'wrong'):
            self.assertFalse(self.review(raw=raw)['exact_output_bytes'])

    def test_stale_grant_and_context_rejected(self):
        for section, field in [('authority', 'grant_id'), ('skill', 'content_hash'), ('subject', 'session_id')]:
            context = copy.deepcopy(self.context); context[section][field] = 'old'
            self.assertFalse(self.review(context=context)['all_current_skill_attribution'])

    def test_unlinked_observation_rejected(self):
        records = copy.deepcopy(self.records); records[-1]['tool_call_id'] = 'other'
        self.assertFalse(self.review(records=records)['write_file_linked_observation'])
        self.assertFalse(self.review(records=records[:-1])['two_native_decisions_and_observations'])

    def test_parameter_or_target_substitution_rejected(self):
        for field, value, check in [('resource_refs', resource_ref('/wrong'), 'write_file_exact_target_allowed'),
                ('params_digest', '0' * 64, 'write_exact_parameters')]:
            records = copy.deepcopy(self.records); records[2][field] = value
            self.assertFalse(self.review(records=records)[check])

    def test_update_signature_covers_nested_claim(self):
        key = Ed25519PrivateKey.generate()
        doc = {'schema_version': 'local-skill-update-claim/v1', 'plan': {'candidate_grant_id': 'new'}}
        doc['signature'] = key.sign(canonical(doc)).hex()
        signed(key.public_key(), doc)
        doc['plan']['candidate_grant_id'] = 'old'
        with self.assertRaises(InvalidSignature):
            signed(key.public_key(), doc)

    def test_unknown_signing_contract_rejected(self):
        key = Ed25519PrivateKey.generate()
        doc = {'schema_version': 'unknown/v1'}
        doc['signature'] = key.sign(canonical(doc)).hex()
        with self.assertRaises(ValueError):
            signed(key.public_key(), doc)


if __name__ == '__main__':
    unittest.main()
