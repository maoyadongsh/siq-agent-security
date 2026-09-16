#!/usr/bin/env python3
"""B01 生命周期 runner：Linux 安装/升级/中断恢复/回滚/保留状态重入（test_release 层）。

只走产品 CLI 与 systemd --user；复用 installed_user_service_driver。
不读取未授权发布私钥：签署用每次运行新生成的测试种子（test_release），
证据只记录公钥与摘要；测试种子仅保留在私有临时运行目录。

用法（例）:
  /home/maoyd/miniconda3/bin/python3 scripts/personal-experience/closure-b01-lifecycle-runner.py \
      --worktree /home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914 \
      --old-commit efad840 --new-commit 53155b1 \
      --port 25173 --out docs/evidence/personal-experience/closure-b01-<ts>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import selectors
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from installed_user_service_driver import (
    InstalledUserServiceDriver,
    sha256_file,
)

TARGETS = [("linux", "amd64", ""), ("linux", "arm64", ""),
           ("darwin", "arm64", ""), ("windows", "amd64", ".exe")]
TX_RE = re.compile(r"切换事务：(\S+)")


class Runner:
    def __init__(self, args):
        self.args = args
        self.out_dir = os.path.abspath(args.out)
        self.run_dir = os.path.abspath(args.run_dir)
        os.makedirs(self.run_dir, mode=0o700, exist_ok=True)
        os.chmod(self.run_dir, 0o700)
        self.log_dir = os.path.join(self.run_dir, "cli-logs")
        os.makedirs(self.log_dir, mode=0o700, exist_ok=True)
        self.evidence_logs = os.path.join(self.out_dir, "logs")
        os.makedirs(self.evidence_logs, mode=0o700, exist_ok=True)
        self.checks: list[dict] = []
        self.failures: list[dict] = []
        self.driver = InstalledUserServiceDriver(
            state_dir=os.path.join(self.run_dir, "state 中文 空格%25实例"),
            port=args.port, log_dir=self.log_dir)
        self._check_seq = 0

    # ---------- 记录 ----------

    def check(self, cid: str, desc: str, ok: bool, detail: dict | None = None,
              level: str = "observed") -> dict:
        entry = {"id": cid, "desc": desc, "ok": bool(ok), "level": level,
                 "detail": detail or {}, "ts": time.strftime("%H:%M:%S")}
        self.checks.append(entry)
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {cid}: {desc}" + ("" if ok else f"  detail={json.dumps(detail, ensure_ascii=False)[:400]}"))
        if not ok:
            self.failures.append(entry)
        return entry

    def note(self, cid: str, desc: str, detail: dict | None = None):
        """not_exercised / component-covered 登记项。"""
        entry = {"id": cid, "desc": desc, "ok": None, "status": "not_exercised",
                 "level": "not_exercised", "detail": detail or {}}
        self.checks.append(entry)
        print(f"[NOT_EXERCISED] {cid}: {desc}")
        return entry

    def state_tree_digest(self, path: str) -> dict:
        """状态目录树摘要（相对路径排序 + 各文件 sha256 + 文件数）。"""
        entries = {}
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs]
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, path)
                if os.path.islink(full):
                    entries[rel] = "link:" + os.readlink(full)
                else:
                    entries[rel] = sha256_file(full)
        blob = json.dumps(entries, sort_keys=True, ensure_ascii=False).encode()
        return {"file_count": len(entries), "tree_digest": hashlib.sha256(blob).hexdigest(),
                "entries": entries}

    # ---------- 测试信任材料（test_release 层） ----------

    TRUST_CONST = re.compile(
        r'(const ReleasePublicKeyB64 = )"([^"]+)"')

    def prepare_test_trust(self) -> dict:
        """一次性测试种子 → 固定测试公钥（仅注入测试构建，不动生产信任根）。

        种子写 run_dir（0700），证据只记录公钥与补丁说明。
        正式发行信任根 leg 保持 blocked，解锁条件=维护者用正式种子签署 manifest。
        """
        seed = base64.b64encode(os.urandom(32)).decode()
        seed_path = os.path.join(self.run_dir, "release-seed.b64")
        fd = os.open(seed_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(seed + "\n")
        helper = os.path.join(self.run_dir, "derive_pubkey.go")
        with open(helper, "w") as f:
            f.write(
                "package main\n\n"
                "import (\n"
                "\t\"crypto/ed25519\"\n"
                "\t\"encoding/base64\"\n"
                "\t\"fmt\"\n"
                "\t\"os\"\n"
                "\t\"io\"\n"
                ")\n\n"
                "func main() {\n"
                "\traw, err := io.ReadAll(io.LimitReader(os.Stdin, 1024))\n"
                "\tif err != nil { os.Exit(2) }\n"
                "\tseed, err := base64.StdEncoding.DecodeString(string(raw))\n"
                "\tif err != nil || len(seed) != ed25519.SeedSize {\n"
                "\t\tfmt.Fprintln(os.Stderr, \"bad seed\")\n"
                "\t\tos.Exit(2)\n"
                "\t}\n"
                "\tpub := ed25519.NewKeyFromSeed(seed).Public().(ed25519.PublicKey)\n"
                "\tfmt.Println(base64.StdEncoding.EncodeToString(pub))\n"
                "}\n")
        proc = subprocess.run(["go", "run", helper], input=seed,
                              capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0:
            raise RuntimeError("derive pubkey failed")
        pub = proc.stdout.strip()
        return {"seed_path": seed_path, "public_key_b64": pub,
                "production_public_key_b64":
                    "LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY="}

    def patch_test_trust(self, extract: str, pub: str) -> dict:
        """仅在被抽取的测试源码树内替换信任根常量；worktree 不受影响。"""
        path = os.path.join(extract, "apps", "agentshield",
                            "internal", "skillmanifest", "manifest.go")
        src = Path(path).read_text()
        m = self.TRUST_CONST.search(src)
        if not m:
            raise RuntimeError(f"trust const not found in {path}")
        patched = self.TRUST_CONST.sub(lambda mm: mm.group(1) + f'"{pub}"', src,
                                       count=1)
        Path(path).write_text(patched)
        return {"file": os.path.relpath(path, extract),
                "production": m.group(2), "test": pub}

    # ---------- 构建（独立 archive，双版本可追溯） ----------

    def build_version(self, commit: str, tag: str) -> dict:
        extract = os.path.join(self.run_dir, f"src-{tag}")
        os.makedirs(extract, mode=0o700)
        archive = os.path.join(self.run_dir, f"{tag}.tar")
        with open(archive, "wb") as f:
            subprocess.run(["git", "archive", "--format=tar", commit],
                           cwd=self.args.worktree, check=True, stdout=f)
        subprocess.run(["tar", "-xf", archive, "-C", extract], check=True)
        os.unlink(archive)
        trust_patch = self.patch_test_trust(extract, self.test_trust["public_key_b64"])
        tree = subprocess.run(["git", "rev-parse", f"{commit}^{{tree}}"],
                              cwd=self.args.worktree, check=True,
                              capture_output=True, text=True).stdout.strip()
        module = os.path.join(extract, "apps", "agentshield")
        version = f"0.2.0-b01-{tag}"
        bin_dir = os.path.join(self.run_dir, f"bin-{tag}")
        os.makedirs(bin_dir, mode=0o700)
        build_cmds = []
        for goos, goarch, ext in TARGETS:
            name = f"siq-agent-security-{goos}-{goarch}{ext}"
            out = os.path.join(bin_dir, name)
            cmd = ["go", "build", "-C", module, "-trimpath",
                   "-ldflags", f"-s -w -X main.Version={version}",
                   "-o", out, "./cmd/agentshield"]
            env = dict(os.environ, GOOS=goos, GOARCH=goarch, CGO_ENABLED="0")
            subprocess.run(cmd, env=env, check=True)
            build_cmds.append({"target": f"{goos}/{goarch}", "argv": cmd,
                               "digest": sha256_file(out)})
        skill_dir = os.path.join(extract, "skills", "siq-agent-security")
        return {"commit": commit, "tree": tree, "version": version,
                "extract": extract, "bin_dir": bin_dir, "skill_dir": skill_dir,
                "trust_patch": trust_patch,
                "builds": build_cmds,
                "linux_arm64": os.path.join(bin_dir, "siq-agent-security-linux-arm64")}

    def sign_manifest(self, version_info: dict, tag: str,
                      client_compatible: bool = True) -> str:
        """用本批测试种子签署 manifest；种子仅存 run_dir(0700)，证据只记公钥。"""
        env = dict(os.environ)
        env["SIQ_AGENT_SECURITY_RELEASE_SEED"] = \
            Path(self.test_trust["seed_path"]).read_text().strip()
        out = os.path.join(self.run_dir, f"manifest-{tag}"
                           + ("" if client_compatible else "-v2nocompat") + ".json")
        signer = self.signer_binary
        cmd = [signer, "release-manifest",
               "--skill-dir", version_info["skill_dir"],
               "--bin-dir", version_info["bin_dir"],
               "--version", version_info["version"],
               "--out", out] + (["--client-compatible"] if client_compatible else [])
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=300, check=False)
        if proc.returncode != 0:
            raise RuntimeError("release-manifest failed")
        # 测试密钥告警只记录字节数；test_release 来源由 manifest 公钥证明。
        with open(os.path.join(self.evidence_logs, f"release-manifest-{tag}"
                               + ("" if client_compatible else "-v2nocompat") + ".log"),
                  "w") as f:
            os.chmod(f.name, 0o600)
            json.dump({"exit": proc.returncode, "stderr_bytes": len(proc.stderr.encode()), "output_persisted": False}, f)
        return out

    # ---------- LC 阶段 ----------

    def lc01_install_precheck(self, old: dict, new: dict):
        scratch = os.path.join(self.run_dir, "lc01-state")
        os.makedirs(scratch, mode=0o700)
        drv = InstalledUserServiceDriver(state_dir=scratch, port=self.args.port,
                                         log_dir=self.log_dir)
        binary = old["linux_arm64"]
        old_manifest = self.old_manifest
        # 先形成 marker v2 状态（产品入口 init）。
        drv.run_cli(binary, ["init", "--port", str(self.args.port)])
        before = self.state_tree_digest(scratch)
        units_before = self._owned_units_snapshot()

        tampered = os.path.join(self.run_dir, "lc01-tampered-manifest.json")
        raw = bytearray(Path(old_manifest).read_bytes())
        raw[len(raw) // 2] ^= 0x20
        Path(tampered).write_bytes(bytes(raw))
        wrong_digest_binary = new["linux_arm64"]

        negatives = [
            ("lc01_no_confirm", "缺 --confirm-install 拒绝",
             [binary, "client-install", "--manifest", old_manifest,
              "--binary", binary]),
            ("lc01_bad_signature", "篡改 manifest 签名拒绝",
             [binary, "client-install", "--manifest", tampered,
              "--binary", binary, "--confirm-install"]),
            ("lc01_digest_mismatch", "manifest 摘要与二进制不符拒绝",
             [binary, "client-install", "--manifest", old_manifest,
              "--binary", wrong_digest_binary, "--confirm-install"]),
            ("lc01_state_incompatible", "无状态兼容声明（v2 manifest，marker v2）拒绝",
             [binary, "client-install", "--manifest", self.old_manifest_v2nocompat,
              "--binary", binary, "--confirm-install"]),
        ]
        for cid, desc, argv in negatives:
            rec = drv.run_cli(argv[0], argv[1:], check=False)
            refused = rec["exit"] != 0
            self.check(cid, desc, refused,
                       {"exit": rec["exit"], "stderr": drv._one_line(rec.get("stderr", ""))})
        after = self.state_tree_digest(scratch)
        units_after = self._owned_units_snapshot()
        self.check("lc01_no_side_effect", "拒绝前后状态目录与用户单位不变",
                   before["tree_digest"] == after["tree_digest"]
                   and units_before == units_after,
                   {"before": before["tree_digest"], "after": after["tree_digest"],
                    "units_before": units_before, "units_after": units_after})
        drv.drop_admin()

    def _owned_units_snapshot(self, pattern: str = "siq-agent-security-") -> list[str]:
        out = subprocess.run(["systemctl", "--user", "list-unit-files", "--no-legend"], check=True,
                             capture_output=True, text=True).stdout
        return sorted(line.split()[0] for line in out.splitlines()
                      if pattern in line)

    def lc02_pairing(self, binary: str):
        d = self.driver
        fresh_code = d.pairing_code(binary)
        status, _ = d.api("POST", "/v1/pair", token="",
                          payload={"code": "dead-beef-dead-beef"})
        self.check("lc02_pair_invalid", "新码尚未消费时错误配对码拒绝", status == 401,
                   {"status": status})
        valid_status, body = d.api("POST", "/v1/pair", payload={"code": fresh_code})
        token = body.get("session", "")
        self.check("lc02_pair_valid", "错误码重试后同一正确码换得管理会话",
                   valid_status == 200 and bool(token), {"status": valid_status})
        d._admin_token = token  # Only memory; the real response is never logged.
        status2, _ = d.api("POST", "/v1/pair", token="", payload={"code": fresh_code})
        self.check("lc02_pair_replay", "真实已消费配对码重放拒绝", status2 == 401,
                   {"status": status2})
        if getattr(self.args, "skip_pair_expiry", False):
            self.note("lc02_expired_code", "本次显式跳过真实 5 分钟过期，不计为通过")
        else:
            expiry_code = d.pairing_code(binary)
            started = time.monotonic()
            while time.monotonic() - started < 301:
                time.sleep(max(0, min(30, 301 - (time.monotonic() - started))))
                print("[pending] lc02 real pairing expiry; clock unchanged", flush=True)
            elapsed = time.monotonic() - started
            status, _ = d.api("POST", "/v1/pair", payload={"code": expiry_code})
            self.check("lc02_expired_code", "真实未消费配对码自然过期拒绝",
                       elapsed >= 300 and status == 401, {"elapsed_seconds": elapsed, "status": status})
            self.check("lc02_after_expiry_repair", "过期后新码重新配对成功", bool(d.pair(binary)))

    def lc04_background(self, binary: str):
        d = self.driver
        unit = d.unit_name()
        props = d.unit_properties(unit, ["MainPID", "FragmentPath", "ExecStart",
                                         "ActiveState", "UnitFileState"])
        installed_fragment = os.path.join(d.state_dir, unit)
        self.check("lc04_unit_precise", "精确 runtime 用户单位加载并运行"
                   "（FragmentPath 解析到本批源文件；ExecStart 指向 staged 程序）",
                   props.get("ActiveState") == "active"
                   and props.get("UnitFileState") in ("linked-runtime", "enabled-runtime")
                   and bool(props.get("FragmentPath"))
                   and os.path.realpath(props["FragmentPath"]) == os.path.realpath(installed_fragment)
                   and os.path.isfile(installed_fragment)
                   and d.state_dir in str(props.get("ExecStart", "")),
                   {"unit": unit, "fragment_path": props.get("FragmentPath"),
                    "installed_fragment": installed_fragment,
                    "state_unit_rendered": os.path.isfile(
                        os.path.join(d.state_dir, unit)),
                    "props": {k: props.get(k) for k in
                              ("MainPID", "ActiveState", "UnitFileState")}})
        pid1 = props.get("MainPID")
        d.service_start(binary)
        props2 = d.unit_properties(unit, ["MainPID"])
        self.check("lc04_no_second_process", "重复启动无第二进程（MainPID 稳定）",
                   props2.get("MainPID") == pid1,
                   {"pid_before": pid1, "pid_after": props2.get("MainPID")})
        refused = d.service_start_refused(binary)
        self.check("lc04_stop_needs_confirm", "service-stop 缺确认拒绝",
                   refused["exit"] != 0, {"exit": refused["exit"]})
        d.service_stop(binary)
        stopped = d.unit_properties(unit, ["ActiveState"]).get("ActiveState")
        d.service_start(binary)
        active = d.unit_properties(unit, ["ActiveState"]).get("ActiveState")
        self.check("lc04_restart", "stop→start 后服务恢复",
                   stopped == "inactive" and active == "active",
                   {"stopped": stopped, "active": active})
        status, _ = d.api("GET", "/v1/grants", token=d.admin_token or "stale")
        self.check("lc04_session_after_restart", "重启后旧管理会话不再有效",
                   status == 401, {"status": status})
        d.drop_admin()

    def lc06_upgrade(self, old: dict, new: dict, binary: str):
        """binary=当前 staged 旧程序路径（service-upgrade 要求 os.Executable 位置一致）。"""
        d = self.driver
        before = d.identity()
        staged_old, digest_old = before["running_binary_path"], before["binary_digest"]
        rec = d.upgrade(staged_old, self.new_manifest, new["linux_arm64"],
                        source_manifest=self.old_manifest)
        m = TX_RE.search(rec["stdout"] or "")
        self.check("lc06_upgrade_tx", "双版本升级完成并记录事务号", m is not None,
                   {"stdout_bytes": len((rec["stdout"] or "").encode())})
        tx = m.group(1) if m else None
        after = d.verify_identity({
            "version": new["version"],
            "state_directory_id": before["state_directory_id"],
        })
        self.settle_installed_identity(after)
        self.check("lc06_identity_kept", "升级后身份/端口/单位保持",
                   after["state_directory_id"] == before["state_directory_id"]
                   and after["unit_name"] == before["unit_name"]
                   and after["binary_digest"] != digest_old,
                   {"digest_old": digest_old, "digest_new": after["binary_digest"]})
        return tx, staged_old, after

    def settle_installed_identity(self, identity: dict):
        self.installed_identity = identity
        self.driver.set_current_cli(identity["running_binary_path"])

    def lc07_rollback_recover(self, old: dict, new: dict, tx: str | None,
                              staged_old: str):
        d = self.driver
        cur = self.installed_identity
        # 错路径回滚拒绝：--binary 指到与事务源摘要不符的二进制。
        wrong = d.rollback(cur["running_binary_path"], tx or "b01-no-tx",
                           new["linux_arm64"], manifest=self.old_manifest,
                           check=False)
        self.check("lc07_rollback_wrong_path", "回滚二进制与历史摘要不符拒绝",
                   wrong["exit"] != 0,
                   {"exit": wrong["exit"], "stderr": d._one_line(wrong.get("stderr", ""))})
        # 真回滚：精确历史路径（事务内记录的 staged 旧程序路径 + 旧 manifest）。
        # service-rollback 校验 renderUserUnit(--binary) == plan.SourceUnit，
        # 即必须是升级时运行的 staged 路径，repo 构建产物路径会被拒。
        rec = d.rollback(cur["running_binary_path"], tx or "b01-no-tx",
                         staged_old, manifest=self.old_manifest)
        self.check("lc07_rollback", "精确历史路径回滚完成", rec["exit"] == 0, {})
        after = d.verify_identity({"version": old["version"]})
        self.settle_installed_identity(after)
        self.check("lc07_rollback_identity", "回滚后运行旧摘要且身份保持",
                   after["binary_digest"] != cur["binary_digest"]
                   and after["state_directory_id"] == cur["state_directory_id"],
                   {"digest": after["binary_digest"]})
        # 中断恢复：升级中断注入（读出事务号即杀），随后 --recover。
        interrupted = self._interrupted_upgrade(old, new)
        if interrupted.get("tx"):
            rec = d.upgrade(after["running_binary_path"], self.new_manifest,
                            new["linux_arm64"], recover_id=interrupted["tx"])
            self.check("lc07_recover", "中断事务经 --recover 恢复完成",
                       rec["exit"] == 0, {"tx": interrupted["tx"]})
            after2 = d.verify_identity({"version": new["version"]})
            self.settle_installed_identity(after2)
        else:
            self.note("lc07_recover", "中断注入未捕获到已 Prepare 的事务（按次记录）",
                      interrupted)

    def _interrupted_upgrade(self, old: dict, new: dict) -> dict:
        d = self.driver
        attempts = []
        for delay in (0.05, 0.12, 0.3, 0.6, 1.0):
            identity = d.identity()
            cli = identity["running_binary_path"]
            cur_version = identity["version"]
            if cur_version == new["version"]:
                # 上一轮已完成升级；先回滚到旧版再试。
                return {"reason": "already_at_target_before_next_attempt",
                        "attempts": attempts}
            argv = [cli, "service-upgrade", "--manifest", self.new_manifest,
                    "--binary", new["linux_arm64"], "--confirm-upgrade",
                    "--source-manifest", self.old_manifest]
            env = d._env()
            proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            tx = None
            deadline = time.monotonic() + 60
            observed = ""
            # readline() could block past the declared deadline when the child
            # emits a partial line. Read only ready pipe bytes with a bounded
            # buffer; only this Popen-owned child may be terminated.
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while time.monotonic() < deadline:
                    if not selector.select(timeout=0.2):
                        if proc.poll() is not None:
                            break
                        continue
                    chunk = os.read(proc.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    observed += chunk.decode("utf-8", errors="replace")
                    if len(observed) > 65536:
                        break
                    m = TX_RE.search(observed)
                    if m and "\n" in observed[m.end():]:
                        tx = m.group(1)
                        time.sleep(delay)
                        break
            if proc.poll() is None:
                proc.kill()
            _out_tail, err_tail = proc.communicate(timeout=30)
            unit = d.unit_name()
            active = d.unit_properties(unit, ["ActiveState"]).get("ActiveState")
            attempts.append({"delay": delay, "tx_found": tx is not None,
                             "active_after_kill": active,
                             "stderr": d._one_line(err_tail)})
            if tx and active != "active":
                return {"tx": tx, "attempts": attempts}
            if tx and active == "active":
                # 升级在中断注入前已完成：精确历史路径（升级前 staged 旧程序）
                # 回滚后重试下一延迟。
                rec = d.rollback(cli, tx, cli,
                                 manifest=self.old_manifest, check=False)
                attempts[-1]["rollback_after_complete"] = rec["exit"]
                if rec["exit"] == 0:
                    after = d.verify_identity({"version": old["version"]})
                    self.settle_installed_identity(after)
                continue
            if proc.poll() != 0 or active != "active":
                # 进程已死且无事务 → 可直接重试全新升级。
                rec = d.upgrade(cli, self.new_manifest, new["linux_arm64"],
                                source_manifest=self.old_manifest, check=False)
                attempts[-1]["retry_upgrade_exit"] = rec["exit"]
                if rec["exit"] == 0:
                    after = d.verify_identity({"version": new["version"]})
                    self.settle_installed_identity(after)
                    attempts[-1]["state"] = "retry_completed_cleanly"
                    continue
        return {"reason": "no_interrupted_transaction_captured", "attempts": attempts}

    def lc08_unknown_objects(self, old: dict, new: dict):
        d = self.driver
        keep_file = os.path.join(d.state_dir, "b01-unknown-user-file.txt")
        with open(keep_file, "w") as f:
            f.write("unknown user object; must survive lifecycle\n")
        keep_link = os.path.join(d.state_dir, "b01-unknown-user-link")
        if not os.path.lexists(keep_link):
            os.symlink("b01-unknown-user-file.txt", keep_link)
        # Unknown-file fixture belongs to this run, never the real user search path.
        fake_unit = os.path.join(d.state_dir, "b01-unknown-user-unit.service")
        with open(fake_unit, "x") as f:
            f.write("[Unit]\nDescription=unknown fixture; must survive\n")
        before_file, before_link = sha256_file(keep_file), os.readlink(keep_link)
        # 生命周期动作（service-start 幂等 + 版本内升级式 restart 均可；用 start+stop）。
        d.service_start(self.installed_identity["running_binary_path"])
        d.service_stop(self.installed_identity["running_binary_path"])
        d.service_start(self.installed_identity["running_binary_path"])
        after_file, after_link = sha256_file(keep_file), os.readlink(keep_link)
        unit_kept = os.path.lexists(fake_unit)
        self.check("lc08_unknown_preserved", "状态目录未知文件/链接/单位源文件不被覆盖删除（非 manager 单位）",
                   before_file == after_file and before_link == after_link
                   and unit_kept,
                   {"file": before_file == after_file, "link": before_link == after_link,
                    "unit_kept": unit_kept})

    def lc09_teardown_reentry(self, old: dict, new: dict):
        d = self.driver
        binary = self.installed_identity["running_binary_path"]
        admin = d.pair(binary)
        fixture = os.path.join(self.run_dir, "retained-grant-fixture")
        os.mkdir(fixture, 0o700)
        with open(os.path.join(fixture, "SKILL.md"), "x") as f:
            f.write("---\nname: retained-grant-fixture\ndescription: Read synthetic text.\n---\nRead a synthetic report.\n")
        status, admitted = d.api("POST", "/v1/admit", token=admin, payload={"path": fixture})
        if status != 200:
            raise RuntimeError("retained grant admission failed")
        status, granted = d.api("POST", "/v1/grants", token=admin,
            payload={"admission_id": admitted["admission"]["admission_id"], "platform": "hermes",
                     "subject_id": "retained-fixture"})
        if status != 200:
            raise RuntimeError("retained grant create failed")
        grant_route = "/v1/grants/" + granted["grant"]["grant_id"]
        status, revoked = d.api("POST", grant_route + "/revoke", token=admin,
            payload={"expected_revision": granted["state_revision"], "actor_id": "fixture-operator"})
        if status != 200 or revoked["grant"]["status"] != "revoked":
            raise RuntimeError("retained grant revoke failed")
        revoked_signature = revoked["grant"]["signature"]
        revoked_revision = revoked["state_revision"]
        before_tree = self.state_tree_digest(d.state_dir)
        before_id = d.identity()
        d.teardown(binary)
        unit = before_id["unit_name"]
        load = d.load_state(unit)
        self.check("lc09_teardown_unit_gone", "teardown 后单位已注销",
                   load == "not-found", {"load_state": load})
        kept = os.path.isdir(d.state_dir)
        after_tree = self.state_tree_digest(d.state_dir)
        retained = sorted(set(before_tree["entries"]) & set(after_tree["entries"]))
        # 至少身份/配置类文件仍在（不以运行期临时文件消失判失败）。
        self.check("lc09_state_retained", "teardown 保留状态目录（身份/配置条目仍在）",
                   kept and bool(retained)
                   and before_id["state_directory_id"] is not None,
                   {"state_dir_kept": kept,
                    "retained_entry_count": len(retained),
                    "retained_sample": retained[:10],
                    "entries_before": before_tree["file_count"],
                    "entries_after": after_tree["file_count"]})
        # 重入：经受支持入口（client-install）同一状态目录重启。
        # 保留的 user-service 记录绑定 teardown 前最后运行的 staged 程序
        # （unit 摘要签名）；用其他版本重入会触发 "explicit migration
        # required" 设计面拒绝，故以最新已验证版本（new）重入。
        d2 = InstalledUserServiceDriver(state_dir=d.state_dir, port=self.args.port,
                                        log_dir=self.log_dir)
        d2.set_current_cli(new["linux_arm64"])
        rec = d2.install(self.new_manifest, new["linux_arm64"],
                         port=self.args.port, check=False)
        self.check("lc09_reentry_install", "保留状态上经 client-install 重入成功",
                   rec["exit"] == 0,
                   {"exit": rec["exit"], "stderr": d2._one_line(rec.get("stderr", ""))})
        if rec["exit"] != 0:
            return
        after = d2.verify_identity({
            "state_directory_id": before_id["state_directory_id"],
            "version": new["version"],
        })
        self.settle_installed_identity(after)
        self.check("lc09_identity_reused", "重入未重新生成身份（同 directory_id）",
                   after["state_directory_id"] == before_id["state_directory_id"],
                   {"directory_id": after["state_directory_id"]})
        status, _ = d2.api("GET", "/v1/grants", token=admin)
        self.check("lc09_old_session_invalid", "重入拒绝原来的真实管理会话", status == 401, {"status": status})
        new_admin = d2.pair(after["running_binary_path"])
        status, retained_grant = d2.api("GET", grant_route, token=new_admin)
        self.check("lc09_grant_revocation", "重入后真实已撤 Grant 的签名、状态和 revision 保留",
            status == 200 and retained_grant["grant"]["status"] == "revoked"
            and retained_grant["grant"]["signature"] == revoked_signature
            and retained_grant["state_revision"] == revoked_revision, {"status": status})
        status, _ = d2.api("POST", grant_route + "/deploy", token=new_admin,
            payload={"expected_revision": revoked_revision, "actor_id": "fixture-operator"})
        read_status, final_grant = d2.api("GET", grant_route, token=new_admin)
        self.check("lc09_revoked_deploy_refused", "撤销的 Grant 不能在重入后重新部署",
            status == 400 and read_status == 200 and final_grant["grant"] == retained_grant["grant"]
            and final_grant["state_revision"] == revoked_revision, {"status": status})

    def lc03_special_paths_ports(self, old: dict):
        # 端口占用：本批自持监听者，预期真实失败证据，不停止占用者。
        # 使用 lc01 已 init 的状态目录，失败原因可归因到端口而非缺状态。
        occupied_port = self.args.port + 6
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", occupied_port))
        blocker.listen(1)
        drv = InstalledUserServiceDriver(
            state_dir=os.path.join(self.run_dir, "lc01-state"),
            port=occupied_port, log_dir=self.log_dir)
        units_before = self._owned_units_snapshot("siq-agent-security-")
        try:
            rec = drv.install(self.old_manifest, old["linux_arm64"],
                              port=occupied_port, check=False)
            err = drv._one_line(rec.get("stderr", "") or rec.get("stdout", ""))
            still_listening = blocker.getsockname() == ("127.0.0.1", occupied_port)
            units_after = self._owned_units_snapshot("siq-agent-security-")
            # client-install 设计上丢弃子进程 stderr（通用错误面）；归属依据：
            # 非零退出 + 占用者仍存活 + 未新注册任何用户单位。
            self.check("lc03_port_occupied", "端口占用保留真实失败且不停止占用者",
                       rec["exit"] != 0 and still_listening
                       and units_before == units_after,
                       {"exit": rec["exit"], "stderr": err,
                        "occupier_alive": still_listening,
                        "units_before": units_before,
                        "units_after": units_after,
                        "note": "client-install 对子进程失败仅报 installation not confirmed（设计面）"})
        finally:
            blocker.close()

    # ---------- 汇总 ----------

    def write_evidence(self, env_extra: dict):
        os.makedirs(self.out_dir, mode=0o700, exist_ok=True)
        def w(name: str, obj):
            path = os.path.join(self.out_dir, name)
            with open(path, "w") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
            os.chmod(path, 0o600)
        w("checks.json", {"schema": "closure-b01-checks/v1",
                          "baseline": "personal-acceptance-baseline/v2",
                          "checks": self.checks,
                          "failures": self.failures,
                          "complete": not self.failures and all(c["ok"] is True for c in self.checks)})
        w("environment.json", env_extra)
        # 归档 CLI 日志（0600，已脱敏）。
        for name in sorted(os.listdir(self.log_dir)):
            src = os.path.join(self.log_dir, name)
            dst = os.path.join(self.evidence_logs, name)
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)

    def write_sums(self):
        lines = []
        for root, _dirs, files in os.walk(self.out_dir):
            for name in sorted(files):
                if name == "SHA256SUMS":
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, self.out_dir)
                lines.append(f"{sha256_file(full)}  ./{rel}")
        with open(os.path.join(self.out_dir, "SHA256SUMS"), "w") as f:
            f.write("\n".join(sorted(lines)) + "\n")

    def run(self) -> int:
        t0 = time.time()
        # 测试信任材料：一次性种子 + 固定测试公钥（仅注入测试构建）。
        self.test_trust = self.prepare_test_trust()
        # 构建两个可追溯版本。
        old = self.build_version(self.args.old_commit, "old")
        new = self.build_version(self.args.new_commit, "new")
        self.signer_binary = new["linux_arm64"]
        self.old_manifest = self.sign_manifest(old, "old")
        self.old_manifest_v2nocompat = self.sign_manifest(old, "old",
                                                          client_compatible=False)
        self.new_manifest = self.sign_manifest(new, "new")
        self.check("b01_artifacts", "独立 archive 双版本构建与签署",
                   True, {"old": {k: old[k] for k in ("commit", "tree", "version")},
                          "new": {k: new[k] for k in ("commit", "tree", "version")},
                          "trust_layer": {
                              "test_public_key_b64":
                                  self.test_trust["public_key_b64"],
                              "seed_location": "run_dir/release-seed.b64 (0600, 不入证据)",
                              "patched_files": [old["trust_patch"], new["trust_patch"]],
                              "note": "测试构建内嵌单一固定测试公钥（fail-closed pin）；"
                                      "生产信任根未触碰；正式发行 leg 保持 blocked，"
                                      "解锁条件=维护者以正式种子签署 manifest"},
                          "manifests": {"old": sha256_file(self.old_manifest),
                                        "old_v2nocompat": sha256_file(self.old_manifest_v2nocompat),
                                        "new": sha256_file(self.new_manifest)}})
        def guarded(cid: str, fn, *fn_args):
            try:
                return fn(*fn_args)
            except Exception as exc:  # noqa: BLE001 -- archive failure category and clean owned resources
                self.check(cid, f"{fn.__name__} 阶段异常", False,
                           {"error_type": type(exc).__name__})
                return None

        # LC01 在独立 scratch 状态目录。
        guarded("phase_lc01", self.lc01_install_precheck, old, new)
        # LC03 特殊路径/端口占用（占用者为本批自持监听）。
        guarded("phase_lc03", self.lc03_special_paths_ports, old)
        # 主实例：特殊路径状态目录 + 端口。
        rec = self.driver.install(self.old_manifest, old["linux_arm64"],
                                  port=self.args.port)
        self.check("lc01_install_ok", "通过 client-install 安装旧版并启动",
                   rec["exit"] == 0, {})
        if rec["exit"] == 0:
            self.driver.set_current_cli(old["linux_arm64"])
            identity = self.driver.identity()
            pubkey = self.driver.pubkey(identity["running_binary_path"])
            self.settle_installed_identity(identity)
            self.check("lc01_identity", "安装后身份面完整",
                       bool(identity["state_directory_id"]) and bool(pubkey)
                       and identity["version"] == old["version"],
                       {"identity": {k: identity[k] for k in
                                     ("port", "state_directory_id", "version",
                                      "unit_name", "main_pid", "fragment_path",
                                      "binary_digest")},
                        "signing_pubkey": pubkey})
            self.check("lc03_special_path", "中文/空格/% 状态路径实际运行"
                       "（ExecStart 运行路径归属到特殊路径状态目录）",
                       "中文" in identity["exec_start"]
                       and identity["running_binary_path"].startswith(
                           self.driver.state_dir)
                       and identity["active_state"] == "active",
                       {"state_dir": self.driver.state_dir,
                        "fragment_path": identity["fragment_path"],
                        "exec_start": identity["exec_start"]})
            guarded("phase_lc02", self.lc02_pairing,
                    identity["running_binary_path"])
            guarded("phase_lc04", self.lc04_background,
                    identity["running_binary_path"])
            # LC04 补充：重启后需重新配对再进入 LC06。
            self.driver.pair(self.installed_identity["running_binary_path"])
            tx, staged_old, _after = self.lc06_upgrade(
                old, new, self.installed_identity["running_binary_path"])
            # LC06 后新实例需重配对（重启失效旧会话）。
            self.driver.pair(self.installed_identity["running_binary_path"])
            guarded("phase_lc07", self.lc07_rollback_recover,
                    old, new, tx, staged_old)
            guarded("phase_lc08", self.lc08_unknown_objects, old, new)
            guarded("phase_lc09", self.lc09_teardown_reentry, old, new)
        # 收尾：teardown 本批实例（状态目录保留，服务与单位注销）。
        if getattr(self, "installed_identity", None):
            try:
                unit = self.installed_identity["unit_name"]
                self.driver.teardown(self.installed_identity["running_binary_path"])
                self.check("b01_final_teardown", "收尾 teardown 完成（单位注销）",
                           self.driver.load_state(unit) == "not-found",
                           {"unit": unit})
            except Exception as exc:  # noqa: BLE001 -- archive failure category and clean owned resources
                self.check("b01_final_teardown", "收尾 teardown 异常（登记）",
                           False, {"error_type": type(exc).__name__})
        env_extra = {
            "schema": "closure-b01-environment/v1",
            "trust_layer": {
                "mode": "test_release：一次性测试种子签署；测试公钥固定注入测试构建（fail-closed 单密钥 pin）",
                "test_public_key_b64": self.test_trust["public_key_b64"],
                "seed_location": "run_dir/release-seed.b64 (0600，不入证据)",
                "official_release_leg": "blocked；解锁条件=维护者以正式发布种子签署 manifest"},
            "old_commit": old["commit"], "old_tree": old["tree"],
            "new_commit": new["commit"], "new_tree": new["tree"],
            "versions": {"old": old["version"], "new": new["version"]},
            "builds": {"old": old["builds"], "new": new["builds"]},
            "state_dir": self.driver.state_dir,
            "port": self.args.port,
            "duration_s": round(time.time() - t0, 1),
        }
        self.write_evidence(env_extra)
        self.write_sums()
        # 失败也归档已完成（write_evidence 无条件执行）。
        print(f"done: {len(self.checks)} checks, {len(self.failures)} failures, "
              f"evidence={self.out_dir}")
        return 0 if not self.failures else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--old-commit", default="efad840")
    ap.add_argument("--new-commit", default="53155b1")
    ap.add_argument("--port", type=int, default=25173)
    ap.add_argument("--run-dir", default="/tmp/siq-closure-20260915/b01")
    ap.add_argument("--skip-pair-expiry", action="store_true", help="记录未执行，不关闭过期验收")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.umask(0o077)
    if os.path.lexists(args.run_dir) or os.path.lexists(args.out):
        raise SystemExit("run/evidence directory already exists; refusing to overwrite")
    os.makedirs(args.run_dir, mode=0o700)
    runner = Runner(args)
    try:
        return runner.run()
    except Exception as exc:  # noqa: BLE001 -- archive failure category and clean owned resources
        runner.check("batch_exception", "批次中断；保留已执行结果", False,
                     {"error_type": type(exc).__name__})
        # Use only the ownership-checked identity from this isolated driver.
        # A failed lookup is not permission to stop an arbitrary service.
        if getattr(runner, "installed_identity", None):
            try:
                identity = runner.driver.identity()
                runner.driver.teardown(identity["running_binary_path"])
                runner.check("exception_cleanup", "异常后注销本批单位",
                             runner.driver.load_state(identity["unit_name"]) == "not-found")
            except Exception as cleanup_exc:  # noqa: BLE001 -- archive failure category and clean owned resources
                runner.check("exception_cleanup", "异常清理未完成，需按归属记录处理", False,
                             {"error_type": type(cleanup_exc).__name__})
        runner.write_evidence({"status": "failed", "error_type": type(exc).__name__,
                               "trust_layer": "test_release"})
        runner.write_sums()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
