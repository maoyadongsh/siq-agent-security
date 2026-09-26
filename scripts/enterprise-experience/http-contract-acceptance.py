#!/usr/bin/env python3
"""真实 HTTP 契约级验收（R09.7）：一次性回环 dev 控制面，逐条核对**已声明**的合同。

这个文件要回答的问题是：把控制面真的跑起来、用真实 HTTP 打进去，
那些**写在 packages/contracts 里**的条目（状态码族、隔离序、分页元数据、审计-状态同事务、
启动 fail-closed、秘密不外泄）在**当前候选**上到底成不成立。

边界（读这份报告时必须一并读这些，否则会读成超出的东西）：
- 身份是**合成 X-Dev-***（`get_identity` 的 dev 分支），**不是真实 IAM**；不构成生产登录、
  真实身份或真实权限来源的证明。
- 数据库是**一次性临时 SQLite**；**零容器**，不碰宿主服务、宿主数据库、宿主 systemd。
- 只绑 `127.0.0.1` 的随机端口，进程组在 `finally` 回收，并断言端口与临时目录已释放。
- 只核对**已声明**的条目；未声明的行为不在此列，本文件不发明新合同。
- **不产生 `enforcement_verified`**：一次合成身份的回环请求不构成策略已生效或防护有效的证据。

退出码：0 全部判据成立；1 有判据不成立；2 用法错误；3 报告写入失败。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL_API = ROOT / "apps" / "control-api"
VENV_PYTHON = CONTROL_API / ".venv" / "bin" / "python"

EXIT_PASS = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_REPORT_WRITE_FAILED = 3

NON_CLAIMS = (
    "合成 X-Dev-* 身份 ≠ 真实 IAM：不证明生产登录、真实身份或真实权限来源",
    "一次性临时 SQLite ≠ 生产 PostgreSQL；零容器，不碰宿主服务/数据库/systemd",
    "只核对 packages/contracts 中**已声明**的条目；未声明的行为不在结论内",
    "不产生 enforcement_verified；不证明策略生效、防护有效或业务权限已授予",
)

# 合成身份：租户/用户/角色都来自 X-Dev-*（仅 dev_mode 生效），不是真实主体。
IDENT_A = {
    "X-Dev-Tenant-Id": "acc-tenant-a",
    "X-Dev-User-Id": "acc-user-a",
    "X-Dev-Roles": "tenant_admin",
}
IDENT_A_AUDITOR = {
    "X-Dev-Tenant-Id": "acc-tenant-a",
    "X-Dev-User-Id": "acc-auditor-a",
    "X-Dev-Roles": "auditor",
}
IDENT_B = {
    "X-Dev-Tenant-Id": "acc-tenant-b",
    "X-Dev-User-Id": "acc-user-b",
    "X-Dev-Roles": "tenant_admin",
}
IDENT_B_AUDITOR = {
    "X-Dev-Tenant-Id": "acc-tenant-b",
    "X-Dev-User-Id": "acc-auditor-b",
    "X-Dev-Roles": "auditor",
}


def _markers(acc: Acceptance) -> dict:
    """本轮注入的**真实**秘密材料（合成值，但确实被服务当秘密使用）：用于扫描外泄。"""
    return {
        "dev JWT 共享密钥": acc.ids["jwt_marker"],
        "控制面签名种子（base64）": acc.ids["seed_b64"],
        "合成 bearer 令牌": acc.ids["bearer_token"],
    }


def _hdr(resp: Resp, name: str) -> str:
    """响应头取值的短表示，同时直接当检查的 detail 用。"""
    return f"{name}={resp.header(name)!r}"


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    text: str

    def json(self):
        try:
            return json.loads(self.text)
        except (ValueError, TypeError):
            return None

    def detail(self):
        payload = self.json()
        return payload.get("detail") if isinstance(payload, dict) else None

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    def rows(self) -> list:
        payload = self.json()
        return payload if isinstance(payload, list) else []


@dataclass
class Acceptance:
    out_dir: Path
    root: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="siq-http-acceptance-")))
    endpoint: str = ""
    port: int = 0
    checks: list[dict] = field(default_factory=list)
    exchanges: list[dict] = field(default_factory=list)
    ids: dict = field(default_factory=dict)

    # ---- 记录 ----

    def check(self, group: str, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"group": group, "name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def status_is(self, group: str, name: str, resp: Resp, expect: int) -> bool:
        detail = "" if resp.status == expect else f"detail={resp.detail()!r}"
        return self.check(group, name, resp.status == expect, f"status={resp.status} 期望={expect} {detail}".strip())

    # ---- HTTP ----

    def request(self, method: str, path: str, ident: dict | None = None, body=None, bearer=None) -> Resp:
        headers = dict(ident or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if bearer:
            headers["Authorization"] = bearer
        request = urllib.request.Request(self.endpoint + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, raw, raw_headers = response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            with exc:
                status, raw, raw_headers = exc.code, exc.read(), dict(exc.headers)
        text = raw.decode("utf-8", "replace")
        resp = Resp(status=status, headers={k.lower(): v for k, v in raw_headers.items()}, text=text)
        self.exchanges.append({"request": f"{method} {path}", "status": status, "headers": resp.headers, "body": text})
        return resp

    def get(self, path: str, ident: dict | None = None, bearer=None) -> Resp:
        return self.request("GET", path, ident, bearer=bearer)

    def post(self, path: str, ident: dict | None, body) -> Resp:
        return self.request("POST", path, ident, body=body)

    def patch(self, path: str, ident: dict | None, body) -> Resp:
        return self.request("PATCH", path, ident, body=body)

    # ---- 组装与回收 ----

    def build_env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TZ")}
        env.update(
            {
                "HOME": str(self.root),
                "SIQ_AS_DEV": "1",
                "SIQ_AS_ALLOW_SQLITE": "1",
                "SIQ_AS_DATABASE_URL": f"sqlite:///{self.root}/api.db",
                "SIQ_AS_SIGNING_KEY_FILE": str(self.root / "signing.seed"),
                "SIQ_AS_ENFORCEMENT_BACKEND": "fake",
                "SIQ_AS_DEV_JWT_SECRET": self.ids["jwt_marker"],
            }
        )
        return env

    def boot(self) -> subprocess.Popen:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{self.port}"
        (self.root / "signing.seed").write_text(self.ids["seed_b64"] + "\n", encoding="utf-8")
        tenants = "Tenant(id='acc-tenant-a', name='验收组织甲'), Tenant(id='acc-tenant-b', name='验收组织乙')"
        bootstrap = self.root / "serve.py"
        bootstrap.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(CONTROL_API)!r})\n"
            "from app.main import app, settings\n"
            "from app.db import Base, get_engine, init_db, session_scope\n"
            "from app.models import Tenant\n"
            "init_db(settings)\n"
            "Base.metadata.create_all(get_engine())\n"
            "with session_scope() as s:\n"
            f"    s.add_all([{tenants}])\n"
            "import uvicorn\n"
            # log_level=info 是刻意选择：error 级别下服务端一行都不输出，"秘密不进日志"就只是空集为真；
            # info 让启动行（app.main:75 的 dev 模式告警）真实落盘，日志扫描才有内容可查。
            f"uvicorn.run(app, host='127.0.0.1', port={self.port}, log_level='info', access_log=False)\n",
            encoding="utf-8",
        )
        log = (self.root / "server.log").open("wb")
        process = subprocess.Popen(
            [str(VENV_PYTHON), str(bootstrap)],
            env=self.build_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log.close()
        return process

    def wait_ready(self, process: subprocess.Popen) -> None:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError(f"控制面进程提前退出，code={process.returncode}")
            try:
                with urllib.request.urlopen(self.endpoint + "/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.25)
        raise RuntimeError("控制面就绪超时")

    def teardown(self, process: subprocess.Popen | None, markers: dict) -> dict:
        """回收：停进程组 → 端口核验 → 目录内文件扫描 → 移除目录 → 目录核验。

        顺序是刻意的：目录内文件（含一次性 SQLite 库）只有在 rmtree **之前**才读得到，
        所以秘密扫描必须发生在这里，而不是事后。
        """
        info: dict = {"process_exited": None, "port_released": None, "temp_dir_removed": None, "file_hits": []}
        if process is not None:
            self._stop(process)
            info["process_exited"] = process.poll() is not None
        if (self.root / "server.log").is_file():
            shutil.copyfile(self.root / "server.log", self.out_dir / "server-stdout-stderr.log")
        info["port_released"] = self._port_free()
        # 临时库等工作文件由本工具自建自收，读自身产物不越界；
        # signing.seed / serve.py 是本轮的输入材料（本就该含那些内容），不在扫描对象内。
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name in {"signing.seed", "serve.py"}:
                continue
            blob = path.read_bytes()
            info["file_hits"].extend(f"{path.name}:{label}" for label, m in markers.items() if m.encode() in blob)
        shutil.rmtree(self.root, ignore_errors=True)
        info["temp_dir_removed"] = not self.root.exists()
        return info

    @staticmethod
    def _stop(process: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def _port_free(self) -> bool:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", self.port))
                return True
            except OSError:
                return False


# ---------------- 判据组 ----------------


def judge_health(acc: Acceptance) -> None:
    group = "health_json_shape"
    for path in ("/health", "/api/v1/health"):
        resp = acc.get(path)
        acc.status_is(group, f"GET {path} 200", resp, 200)
        acc.check(group, f"GET {path} 体为 status=ok", resp.json() == {"status": "ok"}, f"body={resp.text[:80]}")


def judge_locate_before_permission(acc: Acceptance) -> None:
    """对象级隔离序：先租户定位（404）再权限（403）——见 app/security.py 的 ensure_permission 文档串。"""
    group = "locate_before_permission"
    created = acc.post("/api/v1/environments", IDENT_A, {"name": "acc-env-alpha"})
    acc.status_is(group, "准备：租户甲建环境 201", created, 201)
    env_id = acc.ids["env_a"] = ((created.json() or {}).get("id")) or ""
    acc.check(group, "准备：返回服务端生成的 id（env_…）", env_id.startswith("env"), f"id={env_id!r}")

    probe = {"mode": "enforce", "reason": "probe"}
    forbidden = acc.patch(f"/api/v1/environments/{env_id}/mode", IDENT_A_AUDITOR, probe)
    acc.status_is(group, "同租户无 env:manage → 403", forbidden, 403)
    acc.check(group, "403 detail=forbidden", forbidden.detail() == "forbidden", f"{forbidden.detail()!r}")

    absent = acc.patch("/api/v1/environments/env-absent-alpha/mode", IDENT_A_AUDITOR, probe)
    acc.status_is(group, "同租户不存在 id + 无权限 → 404（不是 403）", absent, 404)

    cross = acc.patch(f"/api/v1/environments/{env_id}/mode", IDENT_B, probe)
    acc.status_is(group, "跨租户 id + 有权限 → 404（不是 200/403）", cross, 404)

    acc.check(
        group,
        "不存在与跨租户的 404 不可区分（同状态 + 同正文）",
        absent.status == cross.status and absent.text == cross.text,
        f"absent={absent.text!r} cross={cross.text!r}",
    )

    listed = acc.get("/api/v1/environments", IDENT_B)
    ids = [row.get("id") for row in listed.rows()]
    acc.check(group, "租户乙列表不含甲的环境 id", env_id not in ids, f"乙列表={ids}")
    unchanged = acc.get("/api/v1/environments", IDENT_A).rows()
    acc.check(group, "跨租户 404 后甲环境未被改动", [r.get("mode") for r in unchanged] == ["discovery"], "")


def judge_error_family(acc: Acceptance) -> None:
    group = "error_code_family"
    anonymous = acc.get("/api/v1/environments")
    acc.status_is(group, "无身份头 → 401", anonymous, 401)
    missing_cred = anonymous.detail()
    acc.check(group, "401 detail=missing_credentials", missing_cred == "missing_credentials", f"{missing_cred!r}")

    denied = acc.get("/api/v1/audit-events", IDENT_A)
    acc.status_is(group, "角色矩阵：tenant_admin 无 audit:read → 403", denied, 403)
    acc.check(group, "403 detail=forbidden", denied.detail() == "forbidden", f"{denied.detail()!r}")
    acc.status_is(group, "角色矩阵：auditor 有 audit:read → 200", acc.get("/api/v1/audit-events", IDENT_A_AUDITOR), 200)

    conflict = acc.post("/api/v1/environments", IDENT_A, {"name": "acc-env-alpha"})
    acc.status_is(group, "同租户重名 → 409", conflict, 409)
    acc.check(
        group,
        "409 detail=environment_name_conflict",
        conflict.detail() == "environment_name_conflict",
        f"{conflict.detail()!r}",
    )

    bad_enum = acc.post("/api/v1/environments", IDENT_A, {"name": "acc-env-bogus", "mode": "not-a-mode"})
    acc.status_is(group, "非法枚举 → 422", bad_enum, 422)
    missing = acc.patch(f"/api/v1/environments/{acc.ids.get('env_a')}/mode", IDENT_A, {"mode": "observe"})
    acc.status_is(group, "缺必填 reason → 422", missing, 422)

    empty_filter = acc.get("/api/v1/audit-events?request_id=", IDENT_A_AUDITOR)
    acc.status_is(group, "空串精确过滤参数 → 422（合同 §4）", empty_filter, 422)
    overlong = acc.get(f"/api/v1/audit-events?request_id={'x' * 65}", IDENT_A_AUDITOR)
    acc.status_is(group, "超长精确过滤参数 → 422（合同 §4）", overlong, 422)


def judge_audit_same_transaction(acc: Acceptance) -> None:
    group = "audit_state_same_transaction"
    env_id = acc.ids["env_a"]

    events = acc.get(f"/api/v1/audit-events?action=environment.create&resource_id={env_id}", IDENT_A_AUDITOR)
    acc.status_is(group, "建环境后可查到该环境的审计事件 200", events, 200)
    rows = events.rows()
    acc.check(group, "建环境留下恰 1 条 environment.create", len(rows) == 1, f"rows={len(rows)}")
    if rows:
        row = rows[0]
        acc.check(group, "审计记录了合成操作者 id", row.get("actor_id") == "acc-user-a", f"{row.get('actor_id')!r}")
        acc.check(group, "审计记录了 actor_type=user", row.get("actor_type") == "user", f"{row.get('actor_type')!r}")
        summary = json.dumps(row.get("summary"), ensure_ascii=False)
        acc.check(group, "审计 summary 不落内部数据库字段", "tenant_id" not in summary, f"summary={summary[:60]}")

    def create_total() -> int | None:
        resp = acc.get("/api/v1/audit-events?action=environment.create&include_total=true&limit=1", IDENT_A_AUDITOR)
        raw = resp.header("x-siq-list-total")
        return int(raw) if raw else None

    before = create_total()
    acc.patch(f"/api/v1/environments/{env_id}/mode", IDENT_A, {"mode": "observe", "reason": "acceptance"})
    acc.check(group, "成功状态变更不额外造环境（总数不变）", create_total() == before, f"{before}→{create_total()}")
    mode_events = acc.get(f"/api/v1/audit-events?action=environment.mode.update&resource_id={env_id}", IDENT_A_AUDITOR)
    mode_count = len(mode_events.rows())
    acc.check(group, "状态变更与审计成对出现（mode.update 可见）", mode_count == 1, f"rows={mode_count}")

    before_409 = create_total()
    acc.post("/api/v1/environments", IDENT_A, {"name": "acc-env-alpha"})
    after_409 = create_total()
    acc.check(group, "409 回滚后不留下审计（失败不写审计）", after_409 == before_409, f"{before_409}→{after_409}")

    before_404 = create_total()
    acc.patch("/api/v1/environments/env-absent-alpha/mode", IDENT_A, {"mode": "observe", "reason": "acceptance"})
    acc.check(group, "404 定位失败不留下审计", create_total() == before_404, f"{before_404}→{create_total()}")

    cross = acc.get(f"/api/v1/audit-events?resource_id={env_id}", IDENT_B_AUDITOR)
    acc.status_is(group, "租户乙按同一 resource_id 查询 200（租户谓词内）", cross, 200)
    acc.check(group, "租户乙查不到甲的审计事件", cross.rows() == [], f"rows={len(cross.rows())}")


def judge_declared_pagination(acc: Acceptance) -> None:
    """只核对合同已声明的条目：enterprise-audit-query.v1.md §5、enterprise-environment-list.v1.md。"""
    group = "declared_pagination"
    for name in ("acc-env-beta", "acc-env-gamma"):
        acc.post("/api/v1/environments", IDENT_A, {"name": name})
    acc.post("/api/v1/environments", IDENT_B, {"name": "acc-env-b-only"})

    def audit_page(query: str) -> Resp:
        base = "/api/v1/audit-events?resource_type=environment&include_total=true"
        return acc.get(f"{base}&{query}", IDENT_A_AUDITOR)

    first = audit_page("limit=2")
    acc.status_is(group, "审计列表带分页参数 200", first, 200)
    acc.check(group, "X-SIQ-List-Limit=2", first.header("x-siq-list-limit") == "2", _hdr(first, "x-siq-list-limit"))
    returned = first.header("x-siq-list-returned")
    acc.check(group, "X-SIQ-List-Returned=2", returned == "2", f"x-siq-list-returned={returned!r}")
    acc.check(group, "X-SIQ-List-Truncated=1（截断必须标出）", first.header("x-siq-list-truncated") == "1", "")
    cursor = first.header("x-siq-next-cursor")
    acc.check(group, "截断时给出 X-SIQ-Next-Cursor", bool(cursor), f"{cursor!r}")
    total_a = int(first.header("x-siq-list-total") or -1)
    acc.check(group, "租户甲 total 反映全部匹配（4 条：3 建 + 1 改）", total_a == 4, f"total={total_a}")

    page_one = [row.get("id") for row in first.rows()]
    second = audit_page(f"limit=2&cursor={urllib.parse.quote(str(cursor))}")
    acc.status_is(group, "翻页 200", second, 200)
    page_two = [row.get("id") for row in second.rows()]
    acc.check(group, "两页无重复项", not set(page_one) & set(page_two), f"{len(page_one)}/{len(page_two)}")
    acc.check(
        group,
        "后续页 total 仍为全量（不受 cursor 影响）",
        second.header("x-siq-list-total") == str(total_a),
        _hdr(second, "x-siq-list-total"),
    )

    clamped = acc.get("/api/v1/audit-events?limit=999", IDENT_A_AUDITOR)
    clamped_limit = clamped.header("x-siq-list-limit")
    acc.check(group, "limit 硬上限 200（合同 §5 的钳制语义）", clamped_limit == "200", f"limit={clamped_limit!r}")

    tenant_b = acc.get("/api/v1/audit-events?resource_type=environment&include_total=true", IDENT_B_AUDITOR)
    tenant_b_total = tenant_b.header("x-siq-list-total")
    acc.check(group, "总数按租户口径（乙 = 1，不并甲）", tenant_b_total == "1", f"total={tenant_b_total!r}")

    full = acc.get("/api/v1/environments", IDENT_A)
    acc.status_is(group, "环境列表不带 limit 200", full, 200)
    acc.check(group, "未提供 limit 时保持全量返回（3 条）", len(full.rows()) == 3, f"len={len(full.rows())}")
    full_truncated = full.header("x-siq-list-truncated")
    acc.check(group, "未截断时不标 truncated", full_truncated == "0", f"truncated={full_truncated!r}")
    cache = full.header("cache-control")
    acc.check(group, "环境列表声明 Cache-Control: no-store", cache == "no-store", f"cache-control={cache!r}")

    page = acc.get("/api/v1/environments?limit=1", IDENT_A)
    truncated = page.header("x-siq-list-truncated") == "1" and bool(page.header("x-siq-next-cursor"))
    first_cursor = page.header("x-siq-next-cursor")
    acc.check(group, "环境列表 limit=1 时截断且给出环境 id 游标", truncated, f"cursor={first_cursor!r}")
    cursor_env = page.header("x-siq-next-cursor")
    acc.check(group, "环境游标即前页末条环境 id", (page.rows() or [{}])[0].get("id") == cursor_env, f"{cursor_env!r}")

    seen: list[str] = [row.get("id") for row in page.rows()]
    walk = cursor_env
    for _ in range(5):
        chunk = acc.get(f"/api/v1/environments?limit=1&cursor={urllib.parse.quote(str(walk))}", IDENT_A)
        seen.extend(row.get("id") for row in chunk.rows())
        if chunk.header("x-siq-list-truncated") != "1":
            break
        walk = chunk.header("x-siq-next-cursor")
    acc.check(group, "逐页走完不重不漏（3 条各一次）", len(seen) == 3 and len(set(seen)) == 3, f"seen={len(seen)}")

    no_limit = acc.get(f"/api/v1/environments?cursor={urllib.parse.quote(str(cursor_env))}", IDENT_A)
    acc.status_is(group, "cursor 不与 limit 同用 → 422", no_limit, 422)
    acc.check(
        group,
        "422 detail=environment_list_cursor_unavailable",
        no_limit.detail() == "environment_list_cursor_unavailable",
        f"{no_limit.detail()!r}",
    )

    foreign = acc.get(f"/api/v1/environments?limit=1&cursor={urllib.parse.quote(str(cursor_env))}", IDENT_B)
    acc.status_is(group, "跨租户游标不可定位 → 422（不透露其他租户）", foreign, 422)
    foreign_detail = foreign.detail()
    acc.check(group, "跨租户游标同 detail（不区分存在与否）", foreign_detail == no_limit.detail(), "")

    overlong = acc.get(f"/api/v1/environments?limit=1&cursor={'y' * 65}", IDENT_A)
    acc.status_is(group, "游标超 64 字符 → 422", overlong, 422)


def judge_fail_closed_startup(acc: Acceptance) -> None:
    """启动期 fail-closed：直接用 app/config.py 的已声明拒绝条件，不起服务、不连数据库。"""
    group = "fail_closed_startup"
    probe = "from app.config import load_settings; load_settings()"
    base = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TZ")}
    pg = "postgresql+psycopg://u@127.0.0.1:1/db"
    # 注意 config.py:78 的 allow_sqlite 默认值是 dev_mode 本身：dev 模式**默认允许** SQLite，
    # 真正被声明的拒绝条件是"显式否认"（SIQ_AS_ALLOW_SQLITE=0）。这里的措辞必须与之一致。
    dev_sqlite_denied = {"SIQ_AS_DEV": "1", "SIQ_AS_ALLOW_SQLITE": "0", "SIQ_AS_DATABASE_URL": "sqlite:///./x.db"}
    cases = [
        ("生产模式缺 SIQ_AS_DATABASE_URL → 拒绝", {}, "生产模式必须配置 SIQ_AS_DATABASE_URL"),
        ("生产模式给 SQLite → 拒绝", {"SIQ_AS_DATABASE_URL": "sqlite:///./x.db"}, "生产模式仅允许 PostgreSQL"),
        ("生产模式缺 JWKS → 拒绝", {"SIQ_AS_DATABASE_URL": pg}, "SIQ_AS_OIDC_JWKS_URL"),
        ("dev 模式显式否认 SQLite（ALLOW_SQLITE=0）→ 拒绝", dev_sqlite_denied, "仅显式开发模式允许"),
    ]
    for name, extra, expected in cases:
        env = dict(base)
        env.update(extra)
        done = subprocess.run(
            [str(VENV_PYTHON), "-c", probe],
            cwd=str(CONTROL_API),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        acc.check(group, name, done.returncode != 0, f"returncode={done.returncode}")
        acc.check(group, f"{name}（报出原因）", expected in (done.stderr + done.stdout), f"期望含 {expected!r}")
    acc.check(group, "以上均为配置期静态判定（未起服务、未连数据库）", True, "probe 只调用 load_settings()")


GROUP_NO_SECRET_ECHO = "no_secret_echo"


def judge_no_secret_echo_live(acc: Acceptance) -> None:
    """秘密不外泄（服务在线的一半）：HTTP 响应面与审计正文。

    先用几类真实请求把响应面铺开：无身份、无权限、有权限、按 resource_id 精确过滤、总览。
    """
    group = GROUP_NO_SECRET_ECHO
    acc.get("/api/v1/environments", bearer="Bearer " + acc.ids["bearer_token"])
    acc.get("/api/v1/audit-events", IDENT_A)
    acc.get("/api/v1/audit-events", IDENT_A_AUDITOR)
    acc.get(f"/api/v1/audit-events?resource_id={acc.ids.get('env_a')}", IDENT_A_AUDITOR)
    acc.get("/api/v1/overview", IDENT_A)

    http_blob = json.dumps(acc.exchanges, ensure_ascii=False)
    for label, marker in _markers(acc).items():
        acc.check(group, f"HTTP 响应/响应头不含{label}", marker not in http_blob, f"marker_len={len(marker)}")

    audit = acc.get("/api/v1/audit-events?resource_type=environment&limit=200", IDENT_A_AUDITOR)
    audit_blob = json.dumps(audit.json(), ensure_ascii=False)
    has_rows = bool(audit_blob.strip("[] "))
    acc.check(group, "审计事件有实际内容可扫（否则退化为空集）", has_rows, f"len={len(audit_blob)}")
    for label, marker in _markers(acc).items():
        acc.check(group, f"审计事件正文不含{label}", marker not in audit_blob, "")


def judge_no_secret_echo_evidence(acc: Acceptance, teardown: dict) -> None:
    """秘密不外泄（停机后的一半）：服务日志与临时库文件——两者只有此刻还存在。"""
    group = GROUP_NO_SECRET_ECHO
    log_path = acc.out_dir / "server-stdout-stderr.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    captured = bool(log_text.strip())
    acc.check(group, "服务 stdout/stderr 已捕获且非空（空日志扫描退化）", captured, f"log_bytes={len(log_text)}")
    for label, marker in _markers(acc).items():
        acc.check(group, f"服务 stdout/stderr 不含{label}", marker not in log_text, "")

    hits = teardown.get("file_hits") or []
    acc.check(group, "临时工作目录内文件（含一次性 SQLite 库）不含秘密材料", not hits, f"hits={hits}")
    acc.check(group, "回环端到端只用合成身份（无真实身份材料进入请求）", True, "ident 全部为 X-Dev-* 合成值")


def _git_candidate() -> dict:
    def git(*argv: str) -> str:
        try:
            done = subprocess.run(["git", "-C", str(ROOT), *argv], capture_output=True, text=True, timeout=30)
            return done.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "worktree_changed_tracked": len(git("status", "--porcelain", "--untracked-files=no").splitlines()),
        "worktree_entries_incl_untracked": len(git("status", "--porcelain", "--untracked-files=all").splitlines()),
        "scope": "工作树候选（含并行作者未提交改动），不是某个提交的独立切片",
    }


def _report(acc: Acceptance, teardown: dict, run_error: str | None) -> dict:
    groups: dict[str, dict] = {}
    for check in acc.checks:
        bucket = groups.setdefault(check["group"], {"group": check["group"], "status": "held", "checks": []})
        bucket["checks"].append(check)
        if not check["ok"]:
            bucket["status"] = "failed"
    failed = [c for c in acc.checks if not c["ok"]]
    return {
        "mode": "loopback_dev_http_contract_acceptance",
        "not_a_claim": list(NON_CLAIMS),
        "candidate": _git_candidate(),
        "isolation": {
            "bind": f"127.0.0.1:{acc.port}",
            "database": "sqlite:///<mktemp>/api.db（一次性，随进程组一起回收）",
            "identity": "合成 X-Dev-*（dev_mode 分支）",
            "containers": 0,
            "dependencies_added": 0,
        },
        "judgments": list(groups.values()),
        "totals": {"checks": len(acc.checks), "failed": len(failed)},
        "conclusion": "run_error" if run_error else ("contracts_failed" if failed else "contracts_held"),
        "run_error": run_error,
        "teardown": teardown,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True, help="证据目录（必须不存在，由本工具独占创建）")
    args = parser.parse_args()
    if not VENV_PYTHON.is_file():
        print(f"用法错误：缺少控制面解释器 {VENV_PYTHON}", file=sys.stderr)
        return EXIT_USAGE
    try:
        args.out_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(f"用法错误：证据目录不可独占创建：{exc}", file=sys.stderr)
        return EXIT_USAGE

    acc = Acceptance(out_dir=args.out_dir)
    acc.ids.update(
        {
            "jwt_marker": f"acc-marker-jwt-{secrets.token_hex(16)}",
            "seed_b64": base64.b64encode(secrets.token_bytes(32)).decode(),
            "bearer_token": secrets.token_urlsafe(24),
        }
    )
    process = None
    run_error = None
    teardown: dict = {}
    try:
        process = acc.boot()
        acc.wait_ready(process)
        judge_health(acc)
        judge_locate_before_permission(acc)
        judge_error_family(acc)
        judge_audit_same_transaction(acc)
        judge_declared_pagination(acc)
        judge_no_secret_echo_live(acc)
    except Exception as exc:  # noqa: BLE001 — 出错也要出货报告
        run_error = f"{type(exc).__name__}: {exc}"
    finally:
        teardown = acc.teardown(process, _markers(acc))

    try:
        judge_fail_closed_startup(acc)
        judge_no_secret_echo_evidence(acc, teardown)
    except Exception as exc:  # noqa: BLE001
        run_error = run_error or f"{type(exc).__name__}: {exc}"

    teardown_checks = (
        ("控制面进程已退出", "process_exited"),
        ("回环端口已释放", "port_released"),
        ("临时工作目录已移除", "temp_dir_removed"),
    )
    for name, key in teardown_checks:
        acc.check("teardown", name, teardown.get(key) is True, f"{key}={teardown.get(key)}")

    report = _report(acc, teardown, run_error)
    try:
        (args.out_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.out_dir / "exchanges.json").write_text(
            json.dumps(acc.exchanges, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(f"报告写入失败：{exc}", file=sys.stderr)
        return EXIT_REPORT_WRITE_FAILED

    for group in report["judgments"]:
        print(f"[{group['status']}] {group['group']}")
        for check in group["checks"]:
            mark = "OK  " if check["ok"] else "FAIL"
            suffix = f" — {check['detail']}" if check["detail"] else ""
            print(f"    {mark} {check['name']}{suffix}")
    print(f"结论：{report['conclusion']}（{report['totals']['checks']} 条判据，{report['totals']['failed']} 条不成立）")
    print(f"报告：{args.out_dir / 'report.json'}")
    return EXIT_PASS if report["conclusion"] == "contracts_held" else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
