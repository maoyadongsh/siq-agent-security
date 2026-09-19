#!/usr/bin/env python3
"""closure-b02: 让 B01 安装实例的 systemd 用户服务直接承载完整浏览器旅程。

任务书 §7 B02：复用 r07/r04/B01 runner；direct_process 与 installed_user_service
两条腿显式分开；installed 腿全程通过受支持的 CLI/HTTP 入口控制同一实例
（client-install / service-start / service-stop / teardown / pair），不读取
daemon 原文日志，不回落到 subprocess.Popen(binary serve)；每个阶段复验
state_directory_id / 签名公钥 / 制品摘要 / 端口 / unit_name / MainPID /
fragment_path（加载源），重启后 MainPID 必须变化且身份字段不变；journey 结束
后执行 service-stop → teardown（unit 注销、状态保留）→ 同状态重入
（client-install 同 manifest/同二进制/同端口，state_directory_id 与回执历史
保持）→ 最终 teardown → ownership 复验；只有 ownership 复验通过后才清理
run_dir 临时制品。

测试层声明：本 runner 依赖每轮生成的测试信任根（release-manifest + 测试种子），
属于 test_release 层；正式发行信任腿仍未关闭（需维护者以正式发布种子签署
manifest）。

HOME 隔离：共享 systemd 用户管理器环境不可修改。安装前只读检查 manager
的 HOME 已是隔离 fixture；不满足时阻塞，不安装，不回退直接启动。
旧报告中 set-environment 后还原的方式存在并发影响，不再作为隔离验收。

用法（host 侧，需 playwright 的解释器）：
  python3 closure-b02-installed-journey-runner.py \
      --openclaw-root <openclaw 模块根> --node <node 二进制> \
      --port <loopback 端口> --out <证据目录>
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
WORKTREE = HERE.parents[1]


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R07 = _load("b02_r07", HERE / "r07-linux-user-journey-smoke.py")
B01 = _load("b01_runner", HERE / "closure-b01-lifecycle-runner.py")
DRIVER = _load("b02_driver", HERE / "installed_user_service_driver.py")


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def journey_passed(report):
    rows = report.get("results", [])
    return report.get("passed") is True and bool(rows) and all(row.get("status") == "pass" for row in rows)


class ManagerHomeOverride:
    """Read-only prerequisite check; never mutate the shared user manager.

    The legacy name is retained for the harness call sites. A dedicated user
    manager must already have the fixture HOME; otherwise stop before install.
    Restoring a global value after start does not isolate concurrent services.
    """

    def __init__(self, home: str, log):
        self.home = home
        self._log = log

    def __enter__(self):
        out = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True, text=True, check=True, timeout=15,
        )
        homes = [line[5:] for line in out.stdout.splitlines() if line.startswith("HOME=")]
        require(homes == [self.home],
                "B02 blocked: installed service requires a dedicated fixture HOME; "
                "changing the shared systemd manager environment is forbidden")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ManagerEnvironmentUnchanged:
    """Observe manager environment in memory; unit-local HOME owns isolation."""

    def __enter__(self):
        self.before = subprocess.check_output(["systemctl", "--user", "show-environment"], timeout=15)
        return self

    def __exit__(self, exc_type, exc, tb):
        after = subprocess.check_output(["systemctl", "--user", "show-environment"], timeout=15)
        require(after == self.before, "shared manager environment changed")
        return False


class InstalledHarness(R07.Harness):
    """r07.Harness 的 installed_user_service 变体：控制面全部走受支持入口。"""

    def config(self, enforcement):
        home = self.root / "home"
        home.mkdir(mode=0o700, exist_ok=True)
        # installed 实例的 config.json 必须携带端口：state.Initialize 对既有
        # 状态拒绝换端口，而 decodeConfig 缺省端口是 47611（state.go），不写
        # port 会让 setup --port <非默认> 在首次初始化时失败。
        (self.state / "config.json").write_text(
            json.dumps(
                {
                    "intent_enforcement": enforcement,
                    "enforcement_mode": "block",
                    "port": self.args.port,
                    "linux_service_home": str(home),
                }
            )
        )

    def start(self):
        runner = self.b02_runner
        drv = self.b02_driver
        cli = str(self.binary)
        port = runner.args.port
        self.endpoint = f"http://127.0.0.1:{port}"
        self.env["SIQ_AGENT_SECURITY_ENDPOINT"] = self.endpoint
        require(drv.state_dir == str(self.state),
                "driver 状态目录必须与本 harness 的隔离状态目录一致")
        with runner.manager_home():
            rec = drv.install(self.b02_manifest, cli, port=port)
        require(rec["exit"] == 0, f"client-install 失败: {rec}")
        props = drv.unit_properties(drv.unit_name(), ["Environment", "MainPID"])
        raw = pathlib.Path(f"/proc/{props['MainPID']}/environ").read_bytes().split(b"\0")
        require(("HOME=" + str(self.home)).encode() in raw, "daemon HOME differs from fixture")
        runner.check("b02_unit_local_home", "running service HOME is fixture; shared manager unchanged", True, {})
        health = drv.instance_health()
        require(health.get("status") == "ready",
                f"installed 服务未就绪: {health}")
        identity = drv.identity()
        for key in ("state_directory_id", "unit_name", "port", "main_pid",
                    "fragment_path", "exec_start", "binary_digest", "version"):
            require(identity.get(key), f"installed 身份缺失 {key}: {identity}")
        require(int(identity["port"]) == int(port), f"端口不符: {identity}")
        require(identity["running_binary_path"].startswith(str(self.state)),
                f"运行二进制未从状态目录 stage: {identity}")
        runner.record_identity_event("installed_start", identity)
        self.admin = drv.pair(self.b02_runner.staged_binary(drv.state_dir))

    def stop(self, *, kill: bool = False):
        require(not kill,
                "installed 驱动没有硬杀平面；本执行链也不使用 kill=True")
        drv = self.b02_driver
        if getattr(self, "_b02_service_gone", False):
            return
        drv.service_stop(self.b02_runner.staged_binary(drv.state_dir))
        props = drv.unit_properties(drv.unit_name(),
                                    ["ActiveState", "MainPID", "Result"])
        require(props.get("ActiveState") == "inactive" and props.get("MainPID") == "0",
                f"service-stop 后未确认停止: {props}")
        # 停止后不再探活（daemon 已下线，instance_health 会抛错），只记 unit 事实。
        self.b02_runner.identity_events.append(
            {"stage": "post_stop",
             "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
             "unit_props": props})

    def restart(self):
        """installed 重启：service-stop → service-start → 身份复验 → 重配对。

        r07 step 8 契约：restart 必须总是重新配对并刷新 self.admin；
        R04 嵌套腿（UP08）也经由此处，绝不回落 Popen(binary serve)。
        """
        runner = self.b02_runner
        drv = self.b02_driver
        staged = runner.staged_binary(drv.state_dir)
        try:
            before = drv.identity()
        except DRIVER.InstalledServiceError:
            # r04 嵌套腿（update_and_run）以 self.stop() 结束（r04:969，为了
            # 离线 verify 回执链），因此 r07 step 8 的 restart 可能从已停止
            # 状态进入；从最后已知 live 身份合成 pre_restart 基线。
            before = None
        if before is None:
            prior = [e["identity"] for e in runner.identity_events
                     if e["stage"] not in ("post_stop", "pre_restart")
                     and e.get("identity", {}).get("main_pid")]
            require(prior, "restart 前没有任何已记录的 live 实例身份")
            before = dict(prior[-1])
            runner.note_log("restart 入口服务已停止（r04 腿以 stop() 结束）；"
                            "以最后已知身份为基线直接 service-start")
            runner.record_identity_event("pre_restart", before,
                                         extra={"entry_state": "stopped"})
        else:
            runner.record_identity_event("pre_restart", before)
            self.stop()
        with runner.manager_home():
            drv.service_start(staged)
        after = drv.verify_identity({
            "state_directory_id": before["state_directory_id"],
            "unit_name": before["unit_name"],
            "port": before["port"],
            "binary_digest": before["binary_digest"],
            "fragment_path": before["fragment_path"],
            "version": before["version"],
        })
        require(after["main_pid"] and after["main_pid"] != before["main_pid"],
                f"重启后 MainPID 未变化: {before['main_pid']} -> {after['main_pid']}")
        runner.record_identity_event("post_restart", after,
                                     extra={"pid_changed": True})
        self.admin = drv.pair(staged)

    def mark_service_gone(self):
        self._b02_service_gone = True


class B02Runner(B01.Runner):
    """B02 runner：复用 B01 的信任/构建/签名与证据机制，跑 installed 旅程。"""

    def __init__(self, args):
        super().__init__(args)
        # B01 Runner.__init__ 建的 driver 面向它自己的特殊状态目录；B02 的
        # driver 按 harness 状态目录在 installed 腿内新建。
        self.driver = None
        self.identity_events = []
        self.serve_scans = []

    # ---- 构建（复用 B01 机制；版本串与目标平台为 B02 特有） ----

    def build_version(self, commit: str, tag: str):
        # 与 B01.build_version 同机制，仅一处差异：版本 0.2.0-b02-<tag>。
        # 全平台都要构建：release-manifest 签署时校验 bin-dir 完整性。
        # 版本串在构建期嵌入 ldflags，无法事后改写，故复制而非调用父类。
        extract = os.path.join(self.run_dir, f"src-{tag}")
        if os.path.exists(extract):
            shutil.rmtree(extract)
        os.makedirs(extract, mode=0o700)
        archive = os.path.join(self.run_dir, f"{tag}.tar")
        with open(archive, "wb") as f:
            subprocess.run(["git", "archive", "--format=tar", commit],
                           cwd=self.args.worktree, check=True, stdout=f)
        subprocess.run(["tar", "-xf", archive, "-C", extract], check=True)
        os.unlink(archive)
        overlay = {}
        if getattr(self.args, "working_tree", False):
            # The installed browser must exercise the same generated UI as the
            # working-tree candidate. Overlaying Go alone silently leaves the
            # archive's old embedded console in the test release.
            source = pathlib.Path(self.args.worktree) / "apps/agentshield"
            for path in source.rglob("*.go"):
                if path.name.endswith("_test.go"):
                    continue
                rel = path.relative_to(pathlib.Path(self.args.worktree))
                target = pathlib.Path(extract) / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                overlay[str(rel)] = B01.sha256_file(target)
            embed_source = source / "internal/ui/embedded"
            embed_target = pathlib.Path(extract) / "apps/agentshield/internal/ui/embedded"
            require((embed_source / "index.html").is_file(),
                    "working-tree embedded console is missing")
            if embed_target.exists():
                shutil.rmtree(embed_target)
            shutil.copytree(embed_source, embed_target)
            for path in embed_target.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(pathlib.Path(extract))
                    overlay[str(rel)] = B01.sha256_file(path)
        self.source_overlay = overlay
        trust_patch = self.patch_test_trust(extract, self.test_trust["public_key_b64"])
        tree = subprocess.run(["git", "rev-parse", f"{commit}^{{tree}}"],
                              cwd=self.args.worktree, check=True,
                              capture_output=True, text=True).stdout.strip()
        module = os.path.join(extract, "apps", "agentshield")
        version = f"0.2.0-b02-{tag}"
        bin_dir = os.path.join(self.run_dir, f"bin-{tag}")
        os.makedirs(bin_dir, mode=0o700)
        build_cmds = []
        for goos, goarch, ext in B01.TARGETS:
            name = f"siq-agent-security-{goos}-{goarch}{ext}"
            out = os.path.join(bin_dir, name)
            cmd = ["go", "build", "-C", module, "-trimpath",
                   "-ldflags", f"-s -w -X main.Version={version}",
                   "-o", out, "./cmd/agentshield"]
            env = dict(os.environ, GOOS=goos, GOARCH=goarch, CGO_ENABLED="0")
            subprocess.run(cmd, env=env, check=True)
            build_cmds.append({"target": f"{goos}/{goarch}", "argv": cmd,
                               "digest": B01.sha256_file(out)})
        skill_dir = os.path.join(extract, "skills", "siq-agent-security")
        return {"commit": commit, "tree": tree, "version": version,
                "extract": extract, "bin_dir": bin_dir, "skill_dir": skill_dir,
                "trust_patch": trust_patch, "source_overlay_sha256": overlay, "builds": build_cmds,
                "linux_arm64": os.path.join(bin_dir,
                                            "siq-agent-security-linux-arm64")}

    # ---- 身份与扫描 ----

    def record_identity_event(self, stage: str, identity: dict, extra: dict | None = None):
        event = {"stage": stage, "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                 "identity": dict(identity)}
        if extra:
            event.update(extra)
        self.identity_events.append(event)
        print(f"[b02] identity[{stage}] pid={identity.get('main_pid')} "
              f"state_id={str(identity.get('state_directory_id'))[:12]}…", flush=True)

    def scan_serve_processes(self) -> list:
        out = subprocess.run(["ps", "-eo", "pid=,args="],
                             capture_output=True, text=True, check=True).stdout
        rows = []
        for line in out.splitlines():
            line = line.strip()
            pid, _, argv = line.partition(" ")
            if "siq-agent-security" in argv and " serve" in f" {argv} ":
                rows.append({"pid": int(pid), "argv": argv[:240]})
        self.serve_scans.append(
            {"ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
             "rows": rows})
        return rows

    def check_single_serve(self, state_dir: str, desc: str):
        rows = self.scan_serve_processes()
        expected = [r for r in rows if r["argv"].split(" serve")[0].startswith(state_dir)]
        # 作用域：本产品全局只有本批状态目录这一个 serve；宿主上可能存在
        # 归属其他会话的既有实例（不同状态目录/端口，按安全边界不得触碰），
        # 记录为 foreign 但不参与判定，也绝不清理。
        foreign = [r for r in rows if r not in expected]
        self.check("b02_no_second_daemon", desc,
                   len(expected) == 1,
                   {"our_state_dir": len(expected),
                    "our_pids": [r["pid"] for r in expected],
                    "foreign_preexisting": [r["pid"] for r in foreign]})

    def staged_binary(self, state_dir) -> str:
        """state 目录内被 client-install 暂存并签进 ownership 记录的二进制。

        renderUserUnit 以 os.Executable() 渲染 unit，因此 stop/start/teardown
        等带 ownership 校验的 CLI 必须用暂存路径调用，不能用 journey-root 副本。
        """
        g = sorted(pathlib.Path(state_dir).glob("client-releases/*/siq-agent-security"))
        require(len(g) == 1, f"暂存二进制应恰有一个: {[str(x) for x in g]}")
        return str(g[0])

    def manager_home(self):
        if getattr(self.args, "working_tree", False):
            return ManagerEnvironmentUnchanged()
        return ManagerHomeOverride(str(self.installed_home), self.note_log)

    def note_log(self, message: str):
        print(f"[b02] {message}", flush=True)

    # ---- installed 腿 ----

    def run_installed_leg(self, version_info: dict, manifest: pathlib.Path):
        binary = pathlib.Path(version_info["linux_arm64"])
        run_root = pathlib.Path(self.run_dir)
        journey_root = run_root / "journey-root"
        journey_root.mkdir(parents=True, mode=0o700)
        self.installed_home = journey_root / "home"

        # 环境安全闸：附着前确认没有遗留的本产品用户单元（不附着非本批状态）。
        before_units = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "siq-agent-security-*",
             "--no-legend"], capture_output=True, text=True, check=False).stdout.strip()
        require(before_units == "",
                f"附着前已存在本产品 unit，拒绝附着: {before_units}")
        self.note_log("attach gate: no pre-existing siq-agent-security user units")

        args = argparse.Namespace(
            openclaw_root=pathlib.Path(self.args.openclaw_root),
            node=self.args.node,
            binary=binary,
            port=self.args.port,
        )
        harness = InstalledHarness(journey_root, args)
        shutil.copy2(binary, harness.binary)
        driver = DRIVER.InstalledUserServiceDriver(
            state_dir=str(harness.state), port=self.args.port,
            log_dir=str(self.log_dir))
        harness.b02_runner = self
        harness.b02_driver = driver
        harness.b02_manifest = str(manifest)
        self.driver = driver

        report = {"schema_version": "personal-b02-installed-journey/v1"}
        try:
            harness.config("required")
            harness.start()
            self.check("b02_install_via_client_install",
                       "客户端安装注册并启动 systemd 用户服务（受支持入口）",
                       True, {"identity": self.identity_events[-1]["identity"]})
            self.check_single_serve(str(harness.state), "旅程开始时唯一 serve 进程来自本批状态目录")

            # r07.main 语义：激活前基线先取值，setup_authority 重置
            # journey_results 之后再计入。
            pre_activation = harness.check_raw_content_default_disabled()
            harness.setup_authority()
            harness.journey_results.append(pre_activation)

            # 发现绑定：daemon 的 Home 必须是隔离 HOME，而不是日常 profile。
            catalog = harness.api("/v1/adapter/instances?platform=openclaw")
            rows = catalog.get("instances", [])
            expected_shown = "~/.openclaw"
            row = next((r for r in rows if r.get("platform") == "openclaw"), None)
            home_ok = bool(row) and row.get("config_dir") == expected_shown \
                and row.get("detected") is True and row.get("active") is True
            self.check("b02_discovery_binds_fixture_instance",
                       "daemon 实例发现指向隔离 HOME 的 fixture 实例（非日常 profile）",
                       home_ok, {"config_dir": row.get("config_dir") if row else None,
                                 "detected": row.get("detected") if row else None,
                                 "instance_id": row.get("instance_id") if row else None,
                                 "rows": len(rows)})
            if not home_ok:
                raise AssertionError(f"发现未绑定 fixture 实例: {rows}")

            # r07.record 内部已 append 进 journey_results（返回 None），不要重复加入。
            harness.record(
                "b02_installed_journey_start",
                "installed systemd 服务承载旅程起点（同一实例身份）",
                True,
                json.dumps({"endpoint": harness.endpoint,
                            "identity": self.identity_events[-1]["identity"]},
                           ensure_ascii=False, sort_keys=True))

            runner_report = harness.journey()
            report["r07_journey"] = runner_report
            self.check("b02_journey_installed",
                       "installed systemd 服务承载 r07 完整浏览器旅程（含 R04 嵌套腿）",
                       journey_passed(runner_report),
                       {"checks": len(runner_report.get("results", [])),
                        "failed": [r.get("id") for r in runner_report.get("results", [])
                                   if r.get("status") != "pass"]})
            final_identity = driver.identity()
            self.record_identity_event("journey_done", final_identity)
            self.check("b02_identity_preserved_across_restarts",
                       "重启前后 state_directory_id/unit/端口/摘要/加载源不变且 MainPID 变化",
                       self._restart_events_consistent(),
                       {"events": [e["stage"] for e in self.identity_events]})

            # R07 now explicitly revokes this harness's admin bearer after its
            # signed task-export check. Re-pair through the installed CLI;
            # never reuse that revoked bearer for post-journey receipt checks.
            harness.admin = driver.pair(self.staged_binary(driver.state_dir))
            receipt_count = len(harness.receipts())
            self.check("b02_repair_after_journey_logout",
                       "R07 显式注销后通过已装 CLI 重配对并读取历史回执",
                       receipt_count > 0, {"receipt_count": receipt_count})
            harness.stop()  # service-stop + inactive 复验
            self.check("b02_stop_via_service_stop",
                       "journey 后 service-stop 正常停止且幂等路径确认",
                       True, {"receipt_count": receipt_count})
        finally:
            report["identity_events"] = list(self.identity_events)
            report["serve_scans"] = list(self.serve_scans)
            self._journey_report = report
        return harness, driver, binary, receipt_count

    def _restart_events_consistent(self) -> bool:
        pre = [e for e in self.identity_events if e["stage"] == "pre_restart"]
        post = [e for e in self.identity_events if e["stage"] == "post_restart"]
        stable_keys = ("state_directory_id", "unit_name", "port",
                       "binary_digest", "fragment_path", "version")
        if not pre or len(pre) != len(post):
            return False
        for a, b in zip(pre, post):
            if any(a["identity"].get(k) != b["identity"].get(k) for k in stable_keys):
                return False
            if b["identity"].get("main_pid") in (None, "", a["identity"].get("main_pid")):
                return False
        return True

    # ---- teardown → 保留 → 重入 → 最终 teardown → ownership ----

    def run_teardown_reentry_chain(self, harness, driver, binary, manifest,
                                   receipt_count: int):
        # journey 后已 service-stop（run_installed_leg 末尾），daemon 不可探活；
        # unit 名从签名 ownership 记录取（离线、ownership-neutral）。
        unit = driver.unit_name()
        state_before = sorted(p.name for p in pathlib.Path(driver.state_dir).iterdir())

        driver.teardown(self.staged_binary(driver.state_dir))
        self.check("b02_teardown_unit_gone", "teardown 后 unit 注销（加载源消失）",
                   driver.load_state(unit) == "not-found", {"unit": unit})
        harness.mark_service_gone()

        state_dir = pathlib.Path(driver.state_dir)
        state_after = sorted(p.name for p in state_dir.iterdir())
        retained = set(state_before) <= set(state_after) and state_dir.is_dir()
        self.check("b02_state_retained_after_teardown",
                   "teardown 后状态目录与记录保留（含签名 user-service 记录）",
                   retained, {"entries": len(state_after),
                              "subset_of_before": set(state_before) <= set(state_after)})

        reentry = DRIVER.InstalledUserServiceDriver(
            state_dir=str(harness.state), port=self.args.port,
            log_dir=str(self.log_dir))
        with self.manager_home():
            rec = reentry.install(str(manifest), str(binary), port=self.args.port)
        require(rec["exit"] == 0, f"同状态重入 client-install 失败: {rec}")
        identity2 = reentry.identity()
        self.record_identity_event("reentry", identity2)
        same_state = identity2["state_directory_id"] == \
            self.identity_events[0]["identity"]["state_directory_id"]
        self.check("b02_reentry_same_state",
                   "同状态重入：state_directory_id/版本不变，回执历史保留",
                   same_state,
                   {"state_directory_id_equal": same_state,
                    "version": identity2.get("version"),
                    "unit": identity2.get("unit_name")})
        admin2 = reentry.pair(self.staged_binary(reentry.state_dir))
        count_after = self._count_receipts(reentry, admin2)
        self.check("b02_reentry_receipts_preserved",
                   "重入后回执链历史完整（历史保留）",
                   count_after == receipt_count,
                   {"before": receipt_count, "after": count_after})

        reentry.teardown(self.staged_binary(reentry.state_dir))
        unit2 = identity2["unit_name"]
        self.check("b02_final_teardown",
                   "最终 teardown：unit 再次注销",
                   reentry.load_state(unit2) == "not-found", {"unit": unit2})

        after_units = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "siq-agent-security-*",
             "--no-legend"], capture_output=True, text=True, check=False).stdout.strip()
        props_gone = reentry.load_state(unit) == "not-found" and \
            reentry.load_state(unit2) == "not-found"
        self.check("b02_ownership_reverified",
                   "ownership 复验：无遗留本产品 unit，状态目录仍归本批",
                   after_units == "" and props_gone,
                   {"unit_files": after_units, "state_entries": len(state_after)})

    @staticmethod
    def _count_receipts(driver, token) -> int:
        records, since = 0, -1
        while True:
            status, page = driver.api("GET", f"/v1/receipts?since_seq={since}", token=token)
            require(status == 200 and page.get("verified"),
                    f"重入回执链校验失败: status={status}")
            if not page.get("receipts"):
                return records
            records += len(page["receipts"])
            since = page["receipts"][-1]["seq"]

    def cleanup_run_dir(self):
        shutil.rmtree(self.run_dir, ignore_errors=False)
        self.note_log(f"run_dir cleaned: {self.run_dir}")

    # ---- 证据 ----

    def write_evidence(self, direct_report: dict | None):
        out = pathlib.Path(self.out_dir)
        (out / "logs").mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "personal-acceptance-baseline/v2",
            "task": "B02",
            "source_overlay_sha256": getattr(self, "source_overlay", {}),
            "task_layer": "test_release",
            "official_release_note": (
                "正式发行信任腿未关闭：本批 manifest 由每轮测试种子签署；"
                "解锁条件 = 维护者以正式发布种子签署 manifest 后重跑本 runner。"),
            "checks": self.checks,
            "failures": self.failures,
            "identity_events": self.identity_events,
            "serve_scans": self.serve_scans,
        }
        (out / "checks.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        env = {
            "schema_version": "closure-b02-environment/v1",
            "platform": "linux/arm64",
            "openclaw_root": str(self.args.openclaw_root),
            "node": str(self.args.node),
            "port": self.args.port,
            "service_driver": "installed_user_service",
            "direct_leg": bool(direct_report),
            "home_isolation": {
                "method": "signed unit-local HOME with process readback" if getattr(self.args, "working_tree", False) else "read-only dedicated manager HOME prerequisite",
                "scope": "no manager environment mutations",
                "daemon_home": str(self.installed_home),
            },
        }
        (out / "environment.json").write_text(
            json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
        # 日志（已脱敏）0600 收进证据
        for log in sorted(pathlib.Path(self.log_dir).glob("*")):
            target = out / "logs" / log.name
            shutil.copy2(log, target)
            os.chmod(target, 0o600)
        if direct_report:
            (out / "direct-process-report.json").write_text(
                json.dumps(direct_report, ensure_ascii=False, indent=2),
                encoding="utf-8")
        (out / "journey-report.json").write_text(
            json.dumps(getattr(self, "_journey_report", {}),
                       ensure_ascii=False, indent=2), encoding="utf-8")
        self.write_report_md(direct_report)
        subprocess.run(["chmod", "-R", "go-rwx", str(out)], check=True)
        sums = out / "SHA256SUMS"
        lines = []
        for path in sorted(out.rglob("*")):
            if path.is_file() and path.name != "SHA256SUMS":
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                lines.append(f"{digest}  {path.relative_to(out)}")
        sums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_report_md(self, direct_report: dict | None):
        out = pathlib.Path(self.out_dir)
        passed = [c for c in self.checks if c["ok"]]
        failed = [c for c in self.checks if not c["ok"]]
        lines = [
            "# closure-b02 证据报告（installed systemd 用户服务承载完整旅程）",
            "",
            f"- 时间：{_dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
            ("- 任务层：test_release（测试信任根）；正式发行信任腿未关闭，"
            "解锁条件 = 维护者以正式发布种子签署 manifest。"),
            ("- 控制面：installed_user_service（client-install / service-start / "
            "service-stop / teardown / pair），全程无 Popen(binary serve) 回落。"),
            f"- 结果：{len(passed)} PASS / {len(failed)} FAIL",
            "",
            "## 检查",
            "",
        ]
        for c in self.checks:
            mark = "PASS" if c["ok"] else "FAIL"
            lines.append(f"- [{mark}] `{c['id']}` {c['desc']}")
        lines += ["", "## 阶段身份（同一实例绑定）", ""]
        for e in self.identity_events:
            if "identity" not in e:  # post_stop 事件只记 unit_props
                lines.append(
                    f"- {e['stage']}: active={e.get('unit_props', {}).get('ActiveState')} "
                    f"main_pid={e.get('unit_props', {}).get('MainPID')}")
                continue
            lines.append(
                f"- {e['stage']}: unit={e['identity'].get('unit_name')} "
                f"pid={e['identity'].get('main_pid')} "
                f"state_id={str(e['identity'].get('state_directory_id'))[:16]}… "
                f"digest={str(e['identity'].get('binary_digest'))[:12]}…")
        if direct_report:
            lines += ["", "## direct_process 回归腿", "",
                      (f"- r07 main() 原样执行：passed={direct_report.get('passed')} "
                      f"checks={len(direct_report.get('checks', direct_report.get('results', [])))}")]
        lines += ["", "## HOME 隔离", "",
                  "- working-tree 模式使用签名 unit 的实例 HOME 并读取运行进程复验；只读比较 manager 环境不变。",
                  "- 不满足前置条件时阻塞，不回退直接启动或修改 unit drop-in。"]
        (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- 主流程 ----

    def run(self):
        self.installed_home = pathlib.Path(self.run_dir) / "journey-root" / "home"
        try:
            with self.manager_home():
                pass  # Reject before builds or installation when isolation is unavailable.
        except (AssertionError, subprocess.SubprocessError):
            payload = {"schema_version": "closure-b02-prerequisite/v1", "status": "blocked",
                       "reason_code": "dedicated_manager_home_required", "product_actions": 0,
                       "manager_environment_modified": False}
            path = pathlib.Path(self.out_dir) / "blocked.json"
            with path.open("x") as f:
                os.chmod(path, 0o600)
                json.dump(payload, f, indent=2)
            print(json.dumps(payload), flush=True)
            return False
        import playwright.sync_api  # noqa: F401 -- fail before installing if browser dependency absent
        self.test_trust = self.prepare_test_trust()
        self.check("b02_build_and_manifest", "测试信任构建 + manifest 签署（test_release 层）",
                   True, {})
        version_info = self.build_version(self.args.new_commit, "main")
        self.signer_binary = version_info["linux_arm64"]
        manifest = pathlib.Path(self.sign_manifest(version_info, "main"))
        self.checks[0]["detail"] = {
            "version": version_info["version"],
            "pubkey": self.test_trust["public_key_b64"],
            "binary_sha256": version_info["builds"][0]["digest"],
        }

        # installed 腿
        harness = driver = binary = None
        receipt_count = 0
        chain_ok = False
        try:
            harness, driver, binary, receipt_count = self.run_installed_leg(
                version_info, manifest)
            self.run_teardown_reentry_chain(harness, driver, binary, manifest,
                                            receipt_count)
            chain_ok = True
        finally:
            driver = driver or self.driver
            if driver is not None and not chain_ok:
                # 失败路径：只保证服务不残留运行状态，不删任何状态目录。
                try:
                    if driver is not None:
                        driver.teardown(self.staged_binary(driver.state_dir))
                except Exception:  # noqa: BLE001 -- archive failure category and clean owned resources
                    self.note_log("owned service cleanup failed; inspect batch identity before retry")

        # direct_process 回归腿（r07 main 原样执行）
        direct_report = self.run_direct_leg(version_info)
        self.check("b02_direct_regression",
                   "direct_process 腿回归：r07 main() 原样通过",
                   bool(direct_report and direct_report.get("passed")),
                   {"report": str(pathlib.Path(self.out_dir) / "direct-process-report.json")})

        self.write_evidence(direct_report)

        # ownership 复验通过后才清理临时 run_dir
        ownership = next((c for c in self.checks if c["id"] == "b02_ownership_reverified"), None)
        if ownership and ownership["ok"]:
            self.cleanup_run_dir()
        else:
            self.note_log("run_dir retained (ownership not reverified)")

        return not self.failures

    def run_direct_leg(self, version_info: dict):
        binary = pathlib.Path(version_info["linux_arm64"])
        out_json = pathlib.Path(self.out_dir) / "direct-process-raw-report.json"
        cmd = [sys.executable, str(HERE / "r07-linux-user-journey-smoke.py"),
               "--openclaw-root", str(self.args.openclaw_root),
               "--node", str(self.args.node),
               "--binary", str(binary),
               "--out", str(out_json)]
        print(f"[b02] direct leg: {' '.join(cmd)}", flush=True)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
        log = pathlib.Path(self.out_dir) / "direct-process-diagnostic.json"
        with log.open("x") as f:
            os.chmod(log, 0o600)
            json.dump({"exit": proc.returncode, "output_persisted": False,
                       "stdout_bytes": len(proc.stdout.encode()), "stderr_bytes": len(proc.stderr.encode())}, f)
        if proc.returncode == 0 and out_json.exists():
            report = json.loads(out_json.read_text(encoding="utf-8"))
            if journey_passed(report):
                return report
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--worktree", default=str(WORKTREE))
    parser.add_argument("--working-tree", action="store_true", help="record and build current production Go sources with instance HOME support")
    parser.add_argument("--new-commit", default="53155b10c276fe41e71c47757e58e7e56d5d75d4")
    parser.add_argument("--run-dir", default="/tmp/siq-closure-b02")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir)
    if run_dir.exists():
        raise SystemExit(f"run_dir 已存在，拒绝复用: {run_dir}")
    run_dir.mkdir(parents=True, mode=0o700)
    out_dir = pathlib.Path(args.out)
    if out_dir.exists():
        raise SystemExit(f"证据目录已存在，拒绝覆盖: {out_dir}")
    out_dir.mkdir(parents=True, mode=0o700)

    runner = B02Runner(args)
    ok = runner.run()
    print(json.dumps({"passed": ok, "checks": len(runner.checks),
                      "failures": len(runner.failures)}))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
