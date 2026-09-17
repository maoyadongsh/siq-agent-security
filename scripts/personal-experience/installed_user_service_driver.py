#!/usr/bin/env python3
"""installed_user_service 驱动（B02 最小可测试接口）。

只允许两条控制面：
  1. 产品 CLI（client-install / setup / service-* / teardown / pair / pubkey），
     全部经由 systemd --user 管理的真实用户单位运行；
  2. 对该实例 loopback 端点的 HTTP 观测（/healthz/instance 等）。

禁止（本驱动不会提供）：subprocess.Popen(<binary> serve) 直启冒充安装；
从 daemon 原文日志提取配对码并落盘（配对码只在内存中使用）。

identity() 返回并可由 verify_identity() 断言的字段：
  state_directory_id / signing_pubkey / binary_digest / port /
  unit_name / main_pid / fragment_path / exec_start / version
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any

PRODUCT = "siq-agent-security"
PAIR_CODE_RE = re.compile(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b")


class InstalledServiceError(RuntimeError):
    pass


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class InstalledUserServiceDriver:
    """驱动一个由 systemd --user 托管的 installed 实例。"""

    def __init__(self, state_dir: str, port: int, log_dir: str | None = None,
                 cli_timeout: int = 300):
        self.state_dir = os.path.abspath(state_dir)
        self.port = int(port)
        self.log_dir = log_dir
        self.cli_timeout = cli_timeout
        self._admin_token: str | None = None  # 仅内存
        self._pair_code: str | None = None  # 仅内存
        self.records: list[dict[str, Any]] = []
        self._log_seq = 0

    # ---------- CLI 执行与记录 ----------

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["SIQ_AGENT_SECURITY_STATE_DIR"] = self.state_dir
        return env

    def run_cli(self, binary: str, args: list[str], timeout: int | None = None,
                check: bool = True, redact: bool = True) -> dict[str, Any]:
        """运行产品 CLI；原文仅返回内存，0600 日志只写输出字节计数。"""
        cmd = [str(binary)] + [str(a) for a in args]
        started = time.time()
        try:
            proc = subprocess.run(
                cmd, env=self._env(), capture_output=True, text=True,
                timeout=timeout or self.cli_timeout,
             check=False)
        except subprocess.TimeoutExpired:
            raise InstalledServiceError("CLI timeout; output omitted") from None
        rec: dict[str, Any] = {
            "op": "cli",
            "command": args[0] if args and args[0] in {
                "init", "client-install", "setup", "service-start", "service-stop",
                "teardown", "service-prepare", "service-upgrade", "service-rollback",
                "pair", "pubkey", "manifest-verify", "version",
            } else "unknown",
            "exit": proc.returncode,
            "duration_s": round(time.time() - started, 3),
        }
        self._write_output_log(cmd, proc.stdout, proc.stderr, redact)
        rec["ok"] = proc.returncode == 0
        self.records.append(dict(rec))
        if check and proc.returncode != 0:
            raise InstalledServiceError(
                f"CLI failed: exit={proc.returncode} (output retained in memory only)")
        rec["ok"] = proc.returncode == 0
        rec["stdout"] = proc.stdout
        rec["stderr"] = proc.stderr
        return rec

    @staticmethod
    def _redact_arg(a: str) -> str:
        s = str(a)
        if PAIR_CODE_RE.fullmatch(s):
            return "<pair-code>"
        return s

    @staticmethod
    def _one_line(text: str) -> str:
        return "cli_output_omitted" if text else "no_cli_output"

    def _write_output_log(self, cmd: list[str], stdout: str, stderr: str,
                          redact: bool) -> None:
        # Even opt-out callers cannot persist CLI output or arguments: pair,
        # service errors and paths can contain credentials or private content.
        if not self.log_dir:
            return
        os.makedirs(self.log_dir, mode=0o700, exist_ok=True)
        if os.path.islink(self.log_dir):
            raise InstalledServiceError("diagnostic directory must not be a symlink")
        os.chmod(self.log_dir, 0o700)
        fd, _path = tempfile.mkstemp(prefix="cli-", suffix=".json", dir=self.log_dir)
        with os.fdopen(fd, "w") as f:
            json.dump({"kind": "cli_observation", "output_persisted": False,
                       "stdout_bytes": len((stdout or "").encode()),
                       "stderr_bytes": len((stderr or "").encode())}, f)

    # ---------- 生命周期（全部经产品入口） ----------

    def install(self, manifest: str, binary: str, port: int | None = None,
                check: bool = True) -> dict[str, Any]:
        args = ["client-install", "--manifest", manifest, "--binary", binary,
                "--confirm-install", "--runtime"]
        if port:
            args += ["--port", str(port)]
        return self.run_cli(binary, args, timeout=600, check=check)

    def setup(self, binary: str, port: int | None = None) -> dict[str, Any]:
        args = ["setup", "--confirm-setup", "--runtime"]
        if port:
            args += ["--port", str(port)]
        return self.run_cli(binary, args, timeout=600)

    def service_start(self, binary: str) -> dict[str, Any]:
        return self.run_cli(binary, ["service-start"])

    def service_stop(self, binary: str) -> dict[str, Any]:
        return self.run_cli(binary, ["service-stop", "--confirm-stop"])

    def service_start_refused(self, binary: str) -> dict[str, Any]:
        """service-stop 缺确认等拒绝路径：期望非零退出。"""
        return self.run_cli(binary, ["service-stop"], check=False)

    def teardown(self, binary: str) -> dict[str, Any]:
        return self.run_cli(binary, ["teardown", "--confirm-teardown"], timeout=600)

    def service_prepare(self, binary: str) -> dict[str, Any]:
        rec = self.run_cli(binary, ["service-prepare"])
        try:
            return json.loads(rec["stdout"])
        except json.JSONDecodeError as exc:
            raise InstalledServiceError(f"service-prepare 输出非 JSON: {exc}") from exc

    def upgrade(self, binary: str, manifest: str, new_binary: str,
                source_manifest: str | None = None,
                recover_id: str | None = None,
                check: bool = True) -> dict[str, Any]:
        args = ["service-upgrade", "--manifest", manifest, "--binary", new_binary,
                "--confirm-upgrade"]
        if source_manifest:
            args += ["--source-manifest", source_manifest]
        if recover_id:
            args += ["--recover", recover_id]
        return self.run_cli(binary, args, timeout=600, check=check)

    def rollback(self, binary: str, transaction: str, old_binary: str,
                 manifest: str | None = None, check: bool = True) -> dict[str, Any]:
        args = ["service-rollback", "--transaction", transaction,
                "--binary", old_binary, "--confirm-rollback"]
        if manifest:
            args += ["--manifest", manifest]
        return self.run_cli(binary, args, timeout=600, check=check)

    def pubkey(self, binary: str) -> str:
        rec = self.run_cli(binary, ["pubkey"])
        return rec["stdout"].strip()

    # ---------- systemd 观测 ----------

    def unit_properties(self, unit: str, props: list[str]) -> dict[str, str]:
        out = subprocess.run(
            ["systemctl", "--user", "show", unit] +
            [f"--property={p}" for p in props],
            capture_output=True, text=True, timeout=60, check=False)
        if out.returncode != 0:
            raise InstalledServiceError(
                f"systemctl show {unit} failed: {out.stderr.strip()}")
        result: dict[str, str] = {}
        for line in out.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                result[k] = v
        return result

    def load_state(self, unit: str) -> str:
        return self.unit_properties(unit, ["LoadState"]).get("LoadState", "")

    # ---------- HTTP 观测（loopback） ----------

    def instance_health(self, timeout: int = 10) -> dict[str, Any]:
        url = f"http://127.0.0.1:{self.port}/healthz/instance"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.URLError as exc:
            raise InstalledServiceError(f"instance health unreachable: {exc}") from exc
        if body.get("schema_version") != "local-service-instance-health/v1":
            raise InstalledServiceError(
                f"unexpected instance health schema: {body.get('schema_version')}")
        return body

    def api(self, method: str, path: str, token: str = "",
            payload: dict[str, Any] | None = None,
            timeout: int = 20) -> tuple[int, Any]:
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode() or "null")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                return exc.code, json.loads(raw or "null")
            except json.JSONDecodeError:
                return exc.code, {"raw": raw[:200]}

    def pairing_code(self, binary: str) -> str:
        """Issue a single-use code through the CLI; never persist its output."""
        rec = self.run_cli(binary, ["pair", "--port", str(self.port)])
        codes = PAIR_CODE_RE.findall(rec["stdout"] or "")
        if len(codes) != 1:
            raise InstalledServiceError("pair CLI did not return one valid code")
        self._pair_code = codes[0]
        return self._pair_code

    def pair(self, binary: str) -> str:
        """经产品 pair CLI 取码并立即在内存内换 admin 会话；码与 token 均不落盘。"""
        self.pairing_code(binary)
        status, body = self.api("POST", "/v1/pair", token="", payload={"code": self._pair_code})
        if status != 200:
            raise InstalledServiceError(f"/v1/pair rejected: status={status}")
        token = (body or {}).get("session")
        if not token:
            raise InstalledServiceError("/v1/pair 未返回会话")
        self._admin_token = token
        self.records.append({"op": "pair", "exit": 0, "note": "code/token in-memory only"})
        return token

    @property
    def admin_token(self) -> str | None:
        return self._admin_token

    def drop_admin(self) -> None:
        self._admin_token = None

    # ---------- 身份面 ----------

    def binary_digest_from_exec_start(self) -> tuple[str, str]:
        """从 systemd ExecStart 解析实际运行的二进制并取摘要。"""
        props = self.unit_properties(self.unit_name(), ["ExecStart"])
        exec_start = props.get("ExecStart", "")
        # systemd show 的 ExecStart 是对象串：
        # `{ path=/p/a th/binary ; argv[]=/p/a th/binary serve ; ... }`
        # 路径可含空格，须以 ` ;` 截断，不能按空白切分。
        match = re.search(r"path=(.*?)(?: ;|$)", exec_start)
        if not match or not match.group(1).strip():
            raise InstalledServiceError(f"无法从 ExecStart 解析二进制: {exec_start!r}")
        path = match.group(1).strip()
        return path, sha256_file(path)

    def unit_name(self) -> str:
        """只读取单位名：状态目录内已渲染的单位文件即唯一归属名。

        不经 service-prepare（它要获取 state 写锁，服务运行期会被拒）。
        """
        if getattr(self, "_unit_name_cache", None):
            return self._unit_name_cache
        import glob
        matches = sorted(glob.glob(
            os.path.join(self.state_dir, PRODUCT + "-*.service")))
        if len(matches) != 1:
            raise InstalledServiceError(
                "状态目录必须恰好有一个已渲染单位文件；归属不明确时拒绝选择")
        self._unit_name_cache = os.path.basename(matches[0])
        return self._unit_name_cache

    def _staged_binary_hint(self) -> str | None:
        return getattr(self, "_current_cli", None)

    def set_current_cli(self, binary: str) -> None:
        """记录当前应使用的 CLI 二进制（升级后应切换为 staged 新程序路径）。"""
        self._current_cli = str(binary)

    def identity(self) -> dict[str, Any]:
        health = self.instance_health()
        unit = self.unit_name()
        props = self.unit_properties(
            unit, ["MainPID", "FragmentPath", "ExecStart", "ActiveState"])
        staged_path, staged_digest = self.binary_digest_from_exec_start()
        return {
            "port": self.port,
            "state_directory_id": health.get("state_directory_id"),
            "version": health.get("version"),
            "unit_name": unit,
            "main_pid": props.get("MainPID"),
            "fragment_path": props.get("FragmentPath"),
            "exec_start": props.get("ExecStart"),
            "active_state": props.get("ActiveState"),
            "running_binary_path": staged_path,
            "binary_digest": staged_digest,
        }

    def verify_identity(self, expected: dict[str, Any]) -> dict[str, Any]:
        """逐项断言身份面；expected 中出现的键必须匹配。"""
        got = self.identity()
        mismatches: dict[str, Any] = {}
        for key, want in expected.items():
            have = got.get(key)
            if want is not None and have != want:
                mismatches[key] = {"want": want, "got": have}
        if mismatches:
            raise InstalledServiceError(f"identity mismatch: {json.dumps(mismatches)}")
        return got

    # ---------- 清理（ownership 复验后才允许调用方 teardown） ----------

    @staticmethod
    def cleanup_run_dir(path: str) -> None:
        """仅删除调用方确认归属的运行目录；不触碰任何运行中服务的状态。"""
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=False)
