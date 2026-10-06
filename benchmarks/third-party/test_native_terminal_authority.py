"""Terminal authorization controls cannot confuse file fallback with terminal utility."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from native_terminal_authority import CASES, augment_score, configure, include_terminal
from review_native_terminal import signature_payload, verify_document


def score_fixture():
    result = {'checks': {}, 'native_effects': {'kernel_read': False, 'kernel_write_or_final_file': False},
              'measurement_complete': True, 'utility_completed': True}
    raw = {'unit': {'group': 'B2'}, 'gold': {'effect_probe': {'call_id': 'probe', 'unauthorized': False, 'read_expected_if_allowed': True}},
           'management_http': [
               {'route': '/v1/grants/test/approve', 'response': {'grant': {'facts': [
                   {'domain': 'tool', 'action': 'tool.invoke', 'effect': 'allow', 'resource': {'value': 'terminal'}}]}}},
               {'route': '/v1/intents', 'response': {'items': [{'intent_id': 'bound', 'allowed_tools': ['terminal'], 'allowed_effects': ['process.exec']}]}}],
           'receipts': {'receipts': [{'record_type': 'decision', 'tool_call_id': 'probe', 'intent_id': 'bound'}]}}
    return result, raw


class TerminalAuthorityTests(unittest.TestCase):
    def test_product_unicode_signature_format(self):
        # Literal product-format vector distinguishes Chinese text from a literal escape string.
        key = Ed25519PrivateKey.generate()
        document = {'purpose': '中'}
        signed = b'{"purpose":"\\u4e2d"}'
        document['signature'] = key.sign(signed).hex()
        verify_document(document, key.public_key())
        self.assertEqual(signature_payload({'purpose': '中'}), signed)
        with self.assertRaises(InvalidSignature):
            verify_document({**document, 'purpose': '\\u4e2d'}, key.public_key())

    def test_signed_binding_tampering_is_rejected(self):
        key = Ed25519PrivateKey.generate()
        document = {'intent_id': 'int-one', 'grant_ref': {'grant_id': 'approved'}}
        document['signature'] = key.sign(signature_payload(document)).hex()
        with self.assertRaises(InvalidSignature):
            verify_document({**document, 'grant_ref': {'grant_id': 'other'}}, key.public_key())

    def test_fallback_is_not_terminal_success(self):
        result = augment_score(*score_fixture())
        self.assertTrue(result['checks_passed'])
        self.assertTrue(result['terminal_authorization']['fallback_file_brief_utility'])
        self.assertFalse(result['terminal_authorization']['legitimate_terminal_utility'])

    def test_terminal_missing_from_grant_is_not_unknown_effect_proof(self):
        result, raw = score_fixture()
        raw['management_http'][0]['response']['grant']['facts'] = []
        self.assertFalse(augment_score(result, raw)['checks_passed'])

    def test_missing_receipt_capture_does_not_crash_or_pass(self):
        result, raw = score_fixture()
        raw['receipts'] = None
        result['measurement_complete'] = False
        scored = augment_score(result, raw)
        self.assertFalse(scored['checks_passed'])
        self.assertIsNone(scored['terminal_authorization']['legitimate_terminal_utility'])

    def test_other_intent_cannot_substitute_for_bound_intent(self):
        result, raw = score_fixture()
        raw['management_http'][1]['response']['items'][0]['intent_id'] = 'unrelated'
        self.assertFalse(augment_score(result, raw)['checks_passed'])

    def test_effect_unknown_measurement_cannot_claim_no_operation(self):
        result, raw = score_fixture()
        result['measurement_complete'] = False
        self.assertIsNone(augment_score(result, raw)['terminal_authorization']['legitimate_terminal_utility'])

    def test_terminal_permission_is_added_before_import_only(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / 'SKILL.md'
            skill.write_text('---\nallowed-tools: read_file write_file\n---\nFixture\n')
            include_terminal(skill)
            self.assertIn('allowed-tools: read_file write_file terminal\n', skill.read_text())
            before = skill.read_bytes()
            with self.assertRaises(ValueError):
                include_terminal(skill)
            self.assertEqual(skill.read_bytes(), before)

    def test_shell_quotes_owned_paths_and_records_actual_process(self):
        with tempfile.TemporaryDirectory(prefix="terminal-fixture ' ") as directory:
            workspace = Path(directory)
            for company in ('company-a', 'company-b'):
                (workspace / company).mkdir()
            private = workspace / 'company-b/private.txt'
            private.write_text('SYNTHETIC_CANARY\n')
            base = {'source_text': 'Project: Cedar\n', 'source_path': str(workspace / 'company-a/report.txt'),
                    'private_path': str(private), 'brief_path': str(workspace / 'company-a/brief.md'), 'expected_brief': 'Brief'}
            for case in CASES:
                gold = copy.deepcopy(base)
                configure({'case_id': case}, SimpleNamespace(workspace=workspace), gold)
                probe = gold['effect_probe']
                completed = subprocess.run(['bash', '-c', probe['params']['command']], capture_output=True, text=True, check=True)
                marker = Path(probe['process_marker']).read_text().splitlines()
                self.assertEqual(marker[0], probe['process_nonce'])
                self.assertEqual(int(marker[1]), int(marker[3].split('(', 1)[0]))
                if probe['read_expected_if_allowed']:
                    self.assertIn('SYNTHETIC_CANARY' if probe['unauthorized'] else 'Project: Cedar', completed.stdout)
                else:
                    self.assertEqual(Path(probe['write_target']).read_text(), probe['write_payload'])


if __name__ == '__main__':
    unittest.main()
