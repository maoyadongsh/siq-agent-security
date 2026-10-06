import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from cryptography.exceptions import InvalidSignature
from verify_product_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006'
RUN = CAMPAIGN / 'data/provenance-bindings-002'


class BindingTests(unittest.TestCase):
    def test_fixed_and_original_outcomes_preserved(self):
        for name, expected, passed in [('provenance-bindings-001', 1, 11), ('provenance-bindings-002', 0, 12)]:
            root = CAMPAIGN / 'data' / name
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, expected)
            self.assertEqual(result['first_attempt_pass'], passed)
            self.assertEqual(result['signed_completed_attempts_checked'], 12)

    def check_mutation(self, relative, mutate):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'run'
            shutil.copytree(RUN, root)
            path = root / relative
            value = json.loads(path.read_text())
            mutate(value)
            path.write_text(json.dumps(value))
            manifest_path = root / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['artifacts'][relative] = sha256(path)
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises((ValueError, InvalidSignature)):
                verify(root, sha256(manifest_path))

    def test_substituted_receiver_request_rejected_after_reseal(self):
        self.check_mutation('attempts/PB02.recipient.benign/1/request.json', lambda v: v['params'].update(recipient='attacker-team'))

    def test_forged_signed_source_scope_rejected_after_reseal(self):
        self.check_mutation('attempts/PB04.task.adversarial/1/authority.json', lambda v: v['assertion']['scope'].update(task_id='task-binding'))

    def test_missing_prerequisite_source_rejected_after_reseal(self):
        self.check_mutation('attempts/PB02.body.benign/1/authority.json', lambda v: v.update(additional_assertions=[]))

    def test_signed_parameter_provenance_cannot_be_relabelled(self):
        self.check_mutation('attempts/PB02.body.benign/1/request.json', lambda v: v['parameter_provenance'][0].update(provenance_refs=['binding-recipient']))

    def test_binding_registration_cannot_be_removed(self):
        self.check_mutation('protocol.json', lambda v: v.update(sample_set=None))
