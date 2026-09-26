#!/usr/bin/env python3
"""ENT-018-BINDINGS-UI 运行时绑定列表可视化与登记表单可靠性 浏览器验收。

仅使用 127.0.0.1 本地静态服务 + 拦截模拟 API（不连接真实控制面）。
VITE_DEV_MODE 模拟身份构建仅用于测试、不可发布；本脚本不是生产环境验收。
全部使用合成 fixture（长 ID / 长后端值），不登记/吊销真实绑定、不扫描真实用户目录。

两阶段：
  阶段一（只读）：加载/空/失败重试、列表筛选、分页失败+恢复、键盘展开、
    无权限入口不出现+直接访问被拒、环境/资产/实例各自失败+恢复、乱序实例响应、
    表单关闭重开无旧数据混入、五个视口/长文本/展开/表单/对话框无横向溢出、
    无未捕获异常；断言 0 业务写请求。
  阶段二（业务回归）：登记/吊销全部走 mock，记录 path/method/payload，
    断言载荷正确（不跳过写回归以「零写」为由）。

检查项见下方 check() 调用。
"""

import argparse
import json
import mimetypes
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/html", ".html")

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/web"

FULL_ACCESS = {
    "workspace": True, "overview": True, "agents": True, "permissions": True,
    "findings": True, "policies": True, "changes": True,
    "runtime_bindings": True, "environments": True, "audit": True, "settings": True,
}
# 无运行时绑定权限：用于「入口不出现 + 直接访问被拒」
NO_BINDINGS_ACCESS = dict(FULL_ACCESS, runtime_bindings=False)
ACTIONS = {k: False for k in ["confirm_assets", "manage_environment", "enroll_devices",
                              "manage_policy", "propose_change", "approve_change"]}

# 长 ID / 长后端值：用于溢出与长文本检查
LONG_ID = "rb-" + "a1b2c3d4e5f6" * 8
LONG_TARGET = "sandbox-finance-prod-cluster-" + "x" * 60
LONG_BACKEND = "openshell-cli-enterprise-edition"


def make_context(access):
    return {
        "schema_version": "console-context/v1",
        "evaluated_at": "2026-09-25T00:00:00Z",
        "tenant": {"id": "fixture-tenant", "name": "模拟验收组织"},
        "actor": {"id": "fixture-user", "type": "user"},
        "authentication": "development_headers",
        "roles": [{"code": "viewer", "label": "模拟只读查看者", "description": "仅用于绑定验收"}],
        "custom_role_count": 0,
        "access": access,
        "actions": ACTIONS,
    }


def binding_row(rid, env="env-1", asset="agt-1", inst="inst-1",
                backend="openshell-cli", target="target-1", status="active",
                created="2026-09-01T00:00:00Z", revoked=None):
    return {
        "id": rid, "tenant_id": "fixture-tenant", "environment_id": env,
        "agent_instance_id": inst, "asset_id": asset, "backend": backend,
        "backend_target_id": target, "attestation": {"backend_version": "v0.0.83"},
        "status": status, "created_at": created, "revoked_at": revoked,
    }


