#!/usr/bin/env python3
"""ENT-018 企业端导航简化（四主入口 + 高级折叠区）浏览器验收。

仅使用隔离模拟响应（127.0.0.1 本地 mock 控制面），不连接真实业务数据；
VITE_DEV_MODE 构建仅用于模拟验收、不可发布。检查项：
- 桌面四主入口（资产/权限/安全/审计）与默认折叠的高级区域；
- 键盘展开高级入口、选择链接、焦点可见；
- 直接访问旧管理 URL 时高级区域自动展开（不改变浏览器 URL）；
- 权限不足的链接不出现，直达页面仍被拒绝；
- 桌面图标折叠态仍可访问高级功能；
- 375px 移动抽屉：点选关闭、Escape 关闭、无横向溢出；
- 前进/后退导航正确；
- 无新增业务写请求、无浏览器未捕获异常。
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

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/html", ".html")

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/web"

# 模拟身份权限：四主入口 + 总览可访问；策略/变更/绑定/环境不可访问。
ACCESS = {
    "workspace": True, "overview": True, "agents": True, "permissions": True,
    "findings": True, "policies": False, "changes": False,
    "runtime_bindings": False, "environments": False, "audit": True, "settings": True,
}
ACTIONS = {k: False for k in ["confirm_assets", "manage_environment", "enroll_devices",
                              "manage_policy", "propose_change", "approve_change"]}
CONSOLE_CONTEXT = {
    "schema_version": "console-context/v1",
    "evaluated_at": "2026-09-25T00:00:00Z",
    "tenant": {"id": "fixture-tenant", "name": "模拟验收组织"},
    "actor": {"id": "fixture-user", "type": "user"},
    "authentication": "development_headers",
    "roles": [{"code": "viewer", "label": "模拟只读查看者", "description": "仅用于导航验收"}],
    "custom_role_count": 0,
    "access": ACCESS,
    "actions": ACTIONS,
}

REQUEST_LOG: list[dict] = []


class MockHandler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log(self):
        REQUEST_LOG.append({"method": self.command, "path": self.path})

    def do_GET(self):  # noqa: N802
        self._log()
        path = self.path.split("?")[0]
        if path == "/api/v1/console-context":
            return self._send(200, json.dumps(CONSOLE_CONTEXT).encode())
        if path in ("/api/v1/agents", "/api/v1/candidates", "/api/v1/findings",
                    "/api/v1/audit-events", "/api/v1/environments", "/api/v1/policies",
                    "/api/v1/change-requests", "/api/v1/runtime-bindings",
                    "/api/v1/permissions"):
            return self._send(200, b"[]")
        if path == "/api/v1/overview":
            return self._send(200, json.dumps({"agents": 0, "candidates": 0, "open_findings": 0,
                                               "critical_findings": 0, "environments": 0,
                                               "edges_online": 0, "policies": 0}).encode())
        if path == "/api/v1/inventory/access":
            return self._send(200, json.dumps({"schema_version": "inventory-access/v1",
                                               "can_confirm": False, "can_discover": False,
                                               "can_manage_policy": False}).encode())
        if path == "/api/v1/skill-installations":
            return self._send(200, json.dumps({"schema_version": "enterprise-skill-inventory/v1",
                                               "items": [], "next_cursor": None}).encode())
        if path == "/health":
            return self._send(200, json.dumps({"ok": True}).encode())
        if path.startswith("/api/"):
            return self._send(404, json.dumps({"ok": False, "error": {"message": "模拟端点不存在", "code": "not_found"}}).encode())
        # 静态文件 + SPA 回退
        web_root = Path(self.server.web_root)  # type: ignore[attr-defined]
        target = (web_root / path.lstrip("/")).resolve()
        if not target.is_relative_to(web_root.resolve()) or not target.is_file():
            target = web_root / "index.html"
        if target.is_file():
            ctype, _ = mimetypes.guess_type(target.name)
            return self._send(200, target.read_bytes(), ctype or "application/octet-stream")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        self._log()
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._send(405, json.dumps({"ok": False, "error": {"message": "模拟控制面不接受写请求", "code": "method_not_allowed"}}).encode())

    do_PUT = do_POST  # type: ignore[assignment]
    do_PATCH = do_POST  # type: ignore[assignment]
    do_DELETE = do_POST  # type: ignore[assignment]

    def log_message(self, *args):  # 静默
        pass


def wait_http(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("模拟控制面未就绪")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)

    checks: list[dict] = []
    page_errors: list[str] = []
    report = {
        "passed": False,
        "synthetic_identity": True,
        "destination_fixture": True,
        "production_iam": False,
        "note": "VITE_DEV_MODE 模拟身份构建，仅用于导航交互验收，不可发布、不代表生产环境验收。",
        "checks": checks,
        "page_errors": page_errors,
        "request_log_summary": None,
    }

    def check(name: str, ok: bool, detail: str = ""):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))

    with tempfile.TemporaryDirectory(prefix="siq-four-entry-nav-") as raw:
        temporary = Path(raw)
        web_build = temporary / "web-sim"
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TZ", "HOME"}}
        env.update(VITE_DEV_MODE="true", VITE_DEV_TENANT_ID="fixture-tenant",
                   VITE_DEV_USER_ID="fixture-user")
        with (out / "build.log").open("x") as log:
            subprocess.run(["npm", "run", "build", "--", "--outDir", str(web_build)],
                           cwd=WEB, env=env, stdout=log, stderr=log, check=True, timeout=300)

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
        server.web_root = str(web_build)  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        wait_http(port)
        base = f"http://127.0.0.1:{port}"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1280, "height": 800})
                page = context.new_page()
                page.on("pageerror", lambda err: page_errors.append(str(err)))

                # ---- 1. 桌面：四主入口 + 默认折叠高级区域 ----
                page.goto(f"{base}/agents", wait_until="networkidle")
                main_links = page.locator(".entnav-main a.nav-link")
                labels = [main_links.nth(i).inner_text().strip() for i in range(main_links.count())]
                hrefs = [main_links.nth(i).get_attribute("href") for i in range(main_links.count())]
                check("桌面四主入口标签与 URL",
                      labels == ["资产", "权限", "安全", "审计"] and
                      hrefs == ["/agents", "/permissions", "/findings", "/audit"],
                      f"labels={labels} hrefs={hrefs}")
                toggle = page.locator(".entnav-advanced-toggle")
                check("高级区域存在且默认折叠",
                      toggle.count() == 1 and toggle.get_attribute("aria-expanded") == "false")
                check("高级区域默认不渲染入口列表",
                      page.locator("#entnav-advanced-items").count() == 0)
                check("顶栏标题为资产", page.locator(".topbar-title").inner_text().strip() == "资产")
                page.screenshot(path=str(out / "desktop-main.png"), animations="disabled")

                # 资产子页面应保留唯一主入口高亮，标题仍区分清单与详情。
                for route, title in (("/agents/skills", "技能清单"),
                                     ("/agents/fixture-agent", "资产详情")):
                    page.goto(f"{base}{route}", wait_until="networkidle")
                    active = page.locator(".entnav-main a.active[aria-current='page']")
                    check(f"{route} 归属唯一资产入口且标题正确",
                          active.count() == 1 and active.get_attribute("href") == "/agents"
                          and page.locator(".topbar-title").inner_text().strip() == title)
                page.goto(f"{base}/agents", wait_until="networkidle")

                # ---- 2. 键盘展开 + 选择 + 焦点可见 ----
                toggle.focus()
                focused = page.evaluate("document.activeElement === document.querySelector('.entnav-advanced-toggle')")
                ring = page.evaluate("getComputedStyle(document.activeElement).boxShadow")
                check("折叠控件可键盘聚焦且焦点可见", focused and ring and ring != "none", f"boxShadow={ring}")
                page.keyboard.press("Enter")
                check("键盘 Enter 展开高级区域",
                      toggle.get_attribute("aria-expanded") == "true" and
                      page.locator("#entnav-advanced-items").count() == 1)
                overview_link = page.locator("#entnav-advanced-items a", has_text="总览")
                overview_link.focus()
                page.keyboard.press("Enter")
                page.wait_for_url(f"{base}/overview")
                check("键盘选择高级入口链接可导航", page.url.rstrip("/") == f"{base}/overview")

                # ---- 3. 直接访问旧管理 URL 自动展开（URL 不变）----
                page.goto(f"{base}/policies", wait_until="networkidle")
                check("直达旧管理 URL 时高级区域自动展开",
                      toggle.get_attribute("aria-expanded") == "true" and
                      page.url.rstrip("/") == f"{base}/policies")
                check("无权限直达页面仍被拒绝",
                      page.locator("text=当前账号无法访问此页面").count() == 1)

                # ---- 4. 权限不足的链接不出现 ----
                advanced_texts = [page.locator("#entnav-advanced-items a").nth(i).inner_text().strip()
                                  for i in range(page.locator("#entnav-advanced-items a").count())]
                check("无权限入口（策略/变更/绑定/环境）不在高级区域出现",
                      not any(t in advanced_texts for t in ["策略中心", "变更中心", "运行时绑定", "环境与设备"]),
                      f"shown={advanced_texts}")
                check("有权限入口（工作台/总览/设置）出现",
                      all(t in advanced_texts for t in ["工作台", "总览", "设置"]),
                      f"shown={advanced_texts}")

                # ---- 5. 桌面图标折叠态仍可访问高级功能 ----
                page.goto(f"{base}/agents", wait_until="networkidle")
                page.locator(".nav-collapse-btn").click()
                page.wait_for_timeout(400)
                check("桌面侧栏进入图标折叠态", page.locator(".sidebar.collapsed").count() == 1)
                collapsed_toggle = page.locator(".entnav-advanced-toggle")
                check("图标态高级入口仍有可访问名称",
                      collapsed_toggle.count() == 1 and
                      (collapsed_toggle.get_attribute("title") or "").strip() == "管理与高级功能")
                collapsed_toggle.click()
                page.wait_for_timeout(200)
                check("图标态可展开高级区域", collapsed_toggle.get_attribute("aria-expanded") == "true")
                page.locator("#entnav-advanced-items a", has_text="设置").click()
                page.wait_for_url(f"{base}/settings")
                check("图标态可访问高级功能链接", page.url.rstrip("/") == f"{base}/settings")
                page.screenshot(path=str(out / "desktop-collapsed.png"), animations="disabled")

                # ---- 6. 前进/后退 ----
                page.goto(f"{base}/agents", wait_until="networkidle")
                page.goto(f"{base}/permissions", wait_until="networkidle")
                page.go_back()
                page.wait_for_url(f"{base}/agents")
                page.go_forward()
                page.wait_for_url(f"{base}/permissions")
                check("前进/后退导航正确", page.url.rstrip("/") == f"{base}/permissions")

                # ---- 7. 375px 移动抽屉 ----
                mobile = browser.new_context(viewport={"width": 375, "height": 667})
                mpage = mobile.new_page()
                mpage.on("pageerror", lambda err: page_errors.append(str(err)))
                mpage.goto(f"{base}/agents", wait_until="networkidle")
                mpage.locator(".hamburger").click()
                mpage.wait_for_timeout(400)
                check("移动端抽屉可打开", mpage.locator(".sidebar.open").count() == 1)
                mpage.screenshot(path=str(out / "mobile-drawer.png"), animations="disabled")
                mpage.locator(".entnav-main a", has_text="资产").click()
                mpage.wait_for_timeout(400)
                check("移动端点选链接关闭抽屉", mpage.locator(".sidebar.open").count() == 0)
                mpage.locator(".hamburger").click()
                mpage.wait_for_timeout(400)
                mpage.keyboard.press("Escape")
                mpage.wait_for_timeout(400)
                check("移动端 Escape 关闭抽屉", mpage.locator(".sidebar.open").count() == 0)
                overflow = mpage.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                check("375px 无横向溢出", overflow <= 0, f"overflow={overflow}px")
                mobile.close()

                browser.close()
        finally:
            server.shutdown()

    writes = [r for r in REQUEST_LOG if r["method"] in ("POST", "PUT", "PATCH", "DELETE")]
    report["request_log_summary"] = {
        "total": len(REQUEST_LOG),
        "write_requests": len(writes),
        "write_paths": sorted({r["path"] for r in writes}),
    }
    check("无新增业务写请求", not writes, f"writes={writes[:5]}")
    check("无浏览器未捕获异常", not page_errors, f"errors={page_errors[:5]}")

    report["passed"] = all(c["passed"] for c in checks)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{'PASS' if report['passed'] else 'FAIL'}: {sum(c['passed'] for c in checks)}/{len(checks)} checks")
    print(f"report: {out / 'report.json'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
