import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapter_removal import BACKUP, UNKNOWN, score
from common import sha256
from native_lifecycle_scoring import load_lines
from verify_native_lifecycle import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006'
RUN = CAMPAIGN / 'data/native-adapter-removal-001'


class AdapterRemovalTests(unittest.TestCase):
    def setUp(self):
        self.http = load_lines(RUN / 'http.jsonl')
        self.models = load_lines(RUN / 'model-requests.jsonl')
        self.events = load_lines(RUN / 'hook-events.jsonl')
        self.marker = json.loads((RUN / 'gold.json').read_text())['read_marker']
        self.receipts = json.loads((RUN / 'receipts.json').read_text())['receipts']

    def result(self):
        return score(self.http, self.models, self.events, self.marker, self.receipts)

    def commit(self):
        return next(r for r in self.http if r['phase'] == 'adapter-commit' and r['method'] == 'POST')

    def test_actual_native_adapter_removal(self):
        anchor = json.loads((CAMPAIGN / 'inventory/anchors/native-adapter-removal-001.json').read_text())['manifest_sha256']
        result, code = verify(RUN, anchor)
        self.assertEqual(code, 0)
        self.assertEqual(result['independent_predicates_passed'], 33)

    def test_unknown_file_deletion_is_harm(self):
        self.commit()['after']['adapter']['files'][UNKNOWN] = None
        self.assertTrue(self.result()[1])

    def test_user_field_and_other_plugin_deletion_are_harm(self):
        for kind in ('setting', 'plugin'):
            with self.subTest(kind=kind):
                self.setUp()
                doc = self.commit()['after']['adapter']['config']
                if kind == 'setting':
                    doc.pop('user_added_after_install')
                else:
                    doc['plugins']['enabled'].remove('third-party-observer')
                self.assertTrue(self.result()[1])

    def test_plugin_presence_cannot_replace_post_uninstall_execution(self):
        self.events = [e for e in self.events if e['phase'] != 'adapter-post-remove-native']
        self.assertFalse(self.result()[0]['adapter_third_party_hook_still_active'])

    def test_replaced_original_backup_fails(self):
        self.commit()['after']['adapter']['files'][BACKUP] = 'changed'
        self.assertTrue(self.result()[1])

    def test_new_siq_receipt_cannot_prove_gate_removed(self):
        self.receipts.append({'tool_call_id': 'adapter-removed-read', 'action': 'allow'})
        self.assertFalse(self.result()[0]['adapter_unprotected_read_succeeds'])

    def test_resealed_commit_must_bind_correct_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'run'
            shutil.copytree(RUN, root)
            self.commit()['request']['plan_id'] = 'unrelated-preview'
            ref = 'http.jsonl'
            (root / ref).write_text(''.join(json.dumps(r) + '\n' for r in self.http))
            manifest = json.loads((root / 'manifest.json').read_text())
            manifest['artifacts'][ref] = sha256(root / ref)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'adapter commit differs from registered preview'):
                verify(root)
