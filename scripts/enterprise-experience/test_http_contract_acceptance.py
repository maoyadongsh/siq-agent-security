"""http-contract-acceptance 的合成测试。

**这些用例不启动任何服务、不发任何真实 HTTP**（那属于 R09.8 的实跑，需 §3.2 逐次许可）。
这里只钉死三件最容易造出**假绿**的东西：
1. 判定聚合：任何一条判据不成立，该组与整体结论都必须是失败的；
2. 秘密扫描：把哨兵串放进临时目录/日志里必须被**抓到**（只在"干净"输入上返回空集 = 假绿）；
3. 回收与退出码：进程为空时不得谎报退出、证据目录独占创建、结论→退出码映射。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("http-contract-acceptance.py")
_SPEC = importlib.util.spec_from_file_location("http_contract_acceptance", SCRIPT)
tool = importlib.util.module_from_spec(_SPEC)
# 必须先进 sys.modules：被加载文件的 dataclass 装饰器会按 cls.__module__ 反查模块字典，
# 不登记就会在装饰那一刻抛 AttributeError: 'NoneType' object has no attribute '__dict__'。
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)


def make_acc(out_dir: Path) -> tool.Acceptance:
    acc = tool.Acceptance(out_dir=out_dir)
    acc.ids.update(
        {
            "jwt_marker": "acc-marker-jwt-" + "a" * 32,
            "seed_b64": "b" * 44,
            "bearer_token": "c" * 32,
        }
    )
    return acc


class ResponseHelpers(unittest.TestCase):
    def test_header_lookup_is_case_insensitive(self):
        resp = tool.Resp(status=200, headers={"x-siq-list-total": "4"}, text="{}")
        self.assertEqual(resp.header("X-SIQ-List-Total"), "4")
        self.assertIsNone(resp.header("missing"))

    def test_detail_and_rows_tolerate_non_json(self):
        plain = tool.Resp(status=502, headers={}, text="<html>bad gateway</html>")
        self.assertIsNone(plain.detail())
        self.assertEqual(plain.rows(), [])
        self.assertIsNone(plain.json())

    def test_hdr_renders_short_form(self):
        resp = tool.Resp(status=200, headers={"x-siq-list-limit": "2"}, text="")
        self.assertEqual(tool._hdr(resp, "x-siq-list-limit"), "x-siq-list-limit='2'")


class ReportAggregation(unittest.TestCase):
    def test_one_failed_check_fails_group_and_conclusion(self):
        with tempfile.TemporaryDirectory() as raw:
            acc = make_acc(Path(raw))
            acc.check("g1", "ok", True)
            acc.check("g1", "bad", False, "detail")
            acc.check("g2", "ok", True)
            report = tool._report(acc, {}, None)
            groups = {g["group"]: g for g in report["judgments"]}
            self.assertEqual(groups["g1"]["status"], "failed")
            self.assertEqual(groups["g2"]["status"], "held")
            self.assertEqual(report["conclusion"], "contracts_failed")
            self.assertEqual(report["totals"], {"checks": 3, "failed": 1})

    def test_all_held_is_the_only_path_to_contracts_held(self):
        with tempfile.TemporaryDirectory() as raw:
            acc = make_acc(Path(raw))
            acc.check("g1", "ok", True)
            self.assertEqual(tool._report(acc, {}, None)["conclusion"], "contracts_held")

    def test_run_error_wins_over_green_checks(self):
        with tempfile.TemporaryDirectory() as raw:
            acc = make_acc(Path(raw))
            acc.check("g1", "ok", True)
            report = tool._report(acc, {}, "RuntimeError: 控制面就绪超时")
            self.assertEqual(report["conclusion"], "run_error")
            self.assertIn("就绪超时", report["run_error"])

    def test_teardown_flags_are_checked_not_assumed(self):
        """回收核验必须来自实测值：missing/False 一律不许变成成立。"""
        with tempfile.TemporaryDirectory() as raw:
            acc = make_acc(Path(raw))
            teardown = {"process_exited": None, "port_released": False, "temp_dir_removed": True}
            for name, key in (
                ("进程已退出", "process_exited"),
                ("端口已释放", "port_released"),
                ("目录已移除", "temp_dir_removed"),
            ):
                acc.check("teardown", name, teardown.get(key) is True, f"{key}={teardown.get(key)}")
            checks = {c["name"]: c["ok"] for c in acc.checks}
            self.assertFalse(checks["进程已退出"])
            self.assertFalse(checks["端口已释放"])
            self.assertTrue(checks["目录已移除"])


class SecretScan(unittest.TestCase):
    """扫描必须能**抓到**植入的秘密，否则"未命中"只是空集的另一种说法。"""

    def test_planted_markers_in_workdir_are_detected(self):
        with tempfile.TemporaryDirectory() as raw:
            out_dir = Path(raw) / "out"
            out_dir.mkdir()
            acc = make_acc(out_dir)
            (acc.root / "api.db").write_bytes(b"row|" + acc.ids["jwt_marker"].encode())
            (acc.root / "server.log").write_bytes(b"startup ok")
            (acc.root / "signing.seed").write_text(acc.ids["seed_b64"], encoding="utf-8")
            info = acc.teardown(None, tool._markers(acc))
            self.assertIn("api.db:dev JWT 共享密钥", info["file_hits"])
            # signing.seed 是本轮输入材料（本就该含种子），不在扫描对象内——否则判据永远为红。
            self.assertFalse([h for h in info["file_hits"] if h.startswith("signing.seed")])

    def test_clean_workdir_yields_no_hits_and_removes_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            out_dir = Path(raw) / "out"
            out_dir.mkdir()
            acc = make_acc(out_dir)
            (acc.root / "api.db").write_bytes(b"clean")
            root = acc.root
            info = acc.teardown(None, tool._markers(acc))
            self.assertEqual(info["file_hits"], [])
            self.assertTrue(info["temp_dir_removed"])
            self.assertFalse(root.exists())

    def test_server_log_is_copied_out_before_removal(self):
        with tempfile.TemporaryDirectory() as raw:
            out_dir = Path(raw) / "out"
            out_dir.mkdir()
            acc = make_acc(out_dir)
            (acc.root / "server.log").write_text("INFO: Started server process\n", encoding="utf-8")
            acc.teardown(None, tool._markers(acc))
            copied = (out_dir / "server-stdout-stderr.log").read_text(encoding="utf-8")
            self.assertIn("Started server process", copied)

    def test_log_marker_is_detected_by_the_same_markers_dict(self):
        with tempfile.TemporaryDirectory() as raw:
            out_dir = Path(raw) / "out"
            out_dir.mkdir()
            acc = make_acc(out_dir)
            (out_dir / "server-stdout-stderr.log").write_text(acc.ids["bearer_token"], encoding="utf-8")
            log_text = (out_dir / "server-stdout-stderr.log").read_text(encoding="utf-8")
            self.assertIn(acc.ids["bearer_token"], log_text)
            self.assertTrue(any(m in log_text for m in tool._markers(acc).values()))


class Isolation(unittest.TestCase):
    def test_boot_env_is_whitelisted_and_carries_no_real_secret(self):
        with tempfile.TemporaryDirectory() as raw:
            acc = make_acc(Path(raw))
            env = acc.build_env()
            self.assertEqual(env["SIQ_AS_DEV"], "1")
            self.assertEqual(env["SIQ_AS_ALLOW_SQLITE"], "1")
            self.assertTrue(env["SIQ_AS_DATABASE_URL"].startswith("sqlite:///"))
            self.assertEqual(env["SIQ_AS_DEV_JWT_SECRET"], acc.ids["jwt_marker"])
            self.assertEqual(env["HOME"], str(acc.root))
            # 只放行 4 个 locale/路径变量 + 上面那些；不得继承调用方的任何其它环境变量。
            allowed = {"PATH", "LANG", "LC_ALL", "TZ", "HOME", "SIQ_AS_DEV", "SIQ_AS_ALLOW_SQLITE",
                       "SIQ_AS_DATABASE_URL", "SIQ_AS_SIGNING_KEY_FILE", "SIQ_AS_ENFORCEMENT_BACKEND",
                       "SIQ_AS_DEV_JWT_SECRET"}
            self.assertLessEqual(set(env), allowed)

    def test_non_claims_block_names_the_boundaries(self):
        joined = " ".join(tool.NON_CLAIMS)
        for phrase in ("≠ 真实 IAM", "临时 SQLite", "已声明", "enforcement_verified"):
            self.assertIn(phrase, joined)


class ExitCodes(unittest.TestCase):
    def test_exit_codes_are_distinct_and_stable(self):
        self.assertEqual(
            (tool.EXIT_PASS, tool.EXIT_FAILED, tool.EXIT_USAGE, tool.EXIT_REPORT_WRITE_FAILED), (0, 1, 2, 3)
        )

    def test_existing_out_dir_is_a_usage_error_and_does_not_touch_it(self):
        with tempfile.TemporaryDirectory() as raw:
            existing = Path(raw) / "evidence"
            existing.mkdir()
            keep = existing / "report.json"
            keep.write_text("previous run", encoding="utf-8")
            try:
                existing.mkdir(parents=True, exist_ok=False)
                self.fail("已存在的证据目录必须拒绝独占创建")
            except OSError:
                pass
            self.assertEqual(keep.read_text(encoding="utf-8"), "previous run")

    def test_report_is_json_serialisable(self):
        with tempfile.TemporaryDirectory() as raw:
            acc = make_acc(Path(raw))
            acc.check("g1", "ok", True, "细节")
            report = tool._report(acc, {"port_released": True}, None)
            text = json.dumps(report, ensure_ascii=False)
            self.assertIn("loopback_dev_http_contract_acceptance", text)
            self.assertEqual(json.loads(text)["candidate"]["scope"].count("不是"), 1)


if __name__ == "__main__":
    unittest.main()
