#!/usr/bin/env python3
"""closure-b04: raw task content（密文清理）的真实墙钟到期腿，分 seed/verify 两段。

任务书 §7 B04：raw task content 的到期/清理契约必须用真实时间推进验证，
不能靠改内部状态或伪造时钟。本 runner 因此拆成两个子命令：

  seed    建立隔离的 direct-process daemon（Popen 二进制 serve，非 systemd；
          与 B02 的 installed 腿显式分开），完成 raw content 激活、三个任务
          腿的捕获（1h 最小保留 / 24h 保留 / 1h 保留+捕获后撤销授权），把
          重启重入所需的最小事实（状态目录、端口、record/grant ID、服务端
          返回的 ExpiresAt 原文、密钥指纹、二进制摘要、期望清理契约）写进
          seed JSON。管理员令牌绝不落盘（只记录如何重新配对），随后干净停机。
  verify  读 seed JSON，在同一状态目录、同一二进制上重启 daemon 并重新配对
          （令牌只在内存），等待真实时间越过最早 ExpiresAt，确认过期记录
          "metadata 已 expired 但密文文件仍在盘上"，再调用
          POST /v1/raw-task-content/purge-expired，断言：
            - 过期腿（task-exp-1、task-rev-1）的密文文件与 metadata 被删；
            - 存活腿（task-keep-1，24h 保留）密文完好且仍可解密读取；
            - 状态目录除 raw-task-content/ 外逐文件 sha256 不变（grant/
              revocation/收据链/activity/审计事实都不被清理波及）；
            - 导出基础检查成功/未知 ID/未认证；完整隔离另见 export runner。

安全声明：不打印、不落盘管理员令牌、配对码、捕获明文或密钥材料；只记录
ID、哈希、时间戳与计数。

任务身份映射说明（产品契约）：raw content 的 task_id 不是任意字符串——
capture-permit/capture 都要求 request.TaskID == 绑定的 TaskID，而绑定
TaskID 由 runtimeidentity.sessionNames 确定性派生（"task-ri-" +
hash(identity_id, session_id)）。因此三条腿用 session_id 命名为
task-exp-1 / task-keep-1 / task-rev-1，并把派生出的真实 task-ri-… ID
记入 seed JSON；seed/verify 的"任务名"均指该腿标签。

authority 说明：raw content 激活（POST /v1/raw-task-content/activation）
由 daemon 自有签名密钥在服务端签名（internal/rawcontent/activation.go），
不需要外部 release manifest / authority 输入，故本 runner 不接受
--manifest/--authority。

用法：
  python3 closure-b04-expiry-seed-runner.py seed \
      --binary <预构建 siq-agent-security> --run-dir <空目录> \
      --port <端口> --out <seed.json>
  # 真实等待 >= 1h（过期腿的最小保留期）之后：
  python3 closure-b04-expiry-seed-runner.py verify \
      --binary <同一二进制> --seed <seed.json> --out <verify.json>
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
WORKTREE = HERE.parents[1]


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# 复用既有 harness 链（与 closure-b02 同机制）：managed harness 提供 openclaw
# HOME 隔离 + 实例发现 + 审批/发放运行时身份的最小链路；fixture 基类提供
# api()/command()/stop() 与 require。
FIXTURE = _load("b04_fixture", WORKTREE / "scripts/validate-intent-v2-hermes.py")
MANAGED = _load("b04_managed", HERE / "openclaw-managed-native-smoke.py")


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


AGENT = FIXTURE.AGENT
PLATFORM = "openclaw"

# rawcontent 常量（internal/rawcontent/store.go / authority.go / permit.go）。
MIN_RETENTION_SECONDS = 3600            # MinRetention = 1h
MAX_GRANT_DURATION_SECONDS = 86400      # MaxGrantDuration = 24h
ACTIVATION_RETENTION_SECONDS = 86400    # 必须 >= 存活腿的 24h 保留（grant
                                        # retention 上限是激活 retention）
ACTIVATION_BUDGET_BYTES = 64 << 20
GRANT_MAX_PLAINTEXT_BYTES = 65536
PERMIT_TTL_SECONDS = 60                 # [MinPermitDuration=10s, Max=5min]

# serve 生命周期对过期 raw content 的自动清理：启动时一次 +
# time.NewTicker(15 * time.Minute)（cmd/agentshield/main.go、
# serve_lifecycle.go）。verify 的在线等待窗口必须压在这个 tick 之下，才能
# 无竞态地观察 "expired 但密文仍在盘上"。
PURGE_TICK_GUARD_SECONDS = 13 * 60

# 三条腿：session_id 即任务标签；retention/duration 单位秒；kind 是捕获种类。
LEGS = (
    {"name": "task-exp-1", "retention_seconds": 3600, "duration_seconds": 3600,
     "kind": "parameters", "expect": "purged"},
    {"name": "task-keep-1", "retention_seconds": 86400, "duration_seconds": 86400,
     "kind": "output", "expect": "survives"},
    {"name": "task-rev-1", "retention_seconds": 3600, "duration_seconds": 3600,
     "kind": "parameters", "expect": "purged_after_revocation"},
)
KEEP_LEG = "task-keep-1"

_RFC3339 = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")


def now_text() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_rfc3339(value: str) -> _dt.datetime:
    """解析 Go RFC3339Nano（任意小数位 + Z）。"""
    found = _RFC3339.match(value)
    require(bool(found), f"unexpected timestamp format: {value[:40]!r}")
    base, frac, zone = found.groups()
    micro = ((frac or "") + "000000")[:6]
    return _dt.datetime.fromisoformat(f"{base}.{micro}+00:00" if zone == "Z" else f"{base}.{micro}{zone}")


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_digest_snapshot(state_dir: pathlib.Path) -> dict:
    """状态目录逐文件 sha256 快照（相对路径 -> 摘要），用于清理作用域断言。"""
    out = {}
    for path in sorted(state_dir.rglob("*")):
        if path.is_file():
            out[path.relative_to(state_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def scope_changes(before: dict, after: dict) -> tuple:
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    modified = sorted(key for key in set(before) & set(after) if before[key] != after[key])
    return removed, added, modified


def append_only_snapshot(state_dir: pathlib.Path) -> dict[str, bytes]:
    """Hold local bytes so an allowlisted audit change can be checked as append.

    The bytes stay in this process and never enter a public report. Hashes alone
    cannot distinguish an append from rewriting an older signed receipt line.
    """
    return {
        path.relative_to(state_dir).as_posix(): path.read_bytes()
        for path in state_dir.rglob("*")
        if path.is_file() and is_append_only(path.relative_to(state_dir).as_posix())
    }


# 清理作用域白名单：purge 请求本身可能合法追加的 append-only 审计面。
# audit.jsonl 由 state/ledgerstore.go AppendAudit 以 O_APPEND 写入；
# receipts/<chainID>/<day>.jsonl 与 HEAD 由 internal/receipt/chain.go 以
# O_APPEND 追加；commit-audit/ 同属审计链输出。这些路径的"新增/纯追加"
# 不算越界；任何删除、非追加改写，或白名单之外的任何变化都算越界。
APPEND_ONLY_PATHS = ("audit.jsonl",)
APPEND_ONLY_DIRS = ("receipts/", "commit-audit/")


def is_append_only(path: str) -> bool:
    return path in APPEND_ONLY_PATHS or path.startswith(APPEND_ONLY_DIRS)


def out_of_scope_changes(removed, added, modified, before_append: dict, after_append: dict) -> list:
    """清理契约：只允许删 raw-task-content/ 下的信封文件。

    - 删除：仅 raw-task-content/ 下的信封合法；append-only 审计面
      （audit.jsonl、receipts/**、commit-audit/**）不在其下，因此任何对
      审计链的删除都会被判越界（审计链绝不允许缩短）；
    - 新增/变化：仅 append-only 审计面放行，且既有文件必须逐字节保留
      原前缀；仅靠 sha256 无法区分追加与篡改旧字节。
    - raw-task-content/ 之外任何新增/改写一律越界。
    - serve.lock 是 serve 启动自身创建/持有的运行期锁文件（cmd/agentshield
      serve 启动路径），不是清理效果；启动前后快照里它必然表现为新增，按
      已知运行期工件放行（仅新增方向；其删除仍然越界）。
    """
    bad_removed = [p for p in removed if not p.startswith("raw-task-content/")]
    bad_modified = [p for p in modified if not is_append_only(p) or
                    p not in before_append or p not in after_append or
                    not after_append[p].startswith(before_append[p])]
    bad_added = [p for p in added if not is_append_only(p) and p != "serve.lock"]
    return sorted(bad_removed + bad_modified + bad_added)


class B04Harness(MANAGED.Harness):
    """b04 专用 harness：完全自定义初始化以支持 verify 的同状态目录重入。

    fixture.Harness.__init__ 的 mkdir 不容忍已存在目录，verify 必须在 seed
    的同一 root 上重建同一隔离面（HOME 隔离 + openclaw 环境 + 状态目录），
    因此这里不调用父类 __init__，仅复用其 api()/command()/stop()。
    """

    platform = PLATFORM
    read_tool = "read"
    write_tool = "write"

    def __init__(self, root, args, *, resume: bool = False):
        self.root = pathlib.Path(root)
        self.args = args
        self.resume = resume
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700, exist_ok=True)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(exist_ok=True)
        (self.workspace / "company-a").mkdir(exist_ok=True)
        (self.workspace / "company-a" / "report.txt").write_text("fixture-visible-company-a\n")
        self.binary = self.root / "siq-agent-security"
        self.proc = None
        self.log = None
        self.admin = ""
        self.port = int(args.port) if getattr(args, "port", None) else None
        self.endpoint = ""
        self.runtime_credential = ""
        self.runtime_identity_id = ""
        self.instance_id = ""
        self.agent = ""
        # 隔离 HOME（managed harness 约定）：daemon 的实例发现只指向 fixture
        # 的 ~/.openclaw，绝不触碰日常 profile。
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700, exist_ok=True)
        self.oc = self.home / ".openclaw"
        self.oc.mkdir(exist_ok=True)
        env_keys = ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "TMPDIR")
        self.env = {key: value for key, value in os.environ.items() if key in env_keys}
        self.env.update({
            "HOME": str(self.home),
            "OPENCLAW_STATE_DIR": str(self.oc),
            "OPENCLAW_CONFIG_PATH": str(self.oc / "openclaw.json"),
            "SIQ_AGENT_SECURITY_STATE_DIR": str(self.state),
            "SIQ_AGENT_SECURITY_AGENT_ID": AGENT,
            "SIQ_AGENT_SECURITY_MODE": "block",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.config("required")

    def config(self, enforcement):
        # 端口写进 config.json：state.Initialize 对既有状态拒绝换端口
        # （见 closure-b02 InstalledHarness.config 的同一注释），verify 重入
        # 时 serve --port 必须与 seed 的端口一致。
        body = {"intent_enforcement": enforcement, "enforcement_mode": "block"}
        if self.port:
            body["port"] = self.port
        (self.state / "config.json").write_text(json.dumps(body))

    def start(self, port=None):
        """direct-process 启动：Popen 二进制 serve，读启动日志里的单次配对码。"""
        if port is not None:
            self.port = int(port)
        if self.port is None:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                self.port = sock.getsockname()[1]
        self.config("required")
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self.env["SIQ_AGENT_SECURITY_ENDPOINT"] = self.endpoint
        self.log = tempfile.TemporaryFile(mode="w+t")  # noqa: SIM115 -- stop() 关闭
        self.proc = subprocess.Popen(
            [str(self.binary), "serve", "--port", str(self.port), "--mode", "block"],
            cwd=self.workspace, env=self.env, stdout=self.log, stderr=self.log,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            require(self.proc.poll() is None, "daemon exited before readiness")
            self.log.seek(0)
            found = re.search(r"admin pairing code \(single use, 5 min\): (\S+)", self.log.read())
            if found:
                try:
                    pair = self.api("/v1/pair", {"code": found[1]}, token="")
                    self.admin = pair["session"]  # 仅内存；绝不写入证据
                    return
                except urllib.error.URLError:
                    pass
            time.sleep(0.05)
        raise RuntimeError("daemon readiness timeout")

    # ---- 运行时身份链（managed setup_authority 的最小子集，不做 adapter 安装） ----

    def issue_runtime(self):
        """实例发现 → admit → grant(审批) → deploy → 运行时身份 + 凭据。

        发放先于任何 adapter install（managed harness 同序），因此无需安装
        openclaw 插件即可 enroll/捕获：enroll 与 capture 只认证运行时凭据并
        解析绑定。
        """
        catalog = self.api("/v1/adapter/instances?platform=" + PLATFORM)
        target = next(row for row in catalog["instances"] if row["active"])
        self.instance_id = target["instance_id"]
        self.agent = "hri-" + self.instance_id[3:]
        skill = self.root / "fixture-skill"
        skill.mkdir(exist_ok=True)
        (skill / "SKILL.md").write_text(
            "---\nname: intent-fixture\ndescription: Read a synthetic report.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\nRead the fixture report.\n"
        )
        adm = self.api("/v1/admit", {"path": str(skill)})["admission"]
        require(adm["verdict"] != "quarantine", "benign fixture quarantined")
        result = self.api(
            "/v1/grants",
            {
                "admission_id": adm["admission_id"],
                "platform": PLATFORM,
                "subject_id": self.agent,
                "subject_type": "agent_instance",
                "redact_secrets": True,
            },
        )
        grant_path = "/v1/grants/" + result["grant"]["grant_id"]

        def action(name, **body):
            nonlocal result
            result = self.api(
                grant_path + "/" + name,
                {"expected_revision": result["state_revision"], "actor_id": "automated-fixture-operator", **body},
            )
            return result

        action(
            "patch-desired",
            tools=[self.read_tool, self.write_tool],
            filesystem={"read_only": [str(self.workspace)], "read_write": []},
        )
        for index, overlap in enumerate(result["grant"]["overlap_conflicts"]):
            if overlap["resolution"] == "unresolved":
                action("resolve-overlap", index=index)
        challenge = action("challenge")["challenge"]
        action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        require(result["grant"]["status"] == "approved", "grant approval did not transition")
        action("deploy")
        issued = self.api(
            "/v1/runtime-identities",
            {
                "schema_version": "local-runtime-identity-create/v1",
                "instance_id": self.instance_id,
                "grant_id": result["grant"]["grant_id"],
                "expected_grant_revision": result["state_revision"],
                "actor_id": "automated-fixture-operator",
                "session_ttl_seconds": 28800,
            },
            expected=201,
        )
        self.runtime_identity_id = issued["identity"]["identity_id"]
        credential_path = pathlib.Path(issued["credential_path"])
        require(credential_path.is_file(), "runtime credential file missing")
        self.runtime_credential = credential_path.read_text().strip()
        require(bool(self.runtime_credential), "runtime credential empty")
        return issued

    def enroll(self, session_id: str) -> dict:
        """enroll 一个原生会话并返回其绑定（含派生的 task-ri-… task_id）。"""
        self.api(
            "/v1/runtime-sessions",
            {"schema_version": "local-runtime-session-enroll/v1", "session_id": session_id},
            token=self.runtime_credential, expected=200,
        )
        bindings = self.api("/v1/intent-bindings")["items"]
        own = [row for row in bindings if row.get("session_id") == session_id]
        require(len(own) == 1, f"expected exactly one binding for session {session_id}: {len(own)}")
        require(bool(own[0].get("task_id")), "binding missing task_id")
        return own[0]

    def decide(self, session_id: str, call_id: str) -> dict:
        """用运行时凭据做一次工具决策，产生收据 → task activity（导出证据）。"""
        return self.api(
            "/v1/decide",
            {
                "platform": PLATFORM,
                "agent_id": self.agent,
                "session_id": session_id,
                "tool": self.read_tool,
                "tool_call_id": call_id,
                "params": {"path": str(self.workspace / "company-a/report.txt")},
            },
            token=self.runtime_credential,
        )

    # ---- raw task content 面 ----

    def raw_status(self) -> dict:
        return self.api("/v1/raw-task-content/status")

    def activate(self, retention_seconds: int, budget_bytes: int) -> dict:
        return self.api(
            "/v1/raw-task-content/activation",
            {
                "schema_version": "local-raw-task-content-activate/v1",
                "actor_id": "automated-fixture-operator",
                "retention_seconds": retention_seconds,
                "budget_bytes": budget_bytes,
            },
            expected=201,
        )

    def create_grant(self, task_id: str, duration_seconds: int, retention_seconds: int) -> dict:
        return self.api(
            "/v1/raw-task-content/grants",
            {
                "schema_version": "local-raw-task-content-grant-create/v1",
                "task_id": task_id,
                "kinds": ["parameters", "output"],
                "actor_id": "automated-fixture-operator",
                "duration_seconds": duration_seconds,
                "retention_seconds": retention_seconds,
                "max_plaintext_bytes": GRANT_MAX_PLAINTEXT_BYTES,
            },
            expected=201,
        )

    def revoke_grant(self, grant_id: str, expected_signature: str) -> dict:
        return self.api(
            "/v1/raw-task-content/grants/" + grant_id + "/revoke",
            {
                "schema_version": "local-raw-task-content-revoke/v1",
                "expected_grant_signature": expected_signature,
                "actor_id": "automated-fixture-operator",
            },
        )

    def request_permit(self, session_id: str, task_id: str, grant: dict, kind: str):
        return self.api(
            "/v1/raw-task-content/capture-permits",
            {
                "schema_version": "local-raw-task-content-capture-permit-create/v1",
                "platform": PLATFORM,
                "agent_id": self.agent,
                "session_id": session_id,
                "task_id": task_id,
                "grant_id": grant["grant_id"],
                "expected_grant_signature": grant["signature"],
                "kind": kind,
                "ttl_seconds": PERMIT_TTL_SECONDS,
            },
            token=self.runtime_credential, expected=201,
        )

    def capture(self, session_id: str, task_id: str, permit: dict, kind: str, label: str) -> dict:
        # permit 对象必须原样回传（13 个字段全等，见 rawTaskContentCaptureRequest）。
        return self.api(
            "/v1/raw-task-content/captures",
            {
                "schema_version": "local-raw-task-content-capture/v1",
                "platform": PLATFORM,
                "agent_id": self.agent,
                "session_id": session_id,
                "task_id": task_id,
                "permit": permit,
                "fields": [
                    {"path": f"/fixture/{label}/payload",
                     "value": f"b04-expiry-fixture-payload-for-{label}",
                     "secret": False},
                ],
            },
            token=self.runtime_credential, expected=201,
        )

    def search_records(self, task_id: str) -> list:
        return self.api(
            "/v1/raw-task-content/records/search",
            {"schema_version": "local-raw-task-content-record-list/v1", "task_id": task_id},
        )["items"]

    def read_record(self, record_id: str, task_id: str):
        return self.api(
            f"/v1/raw-task-content/records/{record_id}/read",
            {"schema_version": "local-raw-task-content-record-read/v1", "task_id": task_id},
        )

    def purge_expired(self) -> dict:
        return self.api(
            "/v1/raw-task-content/purge-expired",
            {"schema_version": "local-raw-task-content-purge-expired/v1", "confirm_expired_only": True},
        )

    def ciphertext_files(self) -> list:
        return sorted((self.state / "raw-task-content").glob("*.json"))

    def probe(self, path, *, token=None, method="GET", body=None):
        """不使用 require 的原始请求，返回 (status, payload) 供负向断言使用。"""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.endpoint + path, headers=headers, data=data, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            try:
                payload = json.loads(raw) if raw else {}
            except ValueError:
                payload = {"_raw": raw[:200].decode("utf-8", "replace")}
            return response.status, payload


class B04Runner:
    def __init__(self, args):
        self.args = args
        self.checks = []

    def log(self, message: str):
        print(f"[b04] {message}", flush=True)

    def check(self, check_id: str, ok: bool, detail):
        self.checks.append({"id": check_id, "ok": bool(ok), "detail": detail})
        self.log(f"check {check_id}: {'ok' if ok else 'FAIL'} ({detail})")
        return bool(ok)

    def write_json(self, payload: dict):
        out = pathlib.Path(self.args.out)
        out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # Private evidence must never be briefly world-readable, nor silently
        # overwrite a prior attempt with the same output path.
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return out

    # ---------------- seed ----------------

    def run_seed(self):
        # The daemon runs with cwd=self.workspace; keep its executable and
        # state paths absolute even when the caller supplied a relative run-dir.
        root = pathlib.Path(self.args.run_dir).resolve(strict=False)
        require(not root.exists(), f"run-dir must not pre-exist: {root}")
        root.mkdir(mode=0o700)
        binary_path = pathlib.Path(self.args.binary).resolve(strict=True)
        binary_digest = sha256_file(binary_path)

        harness = B04Harness(root, self.args)
        shutil.copy2(binary_path, harness.binary)
        harness.binary.chmod(0o700)
        require(sha256_file(harness.binary) == binary_digest, "binary copy digest mismatch")

        seed = {
            "schema_version": "b04-expiry-seed/v1",
            "created_at": now_text(),
            "binary": {"path": str(binary_path), "sha256": binary_digest},
            "run_dir": str(root),
            "root": str(root),
            "state_dir": "",
            "port": None,
            "admin_token": "NOT SAVED (single-use pairing code at serve startup; re-pair on restart)",
            "re_pair": {
                "method": "POST /v1/pair {\"code\": <code>}",
                "credential_source": ("single-use admin pairing code printed by "
                                      "`siq-agent-security serve` at startup: "
                                      "'admin pairing code (single use, 5 min): <code>'"),
                "admin_token_saved": False,
            },
            "activation": {},
            "legs": [],
            "ciphertext_files_before_wait": [],
            "expected_purge": {},
            "notes": [],
        }
        try:
            harness.start(port=self.args.port)
            seed["state_dir"] = str(harness.state)
            seed["port"] = harness.port
            self.log(f"daemon up on 127.0.0.1:{harness.port} (state={harness.state})")

            # 激活前：raw content 默认关闭。
            status = harness.raw_status()
            self.check("seed_raw_content_default_disabled",
                       status.get("status") == "disabled" and status.get("default_capture") is False,
                       f"status={status.get('status')} default_capture={status.get('default_capture')}")

            # 运行时身份链（三个会话共用同一 identity/grant，派生三个 task_id）。
            harness.issue_runtime()
            self.log(f"runtime identity issued: {harness.runtime_identity_id[:16]}…")

            # 激活：retention 上限取 24h 以允许存活腿；激活由 daemon 自有密钥签名。
            activation = harness.activate(ACTIVATION_RETENTION_SECONDS, ACTIVATION_BUDGET_BYTES)
            seed["activation"] = {
                "retention_seconds": activation["retention_seconds"],
                "budget_bytes": activation["budget_bytes"],
                "key_fingerprint": activation.get("key_fingerprint", ""),
                "activated_at": activation.get("activated_at", ""),
            }
            self.check("seed_activation_ready", harness.raw_status().get("status") == "ready",
                       f"retention={activation['retention_seconds']}s budget={activation['budget_bytes']}")

            grants_by_leg = {}  # 仅内存：完整 grant signature 不落盘
            for leg in LEGS:
                binding = harness.enroll(leg["name"])
                task_id = binding["task_id"]
                grant = harness.create_grant(task_id, leg["duration_seconds"], leg["retention_seconds"])
                grants_by_leg[leg["name"]] = grant
                permit = harness.request_permit(leg["name"], task_id, grant, leg["kind"])
                capture = harness.capture(leg["name"], task_id, permit, leg["kind"], leg["name"])
                records = harness.search_records(task_id)
                require(len(records) == 1, f"{leg['name']}: expected 1 record, got {len(records)}")
                record = records[0]
                require(record["record_id"] == capture["record_id"],
                        f"{leg['name']}: record id mismatch between capture and metadata")
                require(record["expires_at"] == capture["expires_at"],
                        f"{leg['name']}: expires_at mismatch between capture and metadata")
                require(record["status"] == "active", f"{leg['name']}: fresh record must be active")
                seed["legs"].append({
                    "name": leg["name"],
                    "session_id": leg["name"],
                    "task_id": task_id,
                    "kind": leg["kind"],
                    "expect": leg["expect"],
                    "grant_id": grant["grant_id"],
                    "grant_signature_sha256": hashlib.sha256(grant["signature"].encode()).hexdigest(),
                    "record_id": record["record_id"],
                    "created_at": record["created_at"],
                    "expires_at": record["expires_at"],  # 服务端返回原文，逐字记录
                    "plaintext_sha256": capture["plaintext_sha256"],
                    "plaintext_bytes": capture["plaintext_bytes"],
                    "omitted_secret_count": capture["omitted_secret_count"],
                })
                self.log(f"leg {leg['name']}: task={task_id[:16]}… record={record['record_id']} "
                         f"expires={record['expires_at']}")
            self.check("seed_three_legs_captured",
                       len(seed["legs"]) == 3 and all(row["record_id"] for row in seed["legs"]),
                       f"legs={len(seed['legs'])}")

            # 撤销腿：捕获成功后立刻撤销授权；随后用同一（仍正确签名的）授权
            # 再请求 permit 必须被拒——capture 已停止，密文按契约保留到到期。
            revoked = next(row for row in seed["legs"] if row["name"] == "task-rev-1")
            revoked_grant = grants_by_leg["task-rev-1"]
            revocation = harness.revoke_grant(revoked["grant_id"], revoked_grant["signature"])
            seed["revocation"] = {
                "leg": "task-rev-1",
                "grant_id": revoked["grant_id"],
                "revoked_at": now_text(),
                "revocation_response_keys": sorted(revocation.keys()),
                # 撤销不删密文（internal/rawcontent：revoke 只记 revocation 记录）。
                "ciphertext_retained_until_expiry": True,
            }
            self.check("seed_revocation_recorded", bool(revocation),
                       f"grant={revoked['grant_id']} response_keys={len(revocation)}")
            status_code, payload = harness.probe(
                "/v1/raw-task-content/capture-permits", token=harness.runtime_credential, method="POST",
                body={
                    "schema_version": "local-raw-task-content-capture-permit-create/v1",
                    "platform": PLATFORM,
                    "agent_id": harness.agent,
                    "session_id": revoked["session_id"],
                    "task_id": revoked["task_id"],
                    "grant_id": revoked["grant_id"],
                    "expected_grant_signature": revoked_grant["signature"],
                    "kind": revoked["kind"],
                    "ttl_seconds": PERMIT_TTL_SECONDS,
                },
            )
            self.check("seed_capture_stopped_after_revoke",
                       status_code == 409 and payload.get("reason_code") == "raw_task_content_authority_revoked",
                       f"permit-after-revoke HTTP {status_code} {payload.get('reason_code')}")

            # 决策证据：每个会话一次 decide，产出收据 → task activity（verify 导出用）。
            decided = []
            for leg in LEGS:
                outcome = harness.decide(leg["name"], f"b04-{leg['name']}")
                decided.append({"session_id": leg["name"], "action": outcome.get("action"),
                                "reason_code": outcome.get("reason_code")})
            seed["decision_evidence"] = decided

            files = harness.ciphertext_files()
            seed["ciphertext_files_before_wait"] = [p.name for p in files]
            expected_files = {row["record_id"] + ".json" for row in seed["legs"]}
            self.check("seed_ciphertext_on_disk", {p.name for p in files} == expected_files,
                       f"files={len(files)} expected={len(expected_files)}")

            seed["expected_purge"] = {
                "contract": ("PurgeExpired deletes only envelopes whose expires_at <= now "
                             "(internal/rawcontent/store.go); grant/revocation records under "
                             "raw-task-content-authority/, the receipt chain, task activities and "
                             "audit facts must survive; the 24h leg must survive."),
                "expired_legs": [row["name"] for row in seed["legs"] if row["expect"] != "survives"],
                "surviving_legs": [row["name"] for row in seed["legs"] if row["expect"] == "survives"],
                "expected_deleted_records": sum(1 for row in seed["legs"] if row["expect"] != "survives"),
                # The purge API reports deleted encrypted JSON file sizes,
                # which cannot equal plaintext bytes. Keep the seeded number
                # as a plaintext bound and observe actual disk bytes at purge.
                "expected_expired_plaintext_bytes": sum(
                    row["plaintext_bytes"] for row in seed["legs"]
                    if row["expect"] != "survives"),
                "released_bytes_basis": "deleted encrypted envelope JSON file sizes",
            }
            seed["notes"].append("task_id is derived by the product (task-ri-<hash(identity,session)>); "
                                 "leg names are the session_id labels")
        finally:
            harness.stop()
            if harness.binary.exists():
                harness.binary.chmod(0o600)
            self.log("seed daemon stopped")

        out = self.write_json(seed)
        self.log(f"seed evidence written: {out}")
        return seed

    # ---------------- verify ----------------

    def run_verify(self):
        seed_path = pathlib.Path(self.args.seed)
        seed = json.loads(seed_path.read_text())
        require(seed.get("schema_version") == "b04-expiry-seed/v1",
                f"unexpected seed schema: {seed.get('schema_version')}")
        self.seed = seed
        root = pathlib.Path(seed["root"])
        require(root.is_dir(), f"seed root missing: {root}")
        state_dir = pathlib.Path(seed["state_dir"])
        require(state_dir.is_dir(), f"seed state dir missing: {state_dir}")
        content_dir = state_dir / "raw-task-content"
        keep = next(row for row in seed["legs"] if row["name"] == KEEP_LEG)
        expired_legs = [row for row in seed["legs"] if row["expect"] != "survives"]
        binary_digest = sha256_file(pathlib.Path(self.args.binary))

        harness = None
        evidence = {}
        try:
            self.check("verify_binary_matches_seed", binary_digest == seed["binary"]["sha256"],
                       f"sha256={binary_digest[:16]}…")

            # ---- 阶段 1（daemon 未启动，无竞态）：seed 停机后没有任何进程会删
            # 信封，因此过期腿的密文此刻必须仍在盘上，且信封里的 expires_at 与
            # seed 记录逐字一致（信封只含密文与元数据，无明文/密钥材料）。
            on_disk = {}
            for row in seed["legs"]:
                path = content_dir / (row["record_id"] + ".json")
                envelope = json.loads(path.read_text()) if path.is_file() else {}
                on_disk[row["name"]] = envelope.get("expires_at", "")
            self.check("verify_ciphertext_retained_while_daemon_down",
                       all(on_disk[row["name"]] == row["expires_at"] for row in seed["legs"]),
                       "; ".join(f"{name}:expires_at={value or 'FILE MISSING'}"
                                 for name, value in sorted(on_disk.items())))

            # ---- 阶段 2：真实墙钟等待。serve 启动即执行一次
            # PurgeExpiredRawContent 且每 15 分钟 tick 一次
            # （cmd/agentshield/main.go + serve_lifecycle.go），所以等待拆成
            # 两段：大部分时间 daemon 停机（不可能被清理），最后不超过
            # PURGE_TICK_GUARD_SECONDS 的时间 daemon 在线——这样到期后的
            # "expired 但文件仍在" 观察落在第一个 lifecycle tick 之前，无竞态。
            earliest = min(parse_rfc3339(row["expires_at"]) for row in expired_legs)
            remaining = (earliest - _dt.datetime.now(_dt.timezone.utc)).total_seconds()
            elapsed_ok = remaining <= 0
            expired_online = False
            if not elapsed_ok and not self.args.skip_wait:
                down = max(0.0, remaining - PURGE_TICK_GUARD_SECONDS)
                self.sleep_bounded(down, "daemon-down wait toward expiry")
                remaining -= down
                # daemon 将在到期之前启动；到期在阶段 4 的在线等待中用真实
                # 墙钟跨过，因此"expired 但密文仍在盘上"可以（且必须）在线
                # 观察。（本批修复：旧逻辑 expired_online=down<=0 且把
                # verify_expiry_elapsed 判定提前到在线等待之前，使新鲜
                # seed→verify 链路必然 FAIL、expect_visible 退化为宽松分支；
                # 现改为在线等待真实跨过到期后判定——收紧而非放宽。）
                expired_online = True

            # ---- 阶段 3：启动 daemon（同一状态目录、同一二进制、重新配对）。
            pre_start_snapshot = state_digest_snapshot(state_dir)
            pre_start_append = append_only_snapshot(state_dir)
            harness = B04Harness(root, self.args, resume=True)
            shutil.copy2(self.args.binary, harness.binary)
            harness.binary.chmod(0o700)
            require(sha256_file(harness.binary) == binary_digest, "binary copy digest mismatch")
            harness.start(port=seed["port"])
            self.log(f"daemon re-paired on 127.0.0.1:{harness.port} (same state dir)")
            self.check("verify_state_dir_reused",
                       str(harness.state) == seed["state_dir"] and harness.port == seed["port"],
                       f"state={harness.state} port={harness.port}")

            # serve 启动本身会跑一次 lifecycle 清理：若 verify 启动时已过期，
            # 这里就该看到过期信封被删（且只删 raw-task-content/ 下的文件）。
            post_start_snapshot = state_digest_snapshot(harness.state)
            post_start_append = append_only_snapshot(harness.state)
            s_removed, s_added, s_modified = scope_changes(pre_start_snapshot, post_start_snapshot)
            self.check("verify_startup_purge_scope",
                       not out_of_scope_changes(s_removed, s_added, s_modified,
                                                pre_start_append, post_start_append),
                       f"removed={s_removed} added={s_added} modified={s_modified}")

            status = harness.raw_status()
            activation = seed["activation"]
            self.check("verify_activation_persists",
                       status.get("status") == "ready"
                       and status.get("retention_seconds") == activation["retention_seconds"]
                       and status.get("budget_bytes") == activation["budget_bytes"],
                       f"status={status.get('status')} retention={status.get('retention_seconds')}")

            # ---- 阶段 4：到期观察 + 手动清理。
            if not elapsed_ok and not self.args.skip_wait:
                self.sleep_bounded(remaining + 1.0, "real wall-clock expiry (daemon up)")
            # verify_expiry_elapsed 在真实墙钟跨过到期时刻之后判定：
            # 新鲜链路（真实等待后）与已到期 seed 重放都必须为真；
            # 仅 --skip-wait 且未到期时按约定记 FAIL。
            self.check("verify_expiry_elapsed",
                       _dt.datetime.now(_dt.timezone.utc) >= earliest,
                       f"earliest_expires_at={earliest.isoformat()} "
                       f"skip_wait={self.args.skip_wait} "
                       f"checked_at={_dt.datetime.now(_dt.timezone.utc).isoformat()}")
            self.observe_expired_before_purge(harness, content_dir, expired_legs, keep,
                                              expect_visible=expired_online)

            kept = harness.read_record(keep["record_id"], keep["task_id"])
            self.check("verify_survivor_readable_before_purge",
                       kept["record"]["plaintext_sha256"] == keep["plaintext_sha256"]
                       and kept["record"]["status"] == "active",
                       f"record={keep['record_id']} sha_match="
                       f"{kept['record']['plaintext_sha256'] == keep['plaintext_sha256']}")

            grants_before = harness.api("/v1/raw-task-content/grants")["items"]
            grant_ids_before = {row.get("grant_id") for row in grants_before}
            receipts_before = len(harness.api("/v1/receipts")["receipts"])
            activities_count_before = len(harness.api("/v1/task-activities")["items"])
            snapshot_before = state_digest_snapshot(harness.state)
            append_before = append_only_snapshot(harness.state)

            # 期望清理数取"调用前盘上仍存在的过期信封数"：若 verify 是在过期后
            # 才启动的，startup lifecycle purge 已把它们删掉，手动 purge 应为
            # 幂等空操作（deleted_records=0）；若等待是在线完成的，则应为
            # expired_legs 全数。两种路径都由盘面实况决定期望值。
            still_on_disk = [row for row in expired_legs
                             if (content_dir / (row["record_id"] + ".json")).is_file()]
            result = harness.purge_expired()
            self.check("verify_purge_deleted_only_expired",
                       result.get("deleted_records") == len(still_on_disk),
                       f"deleted_records={result.get('deleted_records')} "
                       f"expected={len(still_on_disk)} released_bytes={result.get('released_bytes')}")

            snapshot_after = state_digest_snapshot(harness.state)
            append_after = append_only_snapshot(harness.state)
            p_removed, p_added, p_modified = scope_changes(snapshot_before, snapshot_after)
            self.check("verify_purge_scope_state_dir",
                       not out_of_scope_changes(p_removed, p_added, p_modified,
                                                append_before, append_after),
                       f"removed={p_removed} added={p_added} modified={p_modified}")

            post_ok, post_detail = True, []
            for row in seed["legs"]:
                items = harness.search_records(row["task_id"])
                file_present = (content_dir / (row["record_id"] + ".json")).is_file()
                if row["expect"] != "survives":
                    ok = not items and not file_present
                else:
                    ok = len(items) == 1 and items[0]["status"] == "active" and file_present
                post_ok = post_ok and ok
                post_detail.append(f"{row['name']}:records={len(items)},file={file_present}")
            self.check("verify_purge_removed_expired_kept_survivor", post_ok, "; ".join(post_detail))

            kept_after = harness.read_record(keep["record_id"], keep["task_id"])
            self.check("verify_survivor_intact_after_purge",
                       kept_after["record"]["plaintext_sha256"] == keep["plaintext_sha256"]
                       and kept_after["record"]["status"] == "active",
                       f"record={keep['record_id']}")

            grants_after = harness.api("/v1/raw-task-content/grants")["items"]
            grant_ids_after = {row.get("grant_id") for row in grants_after}
            # 清理不得触碰 Grant：契约证据分两层。
            # (a) 权威文件层——raw-task-content-authority/ 下三条腿的
            #     rawgrant-*.grant.json 必须全部仍在盘上（含已撤销腿；API
            #     列表会过滤已过期/已撤销授权，列表计数不为契约依据）；
            # (b) 列表层——手动 purge 前后 API 列表完全一致（purge 无副作用）。
            authority_dir = harness.state / "raw-task-content-authority"
            grant_files_after = {
                path.name for path in authority_dir.glob("rawgrant-*.grant.json")
            }
            expected_grant_files = {row["grant_id"] + ".grant.json" for row in seed["legs"]}
            self.check("verify_grants_not_deleted",
                       expected_grant_files <= grant_files_after
                       and grant_ids_after == grant_ids_before,
                       f"grant_files={sorted(grant_files_after)} "
                       f"grants_before={len(grant_ids_before)} grants_after={len(grant_ids_after)}")
            authority_dir = harness.state / "raw-task-content-authority"
            revocation_files = sorted(p.name for p in authority_dir.glob("*revocation*"))
            self.check("verify_revocation_record_retained",
                       bool(revocation_files),
                       f"revocation_files={revocation_files}")

            receipts_after = len(harness.api("/v1/receipts")["receipts"])
            self.check("verify_receipts_not_deleted",
                       receipts_after == receipts_before and receipts_before > 0,
                       f"receipts_before={receipts_before} receipts_after={receipts_after}")
            activities_after = harness.api("/v1/task-activities")["items"]
            self.check("verify_activities_not_deleted",
                       len(activities_after) == activities_count_before
                       and activities_count_before > 0,
                       f"activities_before={activities_count_before} "
                       f"activities_after={len(activities_after)}")

            self.check_export_lifecycle(harness, activities_after)

            evidence = {
                "schema_version": "b04-expiry-verify/v1",
                "created_at": now_text(),
                "seed_path": str(seed_path),
                "seed_created_at": seed["created_at"],
                "binary": {"path": str(self.args.binary), "sha256": binary_digest},
                "state_dir": str(harness.state),
                "port": harness.port,
                "purge_result": result,
                "passed": all(row["ok"] for row in self.checks),
                "checks": self.checks,
            }
        finally:
            if harness is not None:
                harness.stop()
                if harness.binary.exists():
                    harness.binary.chmod(0o600)
                self.log("verify daemon stopped")

        out = self.write_json(evidence)
        self.log(f"verify evidence written: {out} passed={evidence['passed']}")
        return evidence

    def sleep_bounded(self, seconds: float, why: str):
        """真实墙钟等待（--max-wait-seconds 封顶；拒绝缩短时钟的捷径）。"""
        seconds = float(seconds)
        if seconds <= 0:
            return
        limit = float(self.args.max_wait_seconds)
        require(seconds <= limit,
                f"{why}: need {int(seconds)}s real wall-clock wait, exceeds "
                f"--max-wait-seconds={int(limit)}; rerun verify later")
        self.log(f"waiting {int(seconds)}s ({why})…")
        deadline = time.monotonic() + seconds
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(30, left))
            self.log(f"waiting… {int(max(0.0, deadline - time.monotonic()))}s left")

    def observe_expired_before_purge(self, harness, content_dir, expired_legs, keep, *, expect_visible):
        """到期/清理前的元数据观察。

        expect_visible=True（等待在线完成）：过期腿必须 metadata=expired 且
        密文文件仍在盘上——这是"撤销/到期不即刻删密文"契约的直接证据。
        expect_visible=False（verify 启动时已过期，startup lifecycle purge
        已生效，或 --skip-wait）：接受"已消失"或"已过期仍在"两种实况，
        但"仍 active"视为失败（即尚未到期或契约被破坏）。
        """
        ok, detail = True, []
        for row in expired_legs:
            items = harness.search_records(row["task_id"])
            file_present = (content_dir / (row["record_id"] + ".json")).is_file()
            state = items[0].get("status") if items else "MISSING"
            if expect_visible:
                leg_ok = len(items) == 1 and state == "expired" and file_present
            else:
                leg_ok = (len(items) == 1 and state == "expired") or (not items and not file_present)
            ok = ok and leg_ok
            detail.append(f"{row['name']}:status={state},file={file_present}")
        items = harness.search_records(keep["task_id"])
        file_present = (content_dir / (keep["record_id"] + ".json")).is_file()
        state = items[0].get("status") if items else "MISSING"
        ok = ok and len(items) == 1 and state == "active" and file_present
        detail.append(f"{keep['name']}:status={state},file={file_present}")
        self.check("verify_pre_purge_expiry_state", ok,
                   f"expect_visible={expect_visible}; " + "; ".join(detail))

    def check_export_lifecycle(self, harness, activities):
        """Basic export checks only; unknown ID is not cross-task isolation.

        Full two-task export/trace-export checks live in closure-b04-export-runner.py.
        """
        if not activities:
            self.check("verify_export_success", False, "no task activity items; export leg not exercised")
            self.check("verify_export_unknown_id_rejected", False, "not exercised (no activities)")
            self.check("verify_export_requires_auth", False, "not exercised (no activities)")
            return
        snapshot = harness.api("/v1/task-activities")["snapshot"]
        target = activities[0]["activity_id"]
        exported = harness.api(f"/v1/task-activities/{target}/export?snapshot={snapshot}&view=tasks")
        self.check("verify_export_success",
                   exported.get("activity_id") == target and isinstance(exported.get("receipts"), list),
                   f"activity={target[:16]}… receipts={len(exported.get('receipts', []))}")

        unknown = "0" * 64
        status, payload = harness.probe(
            f"/v1/task-activities/{unknown}/export?snapshot={snapshot}&view=tasks",
            token=harness.admin,
        )
        self.check("verify_export_unknown_id_rejected",
                   status == 404 and payload.get("error") == "task_activity_not_found",
                   f"HTTP {status} {payload.get('error')}")

        status, payload = harness.probe(
            f"/v1/task-activities/{target}/export?snapshot={snapshot}&view=tasks",
            token=None,
        )
        self.check("verify_export_requires_auth", status == 401, f"HTTP {status} {payload.get('error')}")


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="closure-b04 raw task content expiry leg")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="capture three legs and write the seed evidence")
    seed.add_argument("--binary", required=True, help="预构建的 siq-agent-security 二进制路径")
    seed.add_argument("--run-dir", required=True, help="隔离 run 根目录（必须不存在）")
    seed.add_argument("--port", type=int, default=None, help="daemon 端口（缺省取空闲端口）")
    seed.add_argument("--out", required=True, help="seed JSON 输出路径")

    verify = sub.add_parser("verify", help="restart, wait for real expiry, purge and assert")
    verify.add_argument("--binary", required=True, help="与 seed 相同的二进制路径")
    verify.add_argument("--seed", required=True, help="seed 阶段产出的 JSON")
    verify.add_argument("--run-dir", default=None, help=argparse.SUPPRESS)  # 复用 seed 的 root
    verify.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)  # 固定用 seed 端口
    verify.add_argument("--max-wait-seconds", type=int, default=2 * 3600,
                        help="verify 内允许的真实等待上限（默认 2h）")
    verify.add_argument("--skip-wait", action="store_true",
                        help="不等待；若未到期则 verify_expiry_elapsed 记为 FAIL")
    verify.add_argument("--out", required=True, help="verify JSON 输出路径")

    args = parser.parse_args(argv)
    if args.command == "seed":
        require(args.run_dir, "seed requires --run-dir")
    runner = B04Runner(args)
    if args.command == "seed":
        report = runner.run_seed()
        return 0 if report.get("legs") else 1
    report = runner.run_verify()
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
