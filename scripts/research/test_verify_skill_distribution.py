import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import verify_skill_distribution as verifier


class SkillDistributionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "SKILL.md").write_bytes(b"# Skill\n")
        (self.source / "scripts").mkdir()
        (self.source / "scripts" / "probe.py").write_bytes(b"raise RuntimeError('never execute')\n")
        self.installed = self.base / "installed"
        shutil.copytree(self.source, self.installed)

    def verify(self):
        return verifier.verify_distribution(self.source, self.installed)

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(Path(verifier.__file__)), "--source", str(self.source),
             "--installed", str(self.installed), *map(str, args)],
            capture_output=True, text=True, timeout=5,
        )

    def test_exact_copy_passes_with_stable_digest_only_report(self):
        report = self.verify()
        self.assertEqual(report["result"], "passed")
        self.assertEqual(report["scope"], "distribution_only")
        self.assertEqual(report["source"], report["installed"])
        self.assertEqual(report["differences"], [])
        self.assertEqual(report, self.verify())
        snapshot = report["source"]
        self.assertEqual(snapshot["file_count"], 2)
        self.assertEqual(snapshot["files"][0]["path"], "SKILL.md")
        self.assertEqual(snapshot["files"][0]["sha256"], hashlib.sha256(b"# Skill\n").hexdigest())
        self.assertEqual(snapshot["files"][0]["bytes"], 8)
        encoded = json.dumps(report)
        self.assertNotIn(str(self.base), encoded)
        self.assertNotIn("never execute", encoded)
        self.assertNotIn("# Skill", encoded)

    def test_changed_bytes_fail(self):
        (self.installed / "SKILL.md").write_bytes(b"# Tampered\n")
        report = self.verify()
        self.assertEqual(report["result"], "failed")
        self.assertIn({"path": "SKILL.md", "category": "changed"}, report["differences"])

    def test_missing_and_extra_files_fail(self):
        (self.installed / "scripts" / "probe.py").unlink()
        (self.installed / "extra").write_bytes(b"extra")
        report = self.verify()
        self.assertEqual(report["result"], "failed")
        self.assertEqual(report["differences"], [
            {"path": "extra", "category": "extra"},
            {"path": "scripts/probe.py", "category": "missing"},
        ])

    def test_modified_content_and_manifest_still_fail(self):
        for tree in (self.source, self.installed):
            (tree / "manifest.json").write_text('{"sha256":"original"}')
        (self.installed / "SKILL.md").write_bytes(b"replacement")
        (self.installed / "manifest.json").write_text('{"sha256":"replacement"}')
        report = self.verify()
        self.assertEqual(report["result"], "failed")
        self.assertEqual([item["path"] for item in report["differences"]],
                         ["SKILL.md", "manifest.json"])

    def test_hidden_metadata_is_compared(self):
        (self.installed / ".git").mkdir()
        (self.installed / ".git" / "config").write_bytes(b"extra")
        self.assertEqual(self.verify()["differences"],
                         [{"path": ".git/config", "category": "extra"}])

    def test_skill_document_is_required_even_if_both_trees_match(self):
        for tree in (self.source, self.installed):
            (tree / "SKILL.md").unlink()
        report = self.verify()
        self.assertEqual(report["result"], "failed")
        self.assertEqual({error["category"] for error in report["errors"]}, {"missing_skill"})

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlink_file_and_directory_are_rejected(self):
        for target in ("SKILL.md", "scripts"):
            with self.subTest(target=target):
                link = self.installed / "linked"
                link.symlink_to(target, target_is_directory=target == "scripts")
                report = self.verify()
                self.assertEqual(report["result"], "failed")
                self.assertEqual(report["errors"][0]["category"], "symlink")
                link.unlink()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_input_root_symlink_is_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.installed, target_is_directory=True)
        report = verifier.verify_distribution(self.source, alias)
        self.assertEqual(report["result"], "failed")
        self.assertEqual(report["errors"][0]["category"], "symlink")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlink_ancestor_is_supported(self):
        alias = self.base / "alias"
        alias.symlink_to(self.base, target_is_directory=True)
        self.assertEqual(verifier.verify_distribution(
            alias / "source", alias / "installed")["result"], "passed")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_fifo_is_rejected_without_blocking(self):
        os.mkfifo(self.installed / "pipe")
        output = self.base / "report.json"
        process = self.cli("--out", output)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(json.loads(output.read_text())["errors"][0]["category"], "nonregular")

    def test_file_and_byte_budgets_accept_boundary_and_reject_plus_one(self):
        tree = self.base / "budget"
        tree.mkdir()
        (tree / "SKILL.md").write_bytes(b"1234")
        snapshot = verifier.snapshot_tree(tree, max_files=1, max_bytes=4)
        self.assertEqual(snapshot["total_bytes"], 4)
        (tree / "SKILL.md").write_bytes(b"12345")
        with self.assertRaisesRegex(verifier.DistributionError, "byte_limit"):
            verifier.snapshot_tree(tree, max_files=1, max_bytes=4)
        (tree / "SKILL.md").write_bytes(b"1234")
        (tree / "extra").write_bytes(b"")
        with self.assertRaisesRegex(verifier.DistributionError, "file_limit"):
            verifier.snapshot_tree(tree, max_files=1, max_bytes=4)

    def test_empty_directories_have_a_traversal_budget(self):
        tree = self.base / "budget"
        tree.mkdir()
        (tree / "SKILL.md").write_bytes(b"")
        (tree / "empty1").mkdir()
        verifier.snapshot_tree(tree, max_files=1)
        (tree / "empty2").mkdir()
        with self.assertRaisesRegex(verifier.DistributionError, "entry_limit"):
            verifier.snapshot_tree(tree, max_files=1)

    def test_depth_boundary_and_plus_one(self):
        verifier.snapshot_tree(self.source, max_depth=2)
        with self.assertRaisesRegex(verifier.DistributionError, "depth_limit"):
            verifier.snapshot_tree(self.source, max_depth=1)

    def test_control_character_paths_are_rejected_without_echoing_name(self):
        for character in ("\n", "\x01", "\x7f", "\x85"):
            with self.subTest(character=repr(character)):
                path = self.installed / ("private" + character + "name")
                path.write_bytes(b"")
                report = self.verify()
                self.assertEqual(report["errors"][0]["category"], "invalid_path")
                self.assertNotIn("private", json.dumps(report))
                path.unlink()

    @unittest.skipUnless(os.name == "posix", "POSIX execute bits only")
    def test_each_execute_bit_is_compared(self):
        left = self.source / "scripts" / "probe.py"
        right = self.installed / "scripts" / "probe.py"
        left.chmod(0o700)
        right.chmod(0o711)
        self.assertEqual(self.verify()["result"], "failed")
        right.chmod(0o700)
        self.assertEqual(self.verify()["result"], "passed")

    @unittest.skipUnless(os.name == "posix", "POSIX modes only")
    def test_other_permission_bits_do_not_affect_distribution_equality(self):
        (self.source / "SKILL.md").chmod(0o600)
        (self.installed / "SKILL.md").chmod(0o644)
        self.assertEqual(self.verify()["result"], "passed")

    def test_content_is_never_executed_or_imported(self):
        marker = self.base / "executed"
        code = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        for tree in (self.source, self.installed):
            (tree / "danger.py").write_text(code)
        self.assertEqual(self.verify()["result"], "passed")
        self.assertFalse(marker.exists())

    def test_changed_file_during_read_is_rejected(self):
        original_read = os.read
        changed = False

        def mutate_after_read(fd, size):
            nonlocal changed
            content = original_read(fd, size)
            if not changed and content:
                changed = True
                (self.source / "SKILL.md").write_bytes(b"different bytes")
            return content

        with mock.patch.object(verifier.os, "read", side_effect=mutate_after_read):
            with self.assertRaisesRegex(verifier.DistributionError, "tree_changed"):
                verifier.snapshot_tree(self.source)

    def test_invalid_limits_are_rejected(self):
        for limits in ({"max_files": 0}, {"max_bytes": -1}, {"max_depth": -1}):
            with self.subTest(limits=limits):
                with self.assertRaisesRegex(verifier.DistributionError, "invalid_limit"):
                    verifier.snapshot_tree(self.source, **limits)

    def test_cli_creates_new_report(self):
        output = self.base / "report.json"
        process = self.cli("--out", output)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(output.read_text())["result"], "passed")
        self.assertNotIn(str(self.base), process.stdout + process.stderr)

    def test_cli_does_not_overwrite_existing_report(self):
        output = self.base / "report.json"
        output.write_bytes(b"previous evidence")
        process = self.cli("--out", output)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("output_exists", process.stderr)
        self.assertEqual(output.read_bytes(), b"previous evidence")

    def test_cli_rejects_output_inside_either_input_tree(self):
        for tree in (self.source, self.installed):
            with self.subTest(tree=tree.name):
                output = tree / "report.json"
                process = self.cli("--out", output)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("output_in_input", process.stderr)
                self.assertFalse(output.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_cli_rejects_output_via_symlink_into_input_tree(self):
        alias = self.base / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        process = self.cli("--out", alias / "report.json")
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("output_in_input", process.stderr)
        self.assertFalse((self.source / "report.json").exists())

    def test_cli_missing_input_is_redacted(self):
        shutil.rmtree(self.installed)
        output = self.base / "report.json"
        process = self.cli("--out", output)
        self.assertNotEqual(process.returncode, 0)
        report = json.loads(output.read_text())
        self.assertEqual(report["errors"][0]["category"], "io_error")
        self.assertNotIn(str(self.base), output.read_text() + process.stderr)


if __name__ == "__main__":
    unittest.main()