class MockState:
    def __init__(self):
        self.access = FULL_ACCESS
        # 列表
        self.bindings = [
            binding_row(LONG_ID, backend=LONG_BACKEND, target=LONG_TARGET),
            binding_row("rb-2", env="env-2", asset="agt-2", inst="inst-2",
                        backend="hermes-sandbox", target="target-2", status="revoked",
                        revoked="2026-09-02T00:00:00Z"),
        ]
        self.bindings_fail = False
        self.bindings_truncated = False   # 首页返回截断头 + nextCursor
        self.bindings_page2_fail = False  # 加载更多（cursor2）返回 500
        # 表单选项
        self.environments = [
            {"id": "env-1", "tenant_id": "fixture-tenant", "name": "环境 env-1",
             "env_type": "host", "mode": "observe", "risk_level": "low", "last_heartbeat_at": None},
            {"id": "env-2", "tenant_id": "fixture-tenant", "name": "环境 env-2",
             "env_type": "host", "mode": "observe", "risk_level": "low", "last_heartbeat_at": None},
        ]
        self.environments_fail = False
        self.agents = [
            {"id": "agt-1", "name": "资产 agt-1", "role": None, "framework": "hermes",
             "status": "managed", "system_id": None, "owner_user_id": None,
             "source_type": None, "source_locator": None, "updated_at": "2026-09-01T00:00:00Z"},
            {"id": "agt-2", "name": "资产 agt-2", "role": None, "framework": "hermes",
             "status": "managed", "system_id": None, "owner_user_id": None,
             "source_type": None, "source_locator": None, "updated_at": "2026-09-01T00:00:00Z"},
        ]
        self.agents_fail = False
        # 实例：agentId -> list；instances_delay 秒（用于乱序）
        self.instances = {
            "agt-1": [{"id": "inst-1", "runtime": "hermes", "version": None,
                       "artifact_digest": None, "location": {}, "status": "running", "observed_at": None}],
            "agt-2": [{"id": "inst-2", "runtime": "hermes", "version": None,
                       "artifact_digest": None, "location": {}, "status": "running", "observed_at": None}],
        }
        self.instances_fail = set()      # agentId 集合：返回 500
        self.instances_delay = 0.0       # 秒
        self.instance_completion_order = []
        # 写操作
        self.create_fail = False
        self.create_delay = 0.0
        self.revoke_fail = False
        self.revoke_delay = 0.0


STATE = MockState()
WRITE_LOG: list[dict] = []
READ_LOG: list[dict] = []


