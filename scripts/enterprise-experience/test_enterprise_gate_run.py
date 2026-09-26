"""enterprise-gate-run 合成仓库测试。

全部用例只作用于临时合成目录；**不运行真实门禁**（不跑后端/前端/Go 真套件），
只验证执行器的判定、留证与"不可跑项绝不算通过"的诚实性。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("enterprise-gate-run.py")
_SPEC = importlib.util.spec_from_file_location("enterprise_gate_run", SCRIPT)
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

HAS_GOFMT = shutil.which("gofmt") is not None


def make_git_repo(base: Path, name: str = "repo") -> Path:
    root = base / name
    root.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for args in (("init", "-q"), ("commit", "-q", "--allow-empty", "-m", "init")):
        subprocess.run(["git", *args], cwd=str(root), env=env, capture_output=True, check=True)
    return root


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def synthetic_gates(statuses: dict) -> list:
    """把 id→期望结果 映射成合成门禁（用 git 命令制造真实退出码）。"""
    gates = []
    for gate_id, expected in statuses.items():
        if expected == "passed":
            gates.append({"id": gate_id, "kind": "command", "argv": ["git", "rev-parse", "HEAD"]})
        elif expected == "failed":
            gates.append({"id": gate_id, "kind": "command", "argv": ["git", "rev-parse", "no-such-ref"]})
        else:
            gates.append({"id": gate_id, "kind": "command", "argv": ["no-such-binary-xyz"]})
    return gates


class GateRunTest(unittest.TestCase):
    def test_command_gate_statuses_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            build = Path(tmp) / "build"
            build.mkdir()
            report = tool.run_gates(repo, synthetic_gates(
                {"ok": "passed", "bad": "failed", "missing": "blocked"}), build)
            by_id = {r["id"]: r for r in report["gates"]}
            self.assertEqual(by_id["ok"]["status"], "passed")
            self.assertEqual(by_id["ok"]["exit_code"], 0)
            self.assertEqual(by_id["bad"]["status"], "failed")
            self.assertEqual(by_id["bad"]["detail"], "exit_code=128")
            self.assertEqual(by_id["missing"]["status"], "blocked")
            self.assertIn("executable_not_found", by_id["missing"]["detail"])
            self.assertEqual(report["failed_gate_ids"], ["bad"])
            self.assertEqual(report["blocked_gate_ids"], ["missing"])

    def test_declared_unavailable_gates_always_keep_conclusion_off_green(self):
        """即使全部可跑门禁通过，只要仍有登记在案的不可跑项，结论就不能是绿色。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            build = Path(tmp) / "build"
            build.mkdir()
            report = tool.run_gates(repo, synthetic_gates({"ok": "passed"}), build)
            self.assertTrue(report["skipped_gate_ids"])
            self.assertEqual(report["conclusion"], "gates_incomplete")
            self.assertIn("skipped_gate_is_never_a_pass", report["not_evidence_of"])
            for item in report["skipped_gates"]:
                self.assertEqual(item["status"], "skipped")
                self.assertTrue(item["reason"])

    def test_timeout_is_a_failure_never_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            gate = {"id": "slow", "kind": "command",
                    "argv": [sys.executable, "-c", "import time; time.sleep(30)"], "timeout": 1}
            outcome = tool.run_command(repo, gate)
            self.assertEqual(outcome["status"], "failed")
            self.assertEqual(outcome["detail"], "timeout")

    def test_output_tail_is_bounded_and_truncation_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            gate = {"id": "loud", "kind": "command",
                    "argv": [sys.executable, "-c", "print('x' * 50000)"]}
            outcome = tool.run_command(repo, gate)
            self.assertEqual(outcome["status"], "passed")
            self.assertGreater(outcome["stdout"]["bytes"], tool.MAX_TAIL_CHARS)
            self.assertTrue(outcome["stdout"]["tail_truncated"])
            self.assertEqual(len(outcome["stdout"]["tail"]), tool.MAX_TAIL_CHARS)

    @unittest.skipUnless(HAS_GOFMT, "gofmt 不可用")
    def test_gofmt_ignores_untracked_files_but_flags_tracked_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            write(repo, "mod/good.go", "package mod\n")
            write(repo, "mod/scratch/bad.go", "package scratch\nfunc  x( ){}\n")
            outcome = tool.check_gofmt(repo, "mod")
            self.assertEqual(outcome["status"], "passed")
            self.assertEqual(outcome["evidence"]["reported_untracked_ignored"],
                             ["scratch/bad.go"])

            # 同一份未格式化文件一旦被跟踪，就必须失败。
            subprocess.run(["git", "add", "-f", "mod/scratch/bad.go"], cwd=str(repo),
                           capture_output=True, check=True)
            failed = tool.check_gofmt(repo, "mod")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["detail"], "unformatted_tracked_files")
            self.assertEqual(failed["evidence"]["offenders"], ["scratch/bad.go"])

    def test_rulepack_copies_must_be_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            write(repo, tool.RULEPACK_PYTHON, '{"v": 1}\n')
            write(repo, tool.RULEPACK_GO, '{"v": 1}\n')
            self.assertEqual(tool.check_rulepack_identity(repo)["status"], "passed")

            write(repo, tool.RULEPACK_GO, '{"v": 2}\n')
            drifted = tool.check_rulepack_identity(repo)
            self.assertEqual(drifted["status"], "failed")
            self.assertEqual(drifted["detail"], "rulepack_copies_differ")
            self.assertEqual(len(set(drifted["evidence"]["sha256"].values())), 2)

            (repo / tool.RULEPACK_GO).unlink()
            self.assertEqual(tool.check_rulepack_identity(repo)["status"], "blocked")

    def test_production_bundle_dev_identity_is_asserted_not_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dist"
            (out / "assets").mkdir(parents=True)
            (out / "assets" / "app.js").write_text("const x = 1;", encoding="utf-8")
            clean = tool.check_prod_bundle_has_no_dev_identity(out)
            self.assertEqual(clean["status"], "passed")
            self.assertEqual(clean["evidence"]["files_scanned"], 1)

            (out / "assets" / "leak.js").write_text('h["X-Dev-Tenant-Id"]="tnt-A"', encoding="utf-8")
            leaked = tool.check_prod_bundle_has_no_dev_identity(out)
            self.assertEqual(leaked["status"], "failed")
            self.assertEqual(leaked["detail"], "dev_identity_in_production_bundle")
            self.assertEqual(leaked["evidence"]["hits"]["X-Dev-Tenant-Id"], ["assets/leak.js"])

            self.assertEqual(
                tool.check_prod_bundle_has_no_dev_identity(Path(tmp) / "missing")["status"],
                "blocked")

    def test_report_is_created_exclusively(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "report.json"
            tool.write_report_exclusive(out, {"ok": True})
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), {"ok": True})
            with self.assertRaises(RuntimeError):
                tool.write_report_exclusive(out, {"ok": False})
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), {"ok": True})

    def test_main_end_to_end_partial_run_is_never_a_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"
            builder = lambda _repo, _build: synthetic_gates({"ok": "passed"})
            code = tool.main(["--repo", str(repo), "--out", str(out), "--only", "ok"],
                             gate_builder=builder)
            self.assertEqual(code, tool.EXIT_NOT_GREEN)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["conclusion"], "partial_run_not_a_gate")
            self.assertEqual(report["selected_only"], ["ok"])
            self.assertEqual(report["schema_version"], tool.SCHEMA_VERSION)
            self.assertTrue(report["head_sha"])

    def test_main_full_synthetic_pass_is_still_incomplete_and_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"
            builder = lambda _repo, _build: synthetic_gates({"ok": "passed"})
            code = tool.main(["--repo", str(repo), "--out", str(out)], gate_builder=builder)
            self.assertEqual(code, tool.EXIT_NOT_GREEN)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["conclusion"],
                             "gates_incomplete")

    def test_main_rejects_report_path_inside_repo_and_unknown_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            inside = repo / "report.json"
            builder = lambda _repo, _build: synthetic_gates({"ok": "passed"})
            with self.assertRaises(SystemExit) as ctx:
                tool.main(["--repo", str(repo), "--out", str(inside)], gate_builder=builder)
            self.assertEqual(ctx.exception.code, tool.EXIT_USAGE)
            self.assertFalse(inside.exists())

            outside = Path(tmp) / "r.json"
            with self.assertRaises(SystemExit) as ctx:
                tool.main(["--repo", str(repo), "--out", str(outside), "--only", "nope"],
                          gate_builder=builder)
            self.assertEqual(ctx.exception.code, tool.EXIT_USAGE)
            self.assertFalse(outside.exists())

    def test_main_reports_write_failure_without_touching_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"
            out.write_text("{}", encoding="utf-8")
            builder = lambda _repo, _build: synthetic_gates({"ok": "passed"})
            code = tool.main(["--repo", str(repo), "--out", str(out)], gate_builder=builder)
            self.assertEqual(code, tool.EXIT_REPORT_WRITE_FAILED)
            self.assertEqual(out.read_text(encoding="utf-8"), "{}")


    def test_go_race_gates_forbid_the_test_cache(self):
        """Go 门禁必须 -count=1 且带新鲜性断言，否则 (cached) 会把"没跑"呈现为"通过"。"""
        gates = tool.build_gates(Path("/nonexistent-repo"), Path("/nonexistent-build"))
        race = [g for g in gates if g["id"].endswith("_race")]
        self.assertEqual(len(race), len(tool.GO_MODULES))
        for gate in race:
            self.assertIn("-count=1", gate["argv"])
            self.assertIs(gate["post"], tool.check_go_output_is_fresh)

    def test_cached_go_output_is_not_a_fresh_pass(self):
        fresh = {"stdout": {"tail": "ok  \tsiq/x\t1.2s\n?   \tsiq/y\t[no test files]\n"}}
        cached = {"stdout": {"tail": "ok  \tsiq/x\t(cached)\nok  \tsiq/y\t(cached)\n"}}
        self.assertEqual(tool.check_go_output_is_fresh(fresh)["status"], "passed")
        result = tool.check_go_output_is_fresh(cached)
        self.assertEqual(result["status"], "failed")
        self.assertIn("2", result["detail"])

    def test_post_check_receives_command_outcome(self):
        """post 必须拿到命令结果：新鲜性断言依赖它，缺参数会直接抛 TypeError。"""
        seen = []

        def post(outcome):
            seen.append(outcome.get("exit_code"))
            return {"status": "passed", "detail": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            gate = {"id": "g", "kind": "command", "argv": ["git", "rev-parse", "HEAD"], "post": post}
            record = tool.run_gate(repo, gate)
            self.assertEqual(record["status"], "passed")
            self.assertEqual(seen, [0])

    def test_post_check_failure_downgrades_a_passing_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            gate = {"id": "g", "kind": "command", "argv": ["git", "rev-parse", "HEAD"],
                    "post": lambda _outcome: {"status": "failed", "detail": "post_says_no"}}
            record = tool.run_gate(repo, gate)
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["detail"], "post_says_no")


if __name__ == "__main__":
    unittest.main()
