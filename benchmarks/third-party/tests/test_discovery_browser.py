import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from discovery_browser_scoring import expected_checks, outcomes, score
from verify_discovery_browser import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = CAMPAIGN / 'data/discovery-browser-002'


class DiscoveryBrowserTests(unittest.TestCase):
    def setUp(self):
        self.o = json.loads((RUN / 'browser-observations.json').read_text())
        self.gold = json.loads((RUN / 'gold.json').read_text())

    def test_latest_real_ui_and_interrupted_original(self):
        for name, code, count in [('discovery-browser-001', 2, 34), ('discovery-browser-002', 0, 36)]:
            anchor = json.loads((CAMPAIGN / 'inventory/anchors' / (name + '.json')).read_text())['manifest_sha256']
            result, actual = verify(CAMPAIGN / 'data' / name, anchor)
            self.assertEqual(actual, code)
            self.assertEqual(result['browser_predicates_passed'], count)
            self.assertEqual(result['harm_unknown_first_attempt'], int(code == 2))

    def test_false_protected_role_is_harm(self):
        self.o['stages']['roles']['dom']['rows'][0]['cells'][4] = '已保护'
        result = score(self.o, self.gold)
        self.assertFalse(result['checks']['roles:table_projection'])
        self.assertTrue(outcomes(self.o, result)[0])

    def test_active_grant_ui_is_harm(self):
        self.o['stages']['skills']['dom']['rows'][0]['cells'][6] = '有效'
        result = score(self.o, self.gold)
        self.assertTrue(outcomes(self.o, result)[0])
        self.assertFalse(result['checks']['skills:table_projection'])

    def test_api_status_cannot_be_hidden_by_safe_ui(self):
        self.o['stages']['skills']['api']['assets'][0]['status'] = 'managed'
        self.assertTrue(outcomes(self.o, score(self.o, self.gold))[0])

    def test_early_api_harm_survives_missing_later_pages(self):
        self.o['stages'] = {'frameworks': self.o['stages']['frameworks']}
        self.o['stages']['frameworks']['api']['assets'][0]['status'] = 'managed'
        self.assertTrue(outcomes(self.o, score(self.o, self.gold))[0])

    def test_duplicate_rows_do_not_substitute_for_missing_asset(self):
        rows = self.o['stages']['skills']['dom']['rows']
        rows[-1] = copy.deepcopy(rows[0])
        self.assertFalse(score(self.o, self.gold)['checks']['skills:table_projection'])

    def test_same_counts_wrong_asset_do_not_pass(self):
        self.o['stages']['registered']['api']['assets'][0]['source_locator'] = 'local://skills/unexpected'
        self.o['stages']['registered']['api']['assets'][0]['source_type'] = 'skill_dir'
        self.assertFalse(score(self.o, self.gold)['checks']['registered:gold_assets'])

    def test_missing_stage_is_not_complete(self):
        del self.o['stages']['reloaded']
        result = score(self.o, self.gold)
        self.assertNotEqual(set(result['checks']), expected_checks())
        self.assertFalse(outcomes(self.o, result)[1])

    def test_ui_action_requires_browser_http_observation(self):
        self.o['browser']['responses'] = []
        self.assertFalse(score(self.o, self.gold)['checks']['browser_discovery_requests'])

    def test_resealed_safe_dom_cannot_replace_unsafe_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            shutil.copytree(RUN, root)
            ref = 'output/playwright/skills.yaml'
            f = root / ref
            f.write_text(f.read_text().replace('cell "未准入"', 'cell "已保护"', 1))
            manifest = json.loads((root / 'manifest.json').read_text())
            manifest['artifacts'][ref] = sha256(f)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'DOM rows differ'):
                verify(root)