class MockHandler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, headers=None):
        self._send(code, json.dumps(obj).encode(), headers=headers)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _list_headers(self, returned, truncated, next_cursor=None):
        h = {"x-siq-list-limit": "50", "x-siq-list-returned": str(returned),
             "x-siq-list-truncated": "1" if truncated else "0"}
        if next_cursor:
            h["x-siq-next-cursor"] = next_cursor
        return h

    def do_GET(self):  # noqa: N802
        READ_LOG.append({"method": "GET", "path": self.path})
        path = self.path.split("?")[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        if path == "/api/v1/console-context":
            return self._json(200, make_context(STATE.access))
        if path == "/health":
            return self._json(200, {"ok": True})
        if path == "/api/v1/runtime-bindings":
            if STATE.bindings_fail:
                return self._json(500, {"ok": False, "error": {"message": "模拟控制面故障", "code": "simulated_outage"}})
            if "cursor=cursor2" in query:
                if STATE.bindings_page2_fail:
                    return self._json(500, {"ok": False, "error": {"message": "分页加载故障", "code": "page_outage"}})
                return self._json(200, [binding_row("rb-page2", env="env-3")],
                                  headers=self._list_headers(1, False))
            rows = STATE.bindings
            truncated = STATE.bindings_truncated
            return self._json(200, rows, headers=self._list_headers(len(rows), truncated,
                                                                     "cursor2" if truncated else None))
        if path == "/api/v1/environments":
            if STATE.environments_fail:
                return self._json(500, {"ok": False, "error": {"message": "环境服务故障", "code": "env_outage"}})
            return self._json(200, STATE.environments)
        if path == "/api/v1/agents":
            if STATE.agents_fail:
                return self._json(500, {"ok": False, "error": {"message": "资产服务故障", "code": "agent_outage"}})
            return self._json(200, STATE.agents)
        # /api/v1/agents/{id}/instances
        if path.startswith("/api/v1/agents/") and path.endswith("/instances"):
            agent_id = path[len("/api/v1/agents/"):-len("/instances")]
            if STATE.instances_delay > 0 and agent_id == "agt-1":
                time.sleep(STATE.instances_delay)
            STATE.instance_completion_order.append(agent_id)
            if agent_id in STATE.instances_fail:
                return self._json(500, {"ok": False, "error": {"message": "实例服务故障", "code": "inst_outage"}})
            return self._json(200, STATE.instances.get(agent_id, []))
        if path.startswith("/api/"):
            return self._json(404, {"ok": False, "error": {"message": "模拟端点不存在", "code": "not_found"}})
        web_root = Path(self.server.web_root)  # type: ignore[attr-defined]
        target = (web_root / path.lstrip("/")).resolve()
        if not target.is_relative_to(web_root.resolve()) or not target.is_file():
            target = web_root / "index.html"
        if target.is_file():
            ctype, _ = mimetypes.guess_type(target.name)
            return self._send(200, target.read_bytes(), ctype or "application/octet-stream")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        payload = self._read_body()
        WRITE_LOG.append({"method": "POST", "path": self.path, "payload": payload})
        path = self.path.split("?")[0]
        if path == "/api/v1/runtime-bindings":
            if STATE.create_delay:
                time.sleep(STATE.create_delay)
            if STATE.create_fail:
                return self._json(400, {"ok": False, "error": {"message": "后端拒绝登记", "code": "rejected"}})
            new_id = "rb-created-" + str(len(WRITE_LOG))
            return self._json(201, binding_row(new_id))
        if path.startswith("/api/v1/runtime-bindings/") and path.endswith("/revoke"):
            if STATE.revoke_delay:
                time.sleep(STATE.revoke_delay)
            if STATE.revoke_fail:
                return self._json(400, {"ok": False, "error": {"message": "后端拒绝吊销", "code": "rejected"}})
            return self._json(200, binding_row("rb-x", status="revoked", revoked="2026-09-25T00:00:00Z"))
        return self._json(404, {"ok": False, "error": {"message": "模拟端点不存在", "code": "not_found"}})

    def log_message(self, *args):  # 静默
        pass


def wait_http(port, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("模拟控制面未就绪")


def form_selects(page, idx):
    """form-box 内第 idx 个 select（0=环境,1=资产,2=实例）。"""
    return page.locator(".form-box select").nth(idx)


def form_inputs(page):
    return page.locator(".form-box input")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)

    checks: list[dict] = []
    page_errors: list[str] = []
    blocked_requests: list[str] = []
    report = {
        "passed": False,
        "synthetic_identity": True,
        "destination_fixture": True,
        "production_iam": False,
        "note": "VITE_DEV_MODE 模拟身份构建 + 127.0.0.1 隔离 mock + 全合成 fixture，仅用于绑定页交互验收，不可发布、不代表生产 IAM/目标真实性/防护效果。",
        "checks": checks,
        "page_errors": page_errors,
        "blocked_requests": blocked_requests,
        "write_log": WRITE_LOG,
        "request_log_summary": None,
    }

    def check(name, ok, detail=""):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))

    with tempfile.TemporaryDirectory(prefix="siq-runtime-binding-ui-") as raw:
        temporary = Path(raw)
        web_build = temporary / "web-sim"
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TZ", "HOME"}}
        env.update(VITE_DEV_MODE="true", VITE_DEV_TENANT_ID="fixture-tenant", VITE_DEV_USER_ID="fixture-user")
        with (out / "build.log").open("x") as log:
            subprocess.run(["npm", "run", "build", "--", "--outDir", str(web_build)],
                           cwd=WEB, env=env, stdout=log, stderr=log, check=True, timeout=300)

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
        server.web_root = str(web_build)  # type: ignore[attr-defined]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        wait_http(port)
        base = f"http://127.0.0.1:{port}"

        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900}, service_workers="block")
            def isolated_request(route):
                if not route.request.url.startswith(base + "/") or route.request.method not in {"GET", "POST"}:
                    blocked_requests.append(route.request.url)
                    route.abort()
                    return
                route.continue_()
            page.route("**/*", isolated_request)
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            # ============ 阶段一：只读 ============
            # ---- 1. 首次加载（挂起观察加载态）----
            STATE.bindings_fail = False
            STATE.bindings_truncated = False
            page.goto(f"{base}/runtime-bindings", wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            html = page.content()
            check("首次加载显示加载提示/列表，不显示伪空",
                  ("正在加载运行时绑定" in html) or ("rb-explorer-list" in html) or ("已加载" in html),
                  "加载态或列表未出现")

            # ---- 2. 成功列表（含长 ID/长后端值）----
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            html = page.content()
            check("成功列表展示长 ID 与长后端值", LONG_ID in html and LONG_BACKEND in html)
            check("成功列表显示匹配/已加载计数", "已加载" in html and "筛选仅覆盖已加载记录" in html)
            original_bindings = STATE.bindings
            STATE.bindings = [binding_row("rb-unknown", status="pending-verification")]
            page.reload(wait_until="domcontentloaded")
            page.locator(".rb-explorer-actions").wait_for()
            check("未知状态不冒充终态且不提供吊销",
                  "已终态" not in page.locator(".rb-explorer-actions").inner_text()
                  and page.locator(".rb-explorer-actions button").count() == 0)
            STATE.bindings = original_bindings

            # ---- 3. 成功空列表 ----
            saved = STATE.bindings
            STATE.bindings = []
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            html = page.content()
            check("成功空列表明确「后端成功返回空列表」", "后端成功返回空列表" in html)
            STATE.bindings = saved
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)

            # ---- 4. 首次失败：错误+重试，不冒充空 ----
            STATE.bindings_fail = True
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            html = page.content()
            check("首次失败显示错误与重试，不冒充空列表",
                  ("未连接" in html or "重试" in html) and "后端成功返回空列表" not in html)
            STATE.bindings_fail = False
            page.locator(".notice .btn, .disconnected .btn, button:has-text('重试连接')").first.click()
            page.wait_for_timeout(500)
            html = page.content()
            check("重试成功清除错误并恢复列表", LONG_ID in html)

            # ---- 5. 列表筛选（AND 组合 + 文本搜索 + 清除）----
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            # 状态筛选 revoked
            page.locator(".rb-explorer-filters select").nth(0).select_option("revoked")
            page.wait_for_timeout(200)
            html = page.content()
            check("状态筛选 revoked 仅显示已吊销记录", "rb-2" in html and LONG_ID not in html)
            # 文本搜索命中长目标
            page.locator(".rb-explorer-filters select").nth(0).select_option("")
            search = page.locator(".rb-explorer-field-search input")
            search.fill("target-2")
            page.wait_for_timeout(200)
            html = page.content()
            check("文本搜索命中目标 ID", "rb-2" in html and LONG_ID not in html)
            # 无匹配
            search.fill("不存在的ID-xyz")
            page.wait_for_timeout(200)
            html = page.content()
            check("筛选无匹配提示清除筛选", "当前筛选条件下无匹配项" in html and "清除筛选" in html)
            # 清除
            page.locator(".rb-explorer-filters button:has-text('清除筛选')").click()
            page.wait_for_timeout(200)
            html = page.content()
            check("清除筛选恢复全部已加载记录", LONG_ID in html and "rb-2" in html)

            # ---- 6. 分页失败+恢复 ----
            STATE.bindings_truncated = True
            STATE.bindings_page2_fail = True
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            check("截断首页显示「加载更多」", page.locator("button:has-text('加载更多')").count() >= 1)
            page.locator("button:has-text('加载更多')").first.click()
            page.wait_for_timeout(400)
            html = page.content()
            check("分页失败保留已加载数据并显式不完整",
                  (LONG_ID in html) and ("加载更多失败" in html or "不代表全部加载成功" in html))
            STATE.bindings_page2_fail = False
            page.locator("button:has-text('加载更多')").first.click()
            page.wait_for_timeout(400)
            html = page.content()
            check("分页重试成功追加第二页", "rb-page2" in html)
            STATE.bindings_truncated = False

            # ---- 7. 键盘展开详情 ----
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            details = page.locator(".rb-explorer-disclosure")
            check("详情默认折叠", details.count() >= 1 and details.first.get_attribute("open") is None)
            summary = page.locator(".rb-explorer-disclosure summary").first
            summary.focus()
            page.keyboard.press("Enter")
            page.wait_for_timeout(200)
            check("键盘 Enter 展开详情", details.first.get_attribute("open") is not None)
            html = page.content()
            check("详情展示字段原文与语义说明",
                  "绑定 ID" in html and "不等于运行时防护生效" in html and "开放字典" in html)
            check("详情不展开 attestation 值/不渲染 tenant_id",
                  "v0.0.83" not in html and "fixture-tenant" not in html)
            page.screenshot(path=str(out / "bindings-desktop-expanded.png"))

            # ---- 8. 无权限入口不出现 + 直接访问被拒 ----
            STATE.access = NO_BINDINGS_ACCESS
            page.goto(f"{base}/", wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            nav_hrefs = [a.get_attribute("href") for a in page.locator("nav a").all()]
            check("无权限时导航不出现运行时绑定入口", "/runtime-bindings" not in nav_hrefs, f"hrefs={nav_hrefs}")
            page.goto(f"{base}/runtime-bindings", wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            html = page.content()
            check("无权限直接访问被拒（不渲染绑定列表）",
                  "rb-explorer-list" not in html and ("无法访问" in html or "无权" in html or "无权限" in html))
            STATE.access = FULL_ACCESS

            # ---- 9. 环境/资产/实例各自失败+恢复 ----
            page.goto(f"{base}/runtime-bindings", wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            page.locator("button:has-text('登记绑定')").click()
            page.wait_for_timeout(300)
            # 环境失败
            STATE.environments_fail = True
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(300)
            page.locator("button:has-text('登记绑定')").click()
            page.wait_for_timeout(400)
            html = page.content()
            check("环境加载失败明确报错+重试", "环境加载失败" in html and "环境服务故障" in html)
            STATE.environments_fail = False
            page.locator(".rb-explorer-form-err button:has-text('重试')").first.click()
            page.wait_for_timeout(400)
            html = page.content()
            check("环境重试成功恢复选项", "环境 env-1" in html and "环境加载失败" not in html)
            # 资产失败
            STATE.agents_fail = True
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(300)
            page.locator("button:has-text('登记绑定')").click()
            page.wait_for_timeout(400)
            html = page.content()
            check("资产加载失败明确报错+重试", "资产加载失败" in html and "资产服务故障" in html)
            STATE.agents_fail = False
            # 资产重试成功（使资产选项 ready，实例级联才可用）
            page.locator(".rb-explorer-form-err button:has-text('重试')").first.click()
            page.wait_for_timeout(400)
            html = page.content()
            check("资产重试成功恢复选项", "资产 agt-1" in html and "资产加载失败" not in html)
            # 实例失败
            STATE.instances_fail = {"agt-1"}
            form_selects(page, 1).select_option("agt-1")
            page.wait_for_timeout(400)
            html = page.content()
            check("实例加载失败明确报错+重试", "实例加载失败" in html and "实例服务故障" in html)
            STATE.instances_fail = set()
            page.locator(".rb-explorer-form-err button:has-text('重试')").last.click()
            page.wait_for_timeout(400)
            html = page.content()
            check("实例重试成功恢复选项", "inst-1" in html and "实例加载失败" not in html)

            # ---- 10. 乱序实例响应（A 慢、B 快，最终为 B）----
            STATE.instances = {
                "agt-1": [{"id": "inst-A1", "runtime": "hermes", "version": None,
                           "artifact_digest": None, "location": {}, "status": "running", "observed_at": None}],
                "agt-2": [{"id": "inst-B1", "runtime": "hermes", "version": None,
                           "artifact_digest": None, "location": {}, "status": "running", "observed_at": None}],
            }
            STATE.instances_delay = 0.8
            STATE.instance_completion_order = []
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(300)
            page.locator("button:has-text('登记绑定')").click()
            page.wait_for_timeout(400)
            form_selects(page, 1).select_option("agt-1")   # A 慢
            page.wait_for_timeout(150)
            form_selects(page, 1).select_option("agt-2")   # B 快，先返回
            page.wait_for_timeout(1500)                     # 等 B 返回且 A 的迟到响应到达
            html = page.content()
            check("乱序：最终显示 B 的实例而非 A", "inst-B1" in html and "inst-A1" not in html)
            check("乱序夹具确实先完成 B 再完成 A", STATE.instance_completion_order == ["agt-2", "agt-1"])
            STATE.instances_delay = 0.0
            # 恢复默认实例
            STATE.instances = {
                "agt-1": [{"id": "inst-1", "runtime": "hermes", "version": None,
                           "artifact_digest": None, "location": {}, "status": "running", "observed_at": None}],
                "agt-2": [{"id": "inst-2", "runtime": "hermes", "version": None,
                           "artifact_digest": None, "location": {}, "status": "running", "observed_at": None}],
            }

            # ---- 11. 表单实例级联：清空资产/关闭重开无旧数据混入 ----
            # 注意：列表行（rb-1）本身含 inst-1，故只断言表单内实例下拉，不查整页。
            def form_instance_options():
                sel = form_selects(page, 2)
                return [sel.locator("option").nth(i).get_attribute("value")
                        for i in range(sel.locator("option").count())]

            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(300)
            page.locator("button:has-text('登记绑定')").click()
            page.wait_for_timeout(400)
            form_selects(page, 1).select_option("agt-1")
            page.wait_for_timeout(400)
            opts = form_instance_options()
            check("选择资产后实例下拉含该资产实例", "inst-1" in opts, f"options={opts}")
            # 清空资产 → 实例下拉重置为「先选择资产」，不含旧实例（旧响应被拒）
            form_selects(page, 1).select_option("")
            page.wait_for_timeout(300)
            opts2 = form_instance_options()
            check("清空资产后实例下拉重置（不含旧实例）", "inst-1" not in opts2, f"options={opts2}")
            # 关闭再重开：不残留其他资产的实例（需重新选择才加载）
            page.locator("button:has-text('收起')").click()
            page.wait_for_timeout(300)
            page.locator("button:has-text('登记绑定')").click()
            page.wait_for_timeout(400)
            opts3 = form_instance_options()
            check("重开表单实例下拉无跨资产残留", "inst-2" not in opts3, f"options={opts3}")

            # ---- 12. 五个视口/长文本/展开/表单/对话框无横向溢出 ----
            overflow_results = {}
            for width in [375, 768, 1024, 1280, 1440]:
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(f"{base}/runtime-bindings", wait_until="domcontentloaded")
                page.wait_for_timeout(400)
                # 展开详情 + 打开表单 + 打开吊销对话框（长文本场景）
                page.locator(".rb-explorer-disclosure summary").first.click()
                page.wait_for_timeout(150)
                page.locator("button:has-text('登记绑定')").click()
                page.wait_for_timeout(300)
                page.locator(".rb-explorer-actions button:has-text('吊销')").first.click()
                page.wait_for_timeout(300)
                doc_overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth")
                content_overflow = page.evaluate(
                    "() => { const el = document.querySelector('.content'); "
                    "return el ? el.scrollWidth - el.clientWidth : 0; }")
                dialog_overflow = page.locator("[role=dialog]").evaluate("el => el.scrollWidth - el.clientWidth")
                title_overflow = page.locator(".modal-title").evaluate("el => el.scrollWidth - el.clientWidth")
                overflow_results[width] = (doc_overflow, content_overflow, dialog_overflow, title_overflow)
                if width == 375:
                    page.screenshot(path=str(out / "bindings-375-form-dialog.png"))
                # 关闭对话框
                page.locator("button:has-text('取消')").click()
                page.wait_for_timeout(150)
            check("五个视口（展开+表单+对话框+长文本）页面与内容区均无横向溢出",
                  all(all(value <= 0 for value in values) for values in overflow_results.values()),
                  f"overflow={overflow_results}")

            # ---- 13. 阶段一：0 业务写请求 ----
            phase1_writes = [w for w in WRITE_LOG]
            check("阶段一无业务写请求", not phase1_writes, f"writes={phase1_writes[:5]}")

            # ---- 14. 无未捕获异常 ----
            check("阶段一无浏览器未捕获异常", not page_errors, f"errors={page_errors[:5]}")

            # ============ 阶段二：业务回归（mock 记录载荷）============
            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto(f"{base}/runtime-bindings", wait_until="domcontentloaded")
            page.wait_for_timeout(400)

            # ---- 15. 登记成功：正确载荷 ----
            page.locator("button:has-text('登记绑定')").click()
            page.wait_for_timeout(400)
            form_selects(page, 0).select_option("env-1")
            form_selects(page, 1).select_option("agt-1")
            page.wait_for_timeout(400)
            form_selects(page, 2).select_option("inst-1")
            form_inputs(page).nth(1).fill("sandbox-finance-01")
            page.locator(".form-box button:has-text('登记')").last.click()
            page.wait_for_timeout(500)
            create_calls = [w for w in WRITE_LOG if w["path"] == "/api/v1/runtime-bindings" and w["method"] == "POST"]
            check("登记：POST /runtime-bindings 载荷正确",
                  len(create_calls) == 1 and
                  create_calls[0]["payload"] == {
                      "environment_id": "env-1", "agent_instance_id": "inst-1",
                      "backend": "openshell-cli", "backend_target_id": "sandbox-finance-01"},
                  f"payload={create_calls[0]['payload'] if create_calls else None}")
            html = page.content()
            check("登记成功关闭表单并刷新列表", "form-box" not in html)

            # ---- 16. 登记失败：保留输入、明确报错 ----
            STATE.create_fail = True
            page.locator("button:has-text('登记绑定')").click()
            page.wait_for_timeout(400)
            form_selects(page, 0).select_option("env-1")
            form_selects(page, 1).select_option("agt-1")
            page.wait_for_timeout(400)
            form_selects(page, 2).select_option("inst-1")
            form_inputs(page).nth(1).fill("sandbox-finance-02")
            STATE.create_delay = 1.0
            page.locator(".form-box button:has-text('登记')").last.click()
            check("登记在途锁定表单和收起按钮",
                  page.locator(".permissions-toolbar button").is_disabled()
                  and page.locator(".form-box input:enabled, .form-box select:enabled").count() == 0)
            page.locator(".form-box .sync-err").wait_for()
            check("登记失败解锁并保留提交目标",
                  page.locator(".permissions-toolbar button").is_enabled()
                  and form_inputs(page).nth(1).is_enabled()
                  and form_inputs(page).nth(1).input_value() == "sandbox-finance-02")
            STATE.create_delay = 0.0
            html = page.content()
            check("登记失败保留输入并明确报错",
                  "后端拒绝登记" in html and "form-box" in html)
            STATE.create_fail = False

            # ---- 17. 吊销成功：正确载荷（reason 固定）----
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            page.locator(".rb-explorer-actions button:has-text('吊销')").first.click()
            page.wait_for_timeout(300)
            STATE.revoke_delay = 1.0
            page.locator("button:has-text('确认吊销')").click()
            page.keyboard.press("Escape")
            check("吊销在途 Escape 不隐藏确认结果且禁止重复提交",
                  page.locator("[role=dialog]").count() == 1
                  and page.get_by_role("button", name="执行中…").is_disabled())
            page.locator("[role=dialog]").wait_for(state="hidden")
            STATE.revoke_delay = 0.0
            revoke_calls = [w for w in WRITE_LOG if w["path"].startswith("/api/v1/runtime-bindings/")
                            and w["path"].endswith("/revoke")]
            check("吊销：POST /runtime-bindings/{id}/revoke 载荷正确（reason 固定）",
                  len(revoke_calls) == 1 and
                  revoke_calls[0]["payload"] == {"reason": "web-console-manual-revoke"},
                  f"payload={revoke_calls[0]['payload'] if revoke_calls else None}")

            # ---- 18. 吊销失败：不冒充成功 ----
            STATE.revoke_fail = True
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            page.locator(".rb-explorer-actions button:has-text('吊销')").first.click()
            page.wait_for_timeout(300)
            page.locator("button:has-text('确认吊销')").click()
            page.wait_for_timeout(500)
            html = page.content()
            check("吊销失败明确报错（不冒充成功）", "后端拒绝吊销" in html)
            STATE.revoke_fail = False

            # ---- 19. 阶段二写请求仅限预期的登记/吊销 ----
            unexpected = [w for w in WRITE_LOG
                          if not (w["path"] == "/api/v1/runtime-bindings" or
                                  (w["path"].startswith("/api/v1/runtime-bindings/") and w["path"].endswith("/revoke")))]
            check("阶段二写请求仅限登记/吊销（无其他业务写）", not unexpected, f"unexpected={unexpected[:5]}")

            # ---- 20. 全程无未捕获异常 ----
            check("全程无浏览器未捕获异常", not page_errors, f"errors={page_errors[:5]}")
            check("全程未尝试访问隔离模拟服务以外地址或未预期方法", not blocked_requests)

            page.close()
            browser.close()
            pw.stop()
        finally:
            server.shutdown()

    report["request_log_summary"] = {
        "total_reads": len(READ_LOG),
        "write_requests": len(WRITE_LOG),
        "write_paths": sorted({w["path"] for w in WRITE_LOG}),
    }
    report["passed"] = all(c["passed"] for c in checks)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{'PASS' if report['passed'] else 'FAIL'}: {sum(c['passed'] for c in checks)}/{len(checks)} checks")
    print(f"report: {out / 'report.json'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
