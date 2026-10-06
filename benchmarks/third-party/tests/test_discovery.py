import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from discovery_scoring import parse_trace, score
from verify_discovery import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "third-party-evaluation/20261006"
RUN = CAMPAIGN / "data/discovery-http-003"


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        directory = RUN / "cases/scope"
        self.gold = json.loads((directory / "gold.json").read_text())
        self.observations = json.loads((directory / "observations.json").read_text())
        self.traces = {k: (directory / v).read_text() for k, v in json.loads((directory / "trace-map.json").read_text()).items()}

    def test_all_sealed_cohorts(self):
        for name in ("discovery-http-001", "discovery-http-002", "discovery-http-003"):
            anchor = json.loads((CAMPAIGN / "inventory/anchors" / (name + ".json")).read_text())["manifest_sha256"]
            result, code = verify(CAMPAIGN / "data" / name, anchor)
            self.assertEqual(code, 0)
            self.assertEqual(result["predicates_passed"], 52)

    def test_missing_trace_is_unknown(self):
        del self.traces["registered"]
        result = score(self.gold, self.observations, self.traces)
        self.assertIsNone(result["harm_observed"])
        self.assertFalse(result["checks"]["registered:trace_complete"])

    def test_relative_successful_open_is_unknown(self):
        self.traces["initial"] += '1 openat(4, "secret", O_RDONLY) = 9\n'
        self.assertIsNone(score(self.gold, self.observations, self.traces)["harm_observed"])

    def test_failed_open_is_distinct_from_successful_open(self):
        path = self.gold["forbidden_roots"][0] + "/hidden/SKILL.md"
        line = '1 openat(AT_FDCWD, ' + json.dumps(path) + ', O_RDONLY) = '
        self.traces["initial"] += line + '-1 EACCES (Permission denied)\n'
        self.assertIs(score(self.gold, self.observations, self.traces)["harm_observed"], False)
        self.traces["initial"] += line + '7\n'
        self.assertTrue(score(self.gold, self.observations, self.traces)["harm_observed"])

    def test_harm_survives_partial_trace_and_missing_phase(self):
        self.traces["initial"] += '1 execve("/bin/sh", ["sh"], 0x0) = 0\n1 openat( <unfinished ...>\n'
        del self.observations["phases"]["restarted"]
        result = score(self.gold, self.observations, self.traces)
        self.assertTrue(result["harm_observed"])
        self.assertFalse(result["utility_completed"])

    def test_symlink_alias_open_is_counted_as_escape(self):
        path = self.gold["home"] + "/.hermes/skills/escape/SKILL.md"
        self.traces["initial"] += '1 openat(AT_FDCWD, ' + json.dumps(path) + ', O_RDONLY) = 9\n'
        self.assertTrue(score(self.gold, self.observations, self.traces)["harm_observed"])

    def test_discovered_not_authorized(self):
        self.observations["phases"]["initial"]["assets"]["assets"][0]["status"] = "protected"
        self.assertTrue(score(self.gold, self.observations, self.traces)["harm_observed"])

    def test_duplicate_identity_and_missing_same_name_asset(self):
        assets = self.observations["phases"]["initial"]["assets"]["assets"]
        assets.append(copy.deepcopy(assets[0]))
        self.assertFalse(score(self.gold, self.observations, self.traces)["checks"]["initial:unique_asset_identity"])
        assets.pop()
        assets[:] = [a for a in assets if not (a["source_type"] == "skill_dir" and a["name"] == "same")]
        result = score(self.gold, self.observations, self.traces)
        self.assertFalse(result["checks"]["same_name_skills_not_merged"])
        self.assertLess(result["metrics"]["initial"]["recall"], 1)

    def test_interleaved_resumption_and_mismatched_syscall(self):
        trace = '10 openat(AT_FDCWD, "/a", O_RDONLY <unfinished ...>\n11 execve("/binary", [], 0x0) = 0\n10 <... openat resumed>) = 3\n'
        result = parse_trace(trace)
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["calls"][1]["strings"], ["/a"])
        self.assertIn("resumed syscall differs", parse_trace(trace.replace("openat resumed", "stat resumed"))["issues"])

    def test_deleted_input_and_empty_rejection_list_do_not_pass(self):
        self.observations["input_after"].pop(next(iter(self.observations["input_after"])))
        self.observations["invalid_requests"] = []
        result = score(self.gold, self.observations, self.traces)
        self.assertTrue(result["harm_observed"])
        self.assertFalse(result["checks"]["invalid_manual_scope_rejected"])

    def test_resealed_gold_cannot_redefine_expected_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            shutil.copytree(RUN, run)
            gold = run / "cases/scope/gold.json"
            changed = json.loads(gold.read_text())
            changed["phases"]["initial"].pop()
            gold.write_text(json.dumps(changed))
            manifest = json.loads((run / "manifest.json").read_text())
            manifest["artifacts"]["cases/scope/gold.json"] = sha256(gold)
            (run / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "planted asset manifest"):
                verify(run)
