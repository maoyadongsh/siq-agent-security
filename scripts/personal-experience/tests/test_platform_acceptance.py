"""Synthetic verifier tests, NOT OpenClaw/Hermes/WorkBuddy native evidence."""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "platform_acceptance.py"
SPEC = importlib.util.spec_from_file_location("platform_acceptance", MODULE)
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)
SHA = "a" * 40


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = a.template(SHA)

    def review(self, bundle=None):
        return a.verify(self.bundle if bundle is None else bundle, self.root, SHA)

    def observed(self, index=0, name="normal_execution", method="native_cli"):
        row = self.bundle["cases"][index]
        row.update(os_version="fixture-OS-1", host_version="fixture-host-1", binary_sha256="b" * 64)
        if row["mode"] == "wsl2":
            row["guest_version"] = "fixture-guest-1"
        path = f"case-{index}-{name}.json"
        raw = json.dumps({"fixture_only": True, "case": index, "check": name}).encode()
        (self.root / path).write_bytes(raw)
        check = {"status": "pass", "method": method, "reason": None,
                 "evidence": [{"path": path, "sha256": hashlib.sha256(raw).hexdigest()}]}
        row["checks"][name] = check
        return row, check

    def invalid(self, code, bundle=None):
        with self.assertRaisesRegex(a.Invalid, f"^{code}$"):
            self.review(bundle)

    def test_template_preserves_all_candidate_targets(self):
        report = self.review()
        self.assertEqual(len(report["cases"]), 18)
        self.assertEqual(report["support_claim"], "not_assessed")
        self.assertEqual(report["evidence_files_checked"], 0)
        self.assertTrue(all(r["status"] == "needs_native_evidence" for r in report["cases"]))
        self.assertEqual(len([r for r in report["cases"] if r["target"].startswith("workbuddy/")]), 6)

    def test_single_native_result_cannot_close_matrix(self):
        self.observed()
        report = self.review()
        self.assertEqual(report["status"], "needs_native_evidence")
        self.assertEqual(report["cases"][0]["native_checks_recorded"], ["normal_execution"])

    def test_complete_synthetic_bundle_only_ready_for_review(self):
        for i, row in enumerate(self.bundle["cases"]):
            for name in a.CHECKS:
                self.observed(i, name, "native_desktop" if row["platform"] == "workbuddy" else "native_cli")
        report = self.review()
        self.assertEqual(report["status"], "ready_for_review")
        self.assertEqual(report["support_claim"], "not_assessed")
        self.assertNotIn("supported", report)

    def test_component_and_source_review_are_not_native(self):
        for method in ("component_fixture", "source_review"):
            with self.subTest(method=method):
                self.observed(method=method)
                self.assertIn("normal_execution", self.review()["cases"][0]["gaps"])

    def test_workbuddy_requires_own_desktop_evidence(self):
        self.observed(12, method="native_cli")
        self.assertIn("normal_execution", self.review()["cases"][12]["gaps"])
        self.observed(12, method="native_desktop")
        self.assertNotIn("normal_execution", self.review()["cases"][12]["gaps"])

    def test_codebuddy_cannot_substitute_workbuddy(self):
        self.bundle["cases"][12]["platform"] = "codebuddy"
        self.invalid("invalid_or_duplicate_target")

    def test_blocked_never_native_pass(self):
        _, check = self.observed()
        check.update(status="blocked", reason="host_capability_missing")
        self.assertIn("normal_execution", self.review()["cases"][0]["gaps"])

    def test_failure_with_evidence_remains_gap(self):
        _, check = self.observed()
        check.update(status="fail", reason="observed_failure")
        self.assertIn("normal_execution", self.review()["cases"][0]["gaps"])

    def test_missing_target_is_not_dropped(self):
        self.bundle["cases"].pop()
        self.invalid("incomplete_target_matrix")

    def test_duplicate_target_does_not_replace_missing_target(self):
        self.bundle["cases"][-1] = copy.deepcopy(self.bundle["cases"][0])
        self.invalid("invalid_or_duplicate_target")

    def test_missing_or_extra_capability_is_rejected(self):
        for change in ("missing", "extra"):
            bundle = copy.deepcopy(self.bundle)
            if change == "missing":
                del bundle["cases"][0]["checks"]["skill_attribution"]
            else:
                bundle["cases"][0]["checks"]["supported"] = True
            self.invalid("invalid_fields", bundle)

    def test_cross_candidate_evidence_rejected(self):
        self.bundle["candidate_sha"] = "c" * 40
        self.invalid("candidate_mismatch")

    def test_dirty_and_nonboolean_candidate_rejected(self):
        for value in (True, 0, "false", None):
            self.bundle["source_dirty"] = value
            self.invalid("dirty_candidate")

    def test_unknown_fields_cannot_carry_raw_data(self):
        self.bundle["token"] = "synthetic-sensitive-value"
        self.invalid("invalid_fields")

    def test_status_never_accepts_skip_as_pass(self):
        self.bundle["cases"][0]["checks"]["discovery"]["status"] = "skipped"
        self.invalid("invalid_status")

    def test_pass_requires_evidence(self):
        _, check = self.observed()
        check["evidence"] = []
        self.invalid("result_without_evidence")

    def test_pass_requires_execution_identity(self):
        row, _ = self.observed()
        row["host_version"] = None
        self.invalid("missing_execution_identity")

    def test_wsl_requires_guest_and_host_identity(self):
        row, _ = self.observed(1)
        row["guest_version"] = None
        self.invalid("missing_guest_identity")

    def test_native_cannot_be_relabelled_as_guest(self):
        self.bundle["cases"][0]["guest_version"] = "linux-fixture"
        self.invalid("unexpected_guest_version")

    def test_digest_mismatch_is_rejected(self):
        _, check = self.observed()
        check["evidence"][0]["sha256"] = "0" * 64
        self.invalid("evidence_digest_mismatch")

    def test_same_bytes_cannot_be_borrowed_by_other_platform(self):
        _, original = self.observed(0)
        row, _ = self.observed(6)
        row["checks"]["normal_execution"]["evidence"] = copy.deepcopy(original["evidence"])
        self.invalid("evidence_reused_across_cases")

    def test_relative_path_policy(self):
        _, check = self.observed()
        for value in ("../file.json", "/file.json", "C:/file.json", "a\\file.json",
                      "a//file.json", "./file.json", "file.json:stream", "NUL.json",
                      "dir./file.json", ".env", "x.py", "con/file.json"):
            with self.subTest(value=value):
                check["evidence"][0]["path"] = value
                with self.assertRaises(a.Invalid):
                    self.review()

    def test_referenced_program_is_not_executed(self):
        _, check = self.observed()
        raw = b'__import__("os").system("exit 99")'
        path = self.root / check["evidence"][0]["path"]
        path.write_bytes(raw)
        check["evidence"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
        self.assertEqual(self.review()["evidence_files_checked"], 1)

    def test_linked_file_rejected(self):
        _, check = self.observed()
        path = self.root / check["evidence"][0]["path"]
        target = self.root / "target.json"
        path.rename(target)
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest("symlink creation unavailable on this runner")
        self.invalid("evidence_link_refused")

    def test_linked_directory_rejected(self):
        _, check = self.observed()
        try:
            (self.root / "linked").symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable on this runner")
        check["evidence"][0]["path"] = "linked/" + check["evidence"][0]["path"]
        self.invalid("evidence_link_refused")

    def test_hardlink_rejected(self):
        _, check = self.observed()
        try:
            os.link(self.root / check["evidence"][0]["path"], self.root / "alias.json")
        except OSError:
            self.skipTest("hardlink creation unavailable on this runner")
        self.invalid("evidence_not_regular")

    def test_file_and_total_budgets(self):
        self.observed()
        with patch.object(a, "MAX_EVIDENCE", 1):
            self.invalid("evidence_budget_exceeded")
        with patch.object(a, "MAX_TOTAL", 1):
            self.invalid("evidence_budget_exceeded")

    def test_missing_file_refused(self):
        _, check = self.observed()
        (self.root / check["evidence"][0]["path"]).unlink()
        self.invalid("evidence_unreadable")

    def test_not_run_cannot_have_results(self):
        _, check = self.observed()
        check.update(status="not_run", reason="not_tested")
        self.invalid("invalid_not_run")

    def test_versions_cannot_contain_paths_or_urls(self):
        for value in ("https://user:secret@example.test", "/home/user", "line\nother", True):
            self.bundle["cases"][0]["host_version"] = value
            self.invalid("invalid_version")

    def test_duplicate_evidence_refused(self):
        _, check = self.observed()
        check["evidence"] *= 2
        self.invalid("duplicate_evidence_reference")

    def test_manifest_duplicate_json_keys(self):
        path = self.root / "duplicate.json"
        path.write_text('{"cases":[],"cases":[]}')
        with self.assertRaisesRegex(a.Invalid, "duplicate_json_key"):
            a.load_manifest(path)

    def test_manifest_invalid_and_oversized_inputs(self):
        path = self.root / "input.json"
        for raw in (b'{"x": NaN}', b'\xff', b'{', b'[' * 2000):
            path.write_bytes(raw)
            with self.assertRaises(a.Invalid):
                a.load_manifest(path)
        path.write_bytes(b" " * (a.MAX_MANIFEST + 1))
        with self.assertRaisesRegex(a.Invalid, "manifest_budget_exceeded"):
            a.load_manifest(path)

    def test_cli_exit_semantics_and_output_no_overwrite(self):
        manifest = self.root / "matrix.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(a.main(["init", "--candidate", SHA, "--out", str(manifest)]), 0)
            command = ["verify", str(manifest), "--evidence-root", str(self.root), "--candidate", SHA]
            self.assertEqual(a.main(command), 0)
            self.assertEqual(a.main([*command, "--require-native"]), 3)
        original = manifest.read_bytes()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(a.main(["init", "--candidate", SHA, "--out", str(manifest)]), 2)
        self.assertEqual(manifest.read_bytes(), original)
        self.assertNotIn(str(self.root), errors.getvalue())

    def test_invalid_report_does_not_create_output(self):
        path = self.root / "input.json"
        path.write_text('{"token":"synthetic-secret"}')
        output = self.root / "out.json"
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = a.main(["verify", str(path), "--evidence-root", str(self.root),
                           "--candidate", SHA, "--out", str(output)])
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())
        self.assertNotIn("synthetic-secret", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
