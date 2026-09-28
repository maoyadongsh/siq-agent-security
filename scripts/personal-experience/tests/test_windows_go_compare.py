import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("windows_go_compare", Path(__file__).resolve().parents[1] / "windows_go_compare.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class WindowsGoComparisonTests(unittest.TestCase):
    def run_data(self, failed=(), skipped=()):
        events = [{"Package": "pkg", "Test": t, "Action": "fail"} for t in failed]
        events += [{"Package": "pkg", "Test": t, "Action": "skip"} for t in skipped]
        events += [{"Package": "pkg", "Action": "fail" if failed else "pass"}]
        return checker.summarize("\n".join(json.dumps(e) for e in events), int(bool(failed)))

    def test_baseline_failure_never_becomes_full_suite_pass(self):
        result = checker.compare(self.run_data(["TestOld"]), self.run_data(["TestOld"]))
        self.assertEqual(result["new_failures"], [])
        self.assertFalse(result["candidate_full_suite_passed"])
        self.assertEqual(result["workbuddy_native_acceptance"], "not_run")

    def test_new_failure_and_skip_remain_visible(self):
        result = checker.compare(self.run_data(["TestNew"], ["TestSkipped"]), self.run_data(["TestOld"]))
        self.assertEqual(result["new_failures"], ["pkg/TestNew"])
        self.assertEqual(result["new_skips"], ["pkg/TestSkipped"])

    def test_missing_build_or_tool_failure_cannot_pass(self):
        for raw, code in [("", 0), ('{"Package":"pkg","Action":"fail"}', 1), ('{"Package":"pkg","Action":"pass"}', 1)]:
            with self.subTest(raw=raw, code=code), self.assertRaises(ValueError):
                checker.summarize(raw, code)
        with self.assertRaises(ValueError):
            checker.compare(self.run_data(), {"packages": {"missing": "pass"}})

    def test_added_test_helper_is_reported_without_hiding_failures(self):
        for action in ("pass", "skip", "fail"):
            with self.subTest(action=action):
                events = [{"Package": "pkg", "Action": "pass"}]
                if action == "fail":
                    events.append({"Package": "new", "Test": "TestFailure", "Action": "fail"})
                events.append({"Package": "new", "Action": action})
                candidate = checker.summarize("\n".join(json.dumps(e) for e in events), int(action == "fail"))
                result = checker.compare(candidate, self.run_data())
                self.assertEqual(result["added_packages"], ["new"])
                self.assertEqual(result["new_failures"], ["new/TestFailure"] if action == "fail" else [])
                self.assertEqual(result["candidate_full_suite_passed"], action != "fail")

    def test_omitted_baseline_failure_is_not_a_pass(self):
        result = checker.compare(self.run_data(), self.run_data(["TestPOSIXOnly"]))
        self.assertEqual(result["baseline_failures_not_run"], ["pkg/TestPOSIXOnly"])

    def test_successful_rerun_is_distinct_from_omitted_test(self):
        candidate = checker.summarize(
            '\n'.join(json.dumps(e) for e in [
                {"Package": "pkg", "Test": "TestOld", "Action": "pass"},
                {"Package": "pkg", "Action": "pass"},
            ]), 0,
        )
        result = checker.compare(candidate, self.run_data(["TestOld"]))
        self.assertEqual(result["baseline_failures_not_run"], [])
