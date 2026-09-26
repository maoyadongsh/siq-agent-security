"""R07.11 浏览器验收套件的合成分支用例：不启浏览器、不构建前端、不依赖 playwright。

这些用例断言的是**套件自己的诚实性**，而不是浏览器行为：
参数按脚本实际接受的选项拼、缺原生二进制记 blocked 而不是硬塞、证据目录不预建、
"没跑"永远不会被记成通过。
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "run_browser_smoke_suite", HERE / "run-browser-smoke-suite.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = load_tool()


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


HELP_OUTDATED = "usage: x\n\noptions:\n  -h, --help\n  --web WEB\n  --out-dir OUT_DIR\n"
HELP_NATIVE = "options:\n  --edge EDGE\n  --connector-dir CONNECTOR_DIR\n  --web WEB\n  --output OUTPUT\n"
HELP_PLAIN = "options:\n  --output OUTPUT\n"


def make_repo(tmp: Path, stems: list[str]) -> Path:
    """`stems` 是**完整脚本名**（如 `onboarding-browser-smoke`），与套件的键一致。"""
    (tmp / "scripts" / "enterprise-experience").mkdir(parents=True)
    for stem in stems:
        (tmp / "scripts" / "enterprise-experience" / f"{stem}.py").write_text("# synthetic\n",
                                                                             encoding="utf-8")
    (tmp / "apps" / "web").mkdir(parents=True)
    return tmp


def fake_runner(help_map, run_map=None, record=None):
    """按 argv 内容分派：`--help` 走 help_map，其余走 run_map。"""
    def runner(argv, **kwargs):
        if record is not None:
            record.append(list(argv))
        if "--help" in argv:
            name = Path(argv[1]).stem
            return FakeResult(0, help_map.get(name, HELP_PLAIN))
        if argv[1:2] == ["-c"]:
            return FakeResult(0, "1.2.3\n")
        if run_map is not None and Path(argv[1]).stem in run_map:
            return run_map[Path(argv[1]).stem]
        return FakeResult(0, "ok\n")
    return runner


class ProbeTests(unittest.TestCase):
    def test_playwright_probe_asks_distribution_metadata(self):
        """`playwright.__version__` 不存在：用它探测会把装了 playwright 的解释器判成没装。"""
        seen = []

        def runner(argv, **_kwargs):
            seen.append(argv)
            return FakeResult(0, "1.55.0\n")

        self.assertEqual(tool.playwright_version(Path("/python"), runner), "1.55.0")
        self.assertEqual(seen, [[str(Path("/python")), "-c", tool.PLAYWRIGHT_PROBE]])
        self.assertIn("importlib.metadata", tool.PLAYWRIGHT_PROBE)
        self.assertNotIn("__version__", tool.PLAYWRIGHT_PROBE)

    def test_playwright_probe_failure_is_none_not_a_version(self):
        self.assertIsNone(tool.playwright_version(Path("/python"),
                                                  lambda *_a, **_k: FakeResult(1, "", "boom")))


class BuildArgvTests(unittest.TestCase):
    def test_options_come_from_help_not_from_a_guessed_family(self):
        options = tool.script_option_sets(Path("/repo"), Path("/python"),
                                         [Path("/s/outdated-browser-smoke.py")],
                                         runner=fake_runner({"outdated-browser-smoke": HELP_OUTDATED}))
        # 只取长选项：套件从不拼短选项，但同一行上的 `-h, --help` 必须能取到 `--help`
        # （只读行首那个词会漏掉它，也就漏掉"该脚本没有这个参数"的判据）。
        self.assertEqual(options["outdated-browser-smoke"], {"--help", "--web", "--out-dir"})

    def test_out_dir_is_handed_over_not_pre_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()
            argv, reason = tool.build_argv(Path("/python"), Path("/s/a-browser-smoke.py"),
                                           {"--web", "--out-dir"}, web_build=Path("/build"),
                                           evidence_root=root, edge=None, connector_dir=None)
            self.assertIsNone(reason)
            self.assertEqual(argv, ["/python", "/s/a-browser-smoke.py", "--web", "/build",
                                    "--out-dir", str(root / "a-browser-smoke")])
            # 关键：套件**没有**替脚本建目录（脚本自己 mkdir(exist_ok=False)）。
            self.assertFalse((root / "a-browser-smoke").exists())

    def test_missing_native_binaries_are_blocked_not_faked(self):
        argv, reason = tool.build_argv(Path("/python"), Path("/s/n-browser-smoke.py"),
                                       {"--edge", "--connector-dir", "--web", "--output"},
                                       web_build=Path("/build"), evidence_root=Path("/e"),
                                       edge=None, connector_dir=None)
        self.assertEqual(reason, "native_edge_binary_not_provided")
        self.assertNotIn("--output", argv)

    def test_unknown_option_set_is_blocked_rather_than_guessed(self):
        argv, reason = tool.build_argv(Path("/python"), Path("/s/x-browser-smoke.py"), set(),
                                       web_build=None, evidence_root=Path("/e"),
                                       edge=None, connector_dir=None)
        self.assertEqual(reason, "no_known_output_option")
        self.assertEqual(argv, ["/python", "/s/x-browser-smoke.py"])


class SuiteSemanticsTests(unittest.TestCase):
    def _run(self, help_map, run_map, *, edge=None, build_ok=True):
        tmp = tempfile.mkdtemp(prefix="siq-suite-test-")
        repo = make_repo(Path(tmp), sorted(help_map))
        evidence = Path(tmp) / "evidence"
        result = tool.run_suite(repo, evidence, python=Path("/python"), edge=edge, connector_dir=None,
                                only=None, timeout=5,
                                runner=fake_runner(help_map, run_map),
                                build_result={"ok": build_ok, "web_build_dir": str(Path(tmp) / "build"),
                                              "detail": None if build_ok else "web_build_exit_nonzero"})
        return result

    def test_all_scripts_passing_is_the_only_way_to_pass(self):
        result = self._run({"a-browser-smoke": HELP_PLAIN, "b-browser-smoke": HELP_OUTDATED}, {})
        self.assertTrue(result["passed"])
        self.assertEqual(result["counts"], {"passed": 2, "failed": 0, "blocked": 0, "total": 2})

    def test_one_failing_script_makes_the_suite_not_passed_and_names_it(self):
        result = self._run({"a-browser-smoke": HELP_PLAIN, "b-browser-smoke": HELP_OUTDATED},
                           {"b-browser-smoke": FakeResult(1, "", "AssertionError: nope\n")})
        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_scripts"], ["b-browser-smoke"])
        self.assertIn("AssertionError", result["scripts"]["b-browser-smoke"]["stderr_tail"])

    def test_blocked_scripts_never_count_as_passed(self):
        result = self._run({"a-browser-smoke": HELP_PLAIN, "n-browser-smoke": HELP_NATIVE}, {})
        self.assertFalse(result["passed"])
        self.assertEqual(result["blocked_scripts"], ["n-browser-smoke"])
        self.assertEqual(result["scripts"]["n-browser-smoke"]["detail"],
                         "native_edge_binary_not_provided")

    def test_build_failure_blocks_everything_instead_of_running_on_stale_output(self):
        result = self._run({"a-browser-smoke": HELP_PLAIN}, {}, build_ok=False)
        self.assertFalse(result["passed"])
        self.assertEqual(result["counts"]["blocked"], 1)

    def test_missing_playwright_is_recorded_as_blocked_not_as_pass(self):
        tmp = tempfile.mkdtemp(prefix="siq-suite-test-")
        repo = make_repo(Path(tmp), ["a-browser-smoke"])
        evidence = Path(tmp) / "evidence"

        def runner(argv, **kwargs):
            if argv[1:2] == ["-c"]:
                return FakeResult(1, "", "ModuleNotFoundError: playwright\n")
            if "--help" in argv:
                return FakeResult(0, HELP_PLAIN)
            return FakeResult(0, "ok\n")

        result = tool.run_suite(repo, evidence, python=Path("/python"), edge=None, connector_dir=None,
                                only=None, timeout=5, runner=runner,
                                build_result={"ok": True, "web_build_dir": str(Path(tmp) / "build")})
        self.assertFalse(result["passed"])
        self.assertIsNone(result["playwright_version"])
        self.assertEqual(result["counts"]["blocked"], 1)

    def test_result_declares_simulated_build_and_never_production(self):
        result = self._run({"a-browser-smoke": HELP_PLAIN}, {})
        self.assertIs(result["simulated_build"], True)
        self.assertIs(result["production_deployed"], False)
        self.assertIs(result["production_identity_tested"], False)
        self.assertIn("mocked browser", result["scope_note"])

    def test_suite_sha256_binds_the_evidence_to_this_tool_revision(self):
        result = self._run({"a-browser-smoke": HELP_PLAIN}, {})
        self.assertEqual(result["suite_sha256"], tool.sha256_file(HERE / "run-browser-smoke-suite.py"))


class ScopeMeasurementTests(unittest.TestCase):
    """范围必须**度量**出来，而不是写死在范围声明里。

    这批脚本不是"全都不碰真实后端"：其中一部分会自起回环 dev 控制面（真实 socket + 真实 HTTP）。
    套件按 `SIQ_AS_DEV` 逐个判定并把结果写进结果文件，读的人不必相信一句范围声明。
    """

    def _run(self, bodies: dict, run_map=None):
        tmp = tempfile.mkdtemp(prefix="siq-suite-scope-")
        repo = make_repo(Path(tmp), sorted(bodies))
        for stem, body in bodies.items():
            (repo / "scripts" / "enterprise-experience" / f"{stem}.py").write_text(body, encoding="utf-8")
        result = tool.run_suite(repo, Path(tmp) / "evidence", python=Path("/python"), edge=None,
                                connector_dir=None, only=None, timeout=5,
                                runner=fake_runner({s: HELP_PLAIN for s in bodies}, run_map or {}),
                                build_result={"ok": True, "web_build_dir": str(Path(tmp) / "build")})
        return result

    REAL_API = "import os\nos.environ['SIQ_AS_DEV'] = '1'\n"
    MOCKED = "page.route('**/x', handler)\n"

    def test_real_dev_api_scripts_are_measured_not_assumed(self):
        result = self._run({"a-browser-smoke": self.REAL_API, "b-browser-smoke": self.MOCKED})
        self.assertEqual(result["real_dev_api_scripts"], ["a-browser-smoke"])
        self.assertIn("real_dev_api_scripts", result["scope_note"])

    def test_failures_inside_the_real_backend_subset_are_flagged_as_such(self):
        """失败是否全落在真实后端脚本内，是一条可核对线索（而不是对失败原因的断言）。"""
        in_real = self._run({"a-browser-smoke": self.REAL_API},
                            {"a-browser-smoke": FakeResult(1, "", "AssertionError\n")})
        self.assertEqual(in_real["failed_scripts"], ["a-browser-smoke"])
        self.assertIs(in_real["failed_are_subset_of_real_dev_api"], True)

        outside = self._run({"a-browser-smoke": self.REAL_API, "b-browser-smoke": self.MOCKED},
                            {"b-browser-smoke": FakeResult(1, "", "AssertionError\n")})
        self.assertEqual(outside["failed_scripts"], ["b-browser-smoke"])
        self.assertIs(outside["failed_are_subset_of_real_dev_api"], False)

    def test_scope_note_does_not_claim_contract_level_evidence(self):
        note = tool.SCOPE_NOTE
        self.assertIn("mocked browser only", note)
        self.assertIn("自起回环 dev 控制面", note)
        self.assertIn("不做契约级断言", note)


class EvidenceDirTests(unittest.TestCase):
    def test_claim_refuses_to_overwrite_prior_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evidence"
            out.mkdir()
            (out / "result.json").write_text('{"passed": true}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                tool.claim_evidence_dir(out)
            with self.assertRaises(RuntimeError):
                tool.write_result(out, {"passed": False})
            self.assertEqual(json.loads((out / "result.json").read_text(encoding="utf-8")),
                             {"passed": True})

    def test_evidence_dir_is_claimed_before_scripts_run(self):
        """脚本会以 mkdir(parents=True) 连带建出父目录：占位必须发生在跑脚本**之前**。

        回归用例：曾经"最后才独占创建"，结果整批 30 个脚本跑完（4 分 24 秒）才报
        "evidence dir already exists"、退出 2，一次真实运行的结果全丢。
        """
        tmp = tempfile.mkdtemp(prefix="siq-suite-test-")
        repo = make_repo(Path(tmp), ["a-browser-smoke"])
        out = Path(tmp) / "evidence"
        observed = {}

        def runner(argv, **_kwargs):
            if "--help" in argv:
                observed["root_existed"] = out.is_dir()
                return FakeResult(0, HELP_PLAIN)
            if argv[1:2] == ["-c"]:
                return FakeResult(0, "1.2.3\n")
            return FakeResult(0, "ok\n")

        tool.claim_evidence_dir(out)
        self.assertTrue(out.is_dir())
        result = tool.run_suite(repo, out, python=Path("/python"), edge=None, connector_dir=None,
                                only=None, timeout=5, runner=runner,
                                build_result={"ok": True, "web_build_dir": str(Path(tmp) / "b")})
        self.assertTrue(observed["root_existed"])
        result_path = tool.write_result(out, result)
        self.assertEqual(json.loads(result_path.read_text(encoding="utf-8"))["passed"], True)

    def test_main_refuses_a_pre_existing_out_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "repo", ["a-browser-smoke"])
            out = Path(tmp) / "exists"
            out.mkdir()
            stderr = io.StringIO()
            original, sys.stderr = sys.stderr, stderr
            try:
                with self.assertRaises(SystemExit) as ctx:
                    tool.main(["--repo", str(repo), "--out", str(out)])
            finally:
                sys.stderr = original
            self.assertEqual(ctx.exception.code, tool.EXIT_USAGE)
            self.assertIn("must not exist", stderr.getvalue())

    def test_main_prints_failed_script_names_for_the_gate_report_tail(self):
        tmp = tempfile.mkdtemp(prefix="siq-suite-test-")
        repo = make_repo(Path(tmp), ["a-browser-smoke", "b-browser-smoke"])
        out = Path(tmp) / "evidence"

        def runner(argv, **_kwargs):
            if "--help" in argv:
                return FakeResult(0, HELP_PLAIN)
            if argv[1:2] == ["-c"]:
                return FakeResult(0, "1.2.3\n")
            return FakeResult(1, "", "boom\n") if "b-browser-smoke" in argv[1] else FakeResult(0, "ok\n")

        stderr = io.StringIO()
        original, sys.stderr = sys.stderr, stderr
        try:
            code = tool.main(["--repo", str(repo), "--out", str(out)], runner=runner,
                             build_web=lambda _repo: {"ok": True, "web_build_dir": str(Path(tmp) / "b")})
        finally:
            sys.stderr = original
        self.assertEqual(code, tool.EXIT_NOT_PASS)
        self.assertIn("failed: b-browser-smoke", stderr.getvalue())

    def test_timeout_is_a_failure_not_a_pass(self):
        tmp = tempfile.mkdtemp(prefix="siq-suite-test-")
        repo = make_repo(Path(tmp), ["t-browser-smoke"])
        evidence = Path(tmp) / "evidence"

        def runner(argv, **kwargs):
            if "--help" in argv:
                return FakeResult(0, HELP_PLAIN)
            if argv[1:2] == ["-c"]:
                return FakeResult(0, "1.2.3\n")
            raise subprocess.TimeoutExpired(cmd=argv, timeout=1)

        result = tool.run_suite(repo, evidence, python=Path("/python"), edge=None, connector_dir=None,
                                only=None, timeout=1, runner=runner,
                                build_result={"ok": True, "web_build_dir": str(Path(tmp) / "build")})
        self.assertFalse(result["passed"])
        self.assertEqual(result["scripts"]["t-browser-smoke"]["status"], "failed")
        self.assertIn("timeout_after_1s", result["scripts"]["t-browser-smoke"]["detail"])


if __name__ == "__main__":
    unittest.main()
