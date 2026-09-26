"""enterprise-gate-run 合成仓库测试。

全部用例只作用于临时合成目录；**不运行真实门禁**（不跑后端/前端/Go 真套件），
只验证执行器的判定、留证与"不可跑项绝不算通过"的诚实性。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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

    def test_browser_acceptance_declaration_carries_the_measured_reason(self):
        """登记原因必须是实测事实，不是猜测。

        2026-09-26 实测：30 个脚本**都不需要预先运行的控制面**（所以不是 `requires_running_services`），
        但**也不是"全都不碰真实后端"**——其中 8 个会自起回环 dev 控制面（真实 socket + 真实 HTTP）。
        措辞必须同时避开这两个方向的失真：既不夸大（不许说成真实 HTTP 契约验收），
        也不缩小（不许说成全部都是 mocked）。
        """
        by_id = {item["id"]: item for item in tool.DECLARED_UNAVAILABLE}
        self.assertEqual(
            sorted(by_id),
            ["browser_acceptance", "migration_replay_postgres", "real_device_native_evidence"],
        )
        browser = by_id["browser_acceptance"]
        self.assertNotEqual(browser["reason"], "requires_running_services")
        self.assertEqual(browser["reason"], "requires_frontend_simulated_build_and_playwright")
        self.assertIn("mocked browser only", browser["note"])
        self.assertIn("自起回环 dev 控制面", browser["note"])
        self.assertIn("不做契约级断言", browser["note"])
        self.assertTrue(browser["tool"])
        for item in tool.DECLARED_UNAVAILABLE:
            self.assertTrue(item["reason"])
            self.assertTrue(item["note"])

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

    def test_postgres_gate_is_not_even_probed_until_explicitly_enabled(self):
        """默认必须**连 docker 都不碰**："没启用"不是"探测后不可跑"，两者证据不同。"""
        calls = []

        def runner(argv, **_kwargs):  # pragma: no cover - 被调用即失败
            calls.append(argv)
            raise AssertionError("未启用时不得触碰 docker")

        decision = tool.postgres_gate_decision(Path("."), enabled=False, runner=runner)
        self.assertEqual(decision["action"], "skipped")
        self.assertEqual(decision["reason"], "requires_database_container")
        self.assertFalse(decision.get("measured"))
        self.assertEqual(calls, [])

    def test_postgres_probe_never_pulls_and_names_the_measured_reason(self):
        class Fake:
            def __init__(self, code, out=""):
                self.returncode, self.stdout, self.stderr = code, out, "boom"

        def make(codes):
            seen = []

            def runner(argv, **_kwargs):
                seen.append(argv)
                return Fake(*codes[len(seen) - 1])

            return runner, seen

        # 客户端/守护进程不可用
        runner, seen = make([(1, "")])
        self.assertEqual(tool.docker_probe(Path("."), runner)["reason"],
                         "docker_daemon_or_client_unavailable")
        # 镜像缺失：不得自动拉取
        runner, seen = make([(0, "29.1.3"), (1, "")])
        probe = tool.docker_probe(Path("."), runner)
        self.assertEqual(probe["reason"], "postgres_image_absent_and_auto_pull_forbidden")
        self.assertFalse(probe["runnable"])
        # 全部就绪
        runner, seen = make([(0, "29.1.3"), (0, "sha256:deadbeef")])
        probe = tool.docker_probe(Path("."), runner)
        self.assertTrue(probe["runnable"])
        self.assertEqual(probe["evidence"]["image_id"], "sha256:deadbeef")
        for argv in seen:
            self.assertNotIn("pull", argv)
            self.assertEqual(argv[0], "docker")

    def test_postgres_evidence_claims_are_asserted_not_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp)
            script = Path(tmp) / "check.py"
            script.write_text("# tool\n", encoding="utf-8")
            digest = hashlib.sha256(script.read_bytes()).hexdigest()

            def proof(**overrides):
                body = {"passed": True, "ephemeral_database": True,
                        "production_identity_tested": False,
                        "checks": {"postgres_submit_replay_and_audit": True},
                        "script_sha256": digest, "database_image_id": "sha256:x",
                        "migrated_head": "0031"}
                body.update(overrides)
                return body

            def write(body):
                (evidence / "result.json").write_text(
                    "not json" if body is None else json.dumps(body), encoding="utf-8")
                return tool.check_postgres_evidence(evidence, script)

            self.assertEqual(write(proof())["status"], "passed")
            self.assertEqual(write(proof(production_identity_tested=True))["detail"],
                             "postgres_evidence_claims_production_identity")
            self.assertEqual(write(proof(ephemeral_database=False))["detail"],
                             "postgres_evidence_not_ephemeral")
            self.assertEqual(write(proof(passed=False))["detail"],
                             "postgres_evidence_not_passed")
            self.assertEqual(write(proof(checks={}))["detail"],
                             "postgres_evidence_has_no_checks")
            self.assertEqual(write(proof(script_sha256="0" * 64))["detail"],
                             "postgres_evidence_script_digest_mismatch")
            self.assertEqual(write(None)["status"], "blocked")
            (evidence / "result.json").unlink()
            self.assertEqual(tool.check_postgres_evidence(evidence, script)["detail"],
                             "postgres_evidence_missing")

    def test_enabled_but_unrunnable_postgres_gate_records_measured_skip_off_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            build = Path(tmp) / "build"
            build.mkdir()

            def runner(_argv, **_kwargs):
                class R:
                    returncode, stdout, stderr = 1, "", "cannot connect"
                return R()

            decision = tool.postgres_gate_decision(repo, enabled=True, runner=runner)
            self.assertEqual(decision["action"], "skipped")
            self.assertTrue(decision["measured"])
            self.assertEqual(decision["reason"], "docker_daemon_or_client_unavailable")
            report = tool.run_gates(repo, synthetic_gates({"ok": "passed"}), build,
                                    postgres_decision=decision)
            entry = [s for s in report["skipped_gates"] if s["id"] == tool.POSTGRES_UNAVAILABLE_ID]
            self.assertEqual(len(entry), 1)
            self.assertEqual(entry[0]["reason"], "docker_daemon_or_client_unavailable")
            self.assertTrue(entry[0]["measured"])
            self.assertEqual(report["conclusion"], "gates_incomplete")

    def test_an_attempted_postgres_gate_retires_the_unavailable_declaration(self):
        """只有**真的跑了**才撤下"不可跑"登记；跑成什么样由门禁记录自己说明。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            build = Path(tmp) / "build"
            build.mkdir()
            gates = synthetic_gates({"ok": "passed"})
            gates.append({"id": tool.POSTGRES_GATE_ID, "kind": "command",
                          "argv": ["git", "rev-parse", "HEAD"]})
            report = tool.run_gates(repo, gates, build, postgres_decision={
                "action": "run", "reason": None, "measured": True,
                "evidence": {"image_id": "sha256:x"}})
            self.assertNotIn(tool.POSTGRES_UNAVAILABLE_ID, report["skipped_gate_ids"])
            by_id = {r["id"]: r for r in report["gates"]}
            self.assertEqual(by_id[tool.POSTGRES_GATE_ID]["status"], "passed")
            self.assertTrue(report["skipped_gate_ids"])  # 其余两项仍登记在案
            self.assertEqual(report["conclusion"], "gates_incomplete")

    def test_main_records_the_optional_gate_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"
            def builder(_repo, _build):
                return synthetic_gates({"ok": "passed"})

            code = tool.main(["--repo", str(repo), "--out", str(out)], gate_builder=builder)
            self.assertEqual(code, tool.EXIT_NOT_GREEN)
            report = json.loads(out.read_text(encoding="utf-8"))
            decision = report["optional_gate_decisions"][0]
            self.assertEqual(decision["id"], tool.POSTGRES_UNAVAILABLE_ID)
            self.assertEqual(decision["action"], "skipped")
            self.assertFalse(decision.get("measured"))
            self.assertIn(tool.POSTGRES_UNAVAILABLE_ID, report["skipped_gate_ids"])

    def test_enabled_but_only_excluded_postgres_gate_never_probes_docker(self):
        """启用了但本次被 `--only` 排除：连只读探测都不做，登记项照旧留在 skipped 里。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"

            def builder(_repo, _build):
                return synthetic_gates({"ok": "passed"})

            def boom(*_args, **_kwargs):  # pragma: no cover - 被调用即失败
                raise AssertionError("被 --only 排除时不得探测 docker")

            with unittest.mock.patch.object(tool, "docker_probe", boom):
                code = tool.main(["--repo", str(repo), "--out", str(out), "--only", "ok",
                                  "--enable-ephemeral-postgres-gate"], gate_builder=builder)
            self.assertEqual(code, tool.EXIT_NOT_GREEN)
            report = json.loads(out.read_text(encoding="utf-8"))
            decision = report["optional_gate_decisions"][0]
            self.assertTrue(decision["excluded_by_only"])
            self.assertEqual(decision["action"], "skipped")
            self.assertIn(tool.POSTGRES_UNAVAILABLE_ID, report["skipped_gate_ids"])
            self.assertNotIn(tool.POSTGRES_GATE_ID, [r["id"] for r in report["gates"]])

    def test_postgres_evidence_dir_is_handed_over_not_pre_created(self):
        """A1 脚本要求一个**不存在**的新目录（防覆盖上次留证）；预建会让门禁假失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"
            seen = {}

            def builder(_repo, _build):
                return synthetic_gates({"ok": "passed"})

            def gate(repo_arg, evidence_dir):
                seen["dir"] = evidence_dir
                return {"id": tool.POSTGRES_GATE_ID, "kind": "command",
                        "argv": ["git", "rev-parse", "HEAD"]}

            with unittest.mock.patch.object(
                    tool, "postgres_gate_decision",
                    lambda _repo, **_kw: {"action": "run", "reason": None}), \
                    unittest.mock.patch.object(tool, "postgres_gate", gate):
                code = tool.main(["--repo", str(repo), "--out", str(out),
                                  "--enable-ephemeral-postgres-gate"], gate_builder=builder)
            self.assertEqual(code, tool.EXIT_NOT_GREEN)
            self.assertFalse(seen["dir"].exists())
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["optional_gate_decisions"][0]["evidence_dir"],
                             str(seen["dir"]))
            self.assertEqual(report["conclusion"], "gates_incomplete")

    def test_browser_gate_is_not_even_probed_until_explicitly_enabled(self):
        """默认必须**连解释器都不探**；"没启用"与"探测后不可跑"是两种不同的诚实。"""
        calls = []

        def runner(argv, **_kwargs):  # pragma: no cover - 被调用即失败
            calls.append(argv)
            raise AssertionError("未启用时不得探测解释器")

        decision = tool.browser_gate_decision(Path("."), enabled=False, python=None, runner=runner)
        self.assertEqual(decision["action"], "skipped")
        self.assertEqual(decision["reason"], "requires_frontend_simulated_build_and_playwright")
        self.assertFalse(decision.get("measured"))
        self.assertEqual(calls, [])

    def test_browser_probe_never_installs_and_names_the_measured_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            scripts = repo / "scripts" / "enterprise-experience"
            python = Path(tmp) / "python"

            # 一个脚本都没有：不可跑（而不是"空套件算通过"）。
            self.assertEqual(tool.browser_probe(repo, python, runner=lambda *_a, **_k: None)["reason"],
                             "no_browser_smoke_scripts_found")

            scripts.mkdir(parents=True, exist_ok=True)
            (scripts / "demo-browser-smoke.py").write_text("# synthetic\n", encoding="utf-8")
            # 解释器不存在
            self.assertEqual(tool.browser_probe(repo, python, runner=lambda *_a, **_k: None)["reason"],
                             "browser_python_not_found")

            python.write_text("#!/bin/sh\n", encoding="utf-8")

            class Fake:
                def __init__(self, code, out="", err=""):
                    self.returncode, self.stdout, self.stderr = code, out, err

            seen = []

            def runner(argv, **_kwargs):
                seen.append(argv)
                return Fake(1, "", "ModuleNotFoundError: No module named 'playwright'")

            probe = tool.browser_probe(repo, python, runner=runner)
            self.assertFalse(probe["runnable"])
            self.assertEqual(probe["reason"], "playwright_not_importable")
            self.assertEqual(seen, [[str(python), "-c", tool.PLAYWRIGHT_PROBE]])
            # 探测命令必须查**发行版元数据**：`playwright.__version__` 不存在，
            # 用它会把装了 playwright 的解释器误判成没装。
            self.assertIn("importlib.metadata", seen[0][2])
            self.assertNotIn("__version__", seen[0][2])
            self.assertNotIn("install", " ".join(seen[0]))  # 不装依赖

            probe = tool.browser_probe(repo, python, runner=lambda *_a, **_k: Fake(0, "1.55.0\n"))
            self.assertTrue(probe["runnable"])
            self.assertEqual(probe["evidence"]["playwright_version"], "1.55.0")
            self.assertEqual(probe["evidence"]["scripts"], 1)

    def test_browser_evidence_claims_are_asserted_not_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp)
            suite = Path(tmp) / "suite.py"
            suite.write_text("# suite\n", encoding="utf-8")
            digest = hashlib.sha256(suite.read_bytes()).hexdigest()

            def proof(**overrides):
                body = {"passed": True, "simulated_build": True, "production_deployed": False,
                        "production_identity_tested": False,
                        "counts": {"passed": 25, "failed": 5, "blocked": 0, "total": 30},
                        "failed_scripts": ["workspace-browser-smoke"],
                        "real_dev_api_scripts": ["workspace-browser-smoke"],
                        "failed_are_subset_of_real_dev_api": True,
                        "suite_sha256": digest, "playwright_version": "1.55.0",
                        "scope_note": "scope: mocked browser only"}
                body.update(overrides)
                return body

            def write(body):
                (evidence / "result.json").write_text(
                    "not json" if body is None else json.dumps(body), encoding="utf-8")
                return tool.check_browser_evidence(evidence, suite)

            self.assertEqual(write(proof())["status"], "passed")
            self.assertEqual(write(proof(passed=False))["detail"], "browser_evidence_not_passed")
            self.assertEqual(write(proof(simulated_build=False))["detail"],
                             "browser_evidence_not_a_simulated_build")
            self.assertEqual(write(proof(production_deployed=True))["detail"],
                             "browser_evidence_claims_production_deploy")
            self.assertEqual(write(proof(production_identity_tested=True))["detail"],
                             "browser_evidence_claims_production_identity")
            self.assertEqual(write(proof(counts={"total": 0}))["detail"],
                             "browser_evidence_has_no_scripts")
            self.assertEqual(write(proof(suite_sha256="0" * 64))["detail"],
                             "browser_evidence_suite_digest_mismatch")
            # 范围自述必须有文件背书：套件把"哪些脚本起了真实后端"作为度量写入结果，
            # 门禁读不到该字段就必须失败，而不是照抄一句范围声明进报告。
            self.assertEqual(write(proof(real_dev_api_scripts=None))["detail"],
                             "browser_evidence_missing_real_dev_api_measurement")
            self.assertEqual(write(proof(real_dev_api_scripts="workspace"))["detail"],
                             "browser_evidence_missing_real_dev_api_measurement")
            carried = write(proof())["evidence"]
            self.assertEqual(carried["real_dev_api_scripts"], ["workspace-browser-smoke"])
            self.assertIs(carried["failed_are_subset_of_real_dev_api"], True)
            self.assertEqual(write(None)["status"], "blocked")
            (evidence / "result.json").unlink()
            self.assertEqual(tool.check_browser_evidence(evidence, suite)["detail"],
                             "browser_evidence_missing")

    def test_enabled_but_unrunnable_browser_gate_records_measured_skip_off_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            build = Path(tmp) / "build"
            build.mkdir()

            decision = tool.browser_gate_decision(repo, enabled=True, python=None,
                                                  runner=lambda *_a, **_k: None)
            self.assertEqual(decision["action"], "skipped")
            self.assertTrue(decision["measured"])
            self.assertEqual(decision["reason"], "no_browser_smoke_scripts_found")
            report = tool.run_gates(repo, synthetic_gates({"ok": "passed"}), build,
                                    browser_decision=decision)
            entry = [s for s in report["skipped_gates"] if s["id"] == tool.BROWSER_UNAVAILABLE_ID]
            self.assertEqual(len(entry), 1)
            self.assertEqual(entry[0]["reason"], "no_browser_smoke_scripts_found")
            self.assertTrue(entry[0]["measured"])
            # 另一条声明（postgres）不受影响，仍用静态原因。
            other = [s for s in report["skipped_gates"] if s["id"] == tool.POSTGRES_UNAVAILABLE_ID]
            self.assertEqual(other[0]["reason"], "requires_database_container")
            self.assertFalse(other[0].get("measured"))
            self.assertEqual(report["conclusion"], "gates_incomplete")

    def test_an_attempted_browser_gate_retires_only_its_own_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            build = Path(tmp) / "build"
            build.mkdir()
            gates = synthetic_gates({"ok": "passed"})
            gates.append({"id": tool.BROWSER_GATE_ID, "kind": "command",
                          "argv": ["git", "rev-parse", "HEAD"]})
            report = tool.run_gates(repo, gates, build, browser_decision={
                "action": "run", "reason": None, "measured": True, "python": "/python"})
            self.assertNotIn(tool.BROWSER_UNAVAILABLE_ID, report["skipped_gate_ids"])
            self.assertIn(tool.POSTGRES_UNAVAILABLE_ID, report["skipped_gate_ids"])
            self.assertEqual(report["conclusion"], "gates_incomplete")

    def test_main_records_both_optional_gate_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"

            def builder(_repo, _build):
                return synthetic_gates({"ok": "passed"})

            code = tool.main(["--repo", str(repo), "--out", str(out)], gate_builder=builder)
            self.assertEqual(code, tool.EXIT_NOT_GREEN)
            report = json.loads(out.read_text(encoding="utf-8"))
            ids = [d["id"] for d in report["optional_gate_decisions"]]
            self.assertEqual(ids, [tool.POSTGRES_UNAVAILABLE_ID, tool.BROWSER_UNAVAILABLE_ID])
            for decision in report["optional_gate_decisions"]:
                self.assertEqual(decision["action"], "skipped")
                self.assertFalse(decision.get("measured"))

    def test_enabled_but_only_excluded_browser_gate_never_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"

            def builder(_repo, _build):
                return synthetic_gates({"ok": "passed"})

            def boom(*_args, **_kwargs):  # pragma: no cover - 被调用即失败
                raise AssertionError("被 --only 排除时不得探测解释器")

            with unittest.mock.patch.object(tool, "browser_probe", boom):
                code = tool.main(["--repo", str(repo), "--out", str(out), "--only", "ok",
                                  "--enable-browser-smoke-gate"], gate_builder=builder)
            self.assertEqual(code, tool.EXIT_NOT_GREEN)
            report = json.loads(out.read_text(encoding="utf-8"))
            decision = report["optional_gate_decisions"][1]
            self.assertTrue(decision["excluded_by_only"])
            self.assertEqual(decision["action"], "skipped")
            self.assertIn(tool.BROWSER_UNAVAILABLE_ID, report["skipped_gate_ids"])
            self.assertNotIn(tool.BROWSER_GATE_ID, [r["id"] for r in report["gates"]])

    def test_browser_evidence_dir_is_handed_over_not_pre_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "report.json"
            seen = {}

            def builder(_repo, _build):
                return synthetic_gates({"ok": "passed"})

            def gate(_repo, evidence_dir, _python, **_kwargs):
                seen["dir"] = evidence_dir
                return {"id": tool.BROWSER_GATE_ID, "kind": "command",
                        "argv": ["git", "rev-parse", "HEAD"]}

            with unittest.mock.patch.object(
                    tool, "browser_gate_decision",
                    lambda _repo, **_kw: {"action": "run", "reason": None, "python": "/python"}), \
                    unittest.mock.patch.object(tool, "browser_gate", gate):
                code = tool.main(["--repo", str(repo), "--out", str(out),
                                  "--enable-browser-smoke-gate"], gate_builder=builder)
            self.assertEqual(code, tool.EXIT_NOT_GREEN)
            self.assertFalse(seen["dir"].exists())
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["optional_gate_decisions"][1]["evidence_dir"], str(seen["dir"]))

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
