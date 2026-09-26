"""source-freeze-preflight 合成仓库组合测试。

所有提交/合并只发生在临时合成 Git 仓库，绝不对真实项目提交；
不读取真实敏感文件来证明排除规则。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("source-freeze-preflight.py")
_SPEC = importlib.util.spec_from_file_location("source_freeze_preflight", SCRIPT)
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

SECRET_MARKER = "PLAINTEXT-SECRET-MARKER-7f3a"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "--no-optional-locks", *args],
        cwd=str(repo), capture_output=True, check=check,
    )


def make_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("alpha\n", encoding="utf-8")
    (repo / "old.txt").write_text("old\n", encoding="utf-8")
    (repo / "deleted.txt").write_text("gone\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def run_tool(repo: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--out", str(out), *extra],
        capture_output=True, check=False,
    )


def load_report(out: Path) -> dict:
    return json.loads(out.read_text(encoding="utf-8"))


class SourceFreezePreflightTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sfp-test-")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_worktree_enumeration_modified_added_deleted_renamed_special_paths(self):
        repo = make_repo(self.base)
        (repo / "a.txt").write_text("modified\n", encoding="utf-8")  # M
        (repo / "new.txt").write_text("added\n", encoding="utf-8")  # ??
        os.remove(repo / "deleted.txt")  # D
        _git(repo, "mv", "old.txt", "renamed.txt")  # R
        special = repo / "dir with space" / "中文 文件'tick.txt"
        special.parent.mkdir()
        special.write_text("special\n", encoding="utf-8")  # ?? 特殊字符路径

        out = self.base / "report.json"
        proc = run_tool(repo, out)
        self.assertEqual(proc.returncode, tool.EXIT_BLOCKED, proc.stderr)
        report = load_report(out)
        self.assertEqual(report["conclusion"], "blocked")
        self.assertFalse(report["signed"] or report["installable"] or report["published"])
        self.assertIsNotNone(report["head_commit"])
        self.assertEqual(report["branch"], "main")
        paths = {e["path"]: e["code"] for e in report["worktree"]["status_entries"]}
        self.assertEqual(paths["a.txt"], " M")
        self.assertEqual(paths["new.txt"], "??")
        self.assertEqual(paths["deleted.txt"], " D")
        self.assertEqual(paths["renamed.txt"], "R ")
        self.assertEqual(paths["dir with space/中文 文件'tick.txt"], "??")
        self.assertIn("renamed.txt", report["unreviewed"])
        # 报告是审阅状态快照，不是发行来源清单
        self.assertNotIn("files", report)
        self.assertEqual(report["schema_version"], tool.SCHEMA_VERSION)
        self.assertNotEqual(report["schema_version"], "siq-release-source-inventory/v1")

    def test_unresolved_conflict_blocks_pass(self):
        repo = make_repo(self.base)
        (repo / "conflict.txt").write_text("base\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", "add conflict file")
        _git(repo, "checkout", "-q", "-b", "side")
        (repo / "conflict.txt").write_text("side\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "side")
        _git(repo, "checkout", "-q", "main")
        (repo / "conflict.txt").write_text("main\n", encoding="utf-8")
        _git(repo, "commit", "-q", "-am", "main")
        _git(repo, "merge", "side", check=False)  # 留下未解决冲突

        out = self.base / "report.json"
        proc = run_tool(repo, out)
        self.assertNotEqual(proc.returncode, 0)
        report = load_report(out)
        self.assertEqual(report["conclusion"], "blocked")
        self.assertIn("conflict.txt", report["conflicts"])
        self.assertTrue(any("unresolved_conflicts" in r for r in report["blocking_reasons"]))

    def test_allowlist_verified_and_unreviewed_entries(self):
        repo = make_repo(self.base)
        target = repo / "reviewed" / "file.py"
        target.parent.mkdir()
        content = "print('reviewed')\n"
        target.write_text(content, encoding="utf-8")
        (repo / "untracked.txt").write_text("not reviewed\n", encoding="utf-8")
        allowlist = self.base / "allow.txt"
        allowlist.write_text("# comment\nreviewed/file.py\n", encoding="utf-8")

        out = self.base / "report.json"
        proc = run_tool(repo, out, "--allowlist", str(allowlist))
        self.assertEqual(proc.returncode, tool.EXIT_BLOCKED, proc.stderr)
        report = load_report(out)
        self.assertEqual(report["allowlist"]["requested"], 1)
        self.assertEqual(report["allowlist"]["verified"], 1)
        import hashlib
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.assertEqual(report["checked_files"][0]["sha256"], expected)
        self.assertEqual(report["checked_files"][0]["status"], "verified")
        self.assertIn("untracked.txt", report["unreviewed"])
        self.assertNotIn("reviewed/file.py", report["unreviewed"])

    def test_sensitive_symlink_escape_missing_rejected_without_content_leak(self):
        repo = make_repo(self.base)
        secret = repo / ".env"
        secret.write_text(f"KEY={SECRET_MARKER}\n", encoding="utf-8")
        private = repo / "server.private"
        private.write_text(SECRET_MARKER, encoding="utf-8")
        outside = self.base / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        link = repo / "linked.txt"
        os.symlink(outside, link)
        allowlist = self.base / "allow.txt"
        allowlist.write_text(
            ".env\nserver.private\nlinked.txt\n../outside.txt\n/etc/passwd\nghost.txt",
            encoding="utf-8",
        )

        out = self.base / "report.json"
        proc = run_tool(repo, out, "--allowlist", str(allowlist))
        self.assertNotEqual(proc.returncode, 0)
        report = load_report(out)
        statuses = {r["path"]: r["status"] for r in report["allowlist"]["results"]}
        self.assertEqual(statuses[".env"], "sensitive_excluded")
        self.assertEqual(statuses["server.private"], "sensitive_excluded")
        self.assertEqual(statuses["linked.txt"], "symlink_rejected")
        self.assertEqual(statuses["../outside.txt"], "invalid_path_rejected")
        self.assertEqual(statuses["/etc/passwd"], "invalid_path_rejected")
        self.assertEqual(statuses["ghost.txt"], "missing")
        for item in statuses.items():
            self.assertNotIn(SECRET_MARKER, str(item))
        self.assertNotIn(SECRET_MARKER, out.read_text(encoding="utf-8"))
        self.assertNotIn(SECRET_MARKER, proc.stdout.decode("utf-8", "replace"))
        self.assertTrue(any("allowlist_missing" in r for r in report["blocking_reasons"]))

    def test_size_limit_reports_unverified_without_digest(self):
        repo = make_repo(self.base)
        big = repo / "big.bin"
        body = ("B" * 32 + "\n") * 8  # 264 字节 > 上限 64
        big.write_text(body, encoding="utf-8")
        allowlist = self.base / "allow.txt"
        allowlist.write_text("big.bin\n", encoding="utf-8")
        out = self.base / "report.json"

        proc = run_tool(repo, out, "--allowlist", str(allowlist), "--max-content-bytes", "64")
        self.assertNotEqual(proc.returncode, 0)
        report = load_report(out)
        self.assertEqual(report["checked_files"], [])
        self.assertEqual(report["allowlist"]["results"][0]["status"], "too_large_unverified")
        self.assertIsNone(report["allowlist"]["results"][0]["sha256"])
        self.assertNotIn(body, out.read_text(encoding="utf-8"))

    def test_worktree_change_during_scan_is_unstable(self):
        repo = make_repo(self.base)
        out = self.base / "report.json"
        original = tool.git_state
        calls = {"n": 0}

        def fake_state(repo_path):
            calls["n"] += 1
            state = original(repo_path)
            if calls["n"] == 1:
                (repo_path / "a.txt").write_text("mutated mid-scan\n", encoding="utf-8")
            return state

        saved = tool.git_state
        tool.git_state = fake_state
        try:
            exit_code = tool.main(["--repo", str(repo), "--out", str(out)])
        finally:
            tool.git_state = saved
        self.assertEqual(exit_code, tool.EXIT_BLOCKED)
        report = load_report(out)
        self.assertEqual(report["conclusion"], "blocked")
        self.assertFalse(report["unstable"]["scan_stable"])
        self.assertTrue(any("worktree_changed_during_scan" in r for r in report["blocking_reasons"]))

    def test_report_refuses_overwrite_and_inside_repo_output(self):
        repo = make_repo(self.base)
        first = self.base / "report.json"
        self.assertEqual(run_tool(repo, first).returncode, 0)
        original_text = first.read_text(encoding="utf-8")
        second = run_tool(repo, first)  # 拒绝覆盖
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(first.read_text(encoding="utf-8"), original_text)

        inside_proc = run_tool(repo, repo / "report-inside.json")
        self.assertNotEqual(inside_proc.returncode, 0)
        self.assertFalse((repo / "report-inside.json").exists())

    def test_output_parent_symlink_cannot_write_inside_repo(self):
        repo = make_repo(self.base)
        alias = self.base / "alias"
        alias.symlink_to(repo, target_is_directory=True)
        result = run_tool(repo, alias / "new-report.json")
        self.assertEqual(result.returncode, tool.EXIT_REPORT_WRITE_FAILED)
        self.assertFalse((repo / "new-report.json").exists())

    def test_file_changed_after_hash_with_same_git_status_blocks(self):
        repo = make_repo(self.base)
        (repo / "a.txt").write_text("first dirty version")
        allow = self.base / "allow.txt"
        allow.write_text("a.txt\n")
        original = tool.git_state
        calls = 0

        def state(path):
            nonlocal calls
            calls += 1
            if calls == 2:
                (repo / "a.txt").write_text("second dirty version")
            return original(path)

        out = self.base / "report.json"
        with patch.object(tool, "git_state", state):
            result = tool.main(["--repo", str(repo), "--allowlist", str(allow), "--out", str(out)])
        self.assertEqual(result, tool.EXIT_BLOCKED)
        self.assertIn("a.txt", load_report(out)["unstable"]["files"])

    def test_swap_after_lstat_does_not_read_symlink_target(self):
        repo = make_repo(self.base)
        outside = self.base / "outside.txt"
        outside.write_text(SECRET_MARKER)
        original = tool.lstat_no_symlink

        def swap(root, pure):
            result = original(root, pure)
            (root / pure).unlink()
            (root / pure).symlink_to(outside)
            return result

        with patch.object(tool, "lstat_no_symlink", swap):
            result = tool.verify_allowlist_file(repo, "a.txt", 1024)
        self.assertIsNone(result["sha256"])
        self.assertNotEqual(result["status"], "verified")


if __name__ == "__main__":
    unittest.main()
