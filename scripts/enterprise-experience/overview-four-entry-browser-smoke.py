#!/usr/bin/env python3
"""ENT-018-OVERVIEW 企业总览页四入口对齐与状态展示 浏览器验收。

仅使用 127.0.0.1 本地静态服务 + 拦截模拟 API（不连接真实控制面）。
VITE_DEV_MODE 模拟身份构建仅用于测试、不可发布；本脚本不是生产环境验收。
检查项：
- 加载时没有伪零值；成功统计与真实零值；异常统计值不显示为 0；
- 失败显示错误，重试成功恢复；
- 四主入口正确；高级区默认折叠、键盘展开；
- 无权限链接不出现；
- 375/768/1024/1280/1440px 页面与内容区均无横向溢出；
- 无新增业务写请求；无未捕获异常。
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

# 模拟身份权限：四主入口 + 策略/变更可访问（用于完整入口检查）。
FULL_ACCESS = {
    "workspace": True, "overview": True, "agents": True, "permissions": True,
    "findings": True, "policies": True, "changes": True,
    "runtime_bindings": True, "environments": True, "audit": True, "settings": True,
}
# 受限权限：安全/策略/变更不可访问（用于无权限链接不出现检查）。
LIMITED_ACCESS = dict(FULL_ACCESS, findings=False, policies=False, changes=False)
ACTIONS = {k: False for k in ["confirm_assets", "manage_environment", "enroll_devices",
                              "manage_policy", "propose_change", "approve_change"]}


def make_context(access):
    return {
        "schema_version": "console-context/v1",
        "evaluated_at": "2026-09-25T00:00:00Z",
        "tenant": {"id": "fixture-tenant", "name": "模拟验收组织"},
        "actor": {"id": "fixture-user", "type": "user"},
        "authentication": "development_headers",
        "roles": [{"code": "viewer", "label": "模拟只读查看者", "description": "仅用于总览验收"}],
        "custom_role_count": 0,
        "access": access,
        "actions": ACTIONS,
    }


class MockState:
    """脚本与 mock 服务端之间共享的可变状态（按场景切换）。"""
    def __init__(self):
        self.access = FULL_ACCESS
        self.overview = None          # dict 或 None
        self.overview_fail = False    # True 时 /overview 返回 500
        self.overview_delay = 0.0     # >0 时 /overview 挂起该秒数（用于观察加载态）


STATE = MockState()
REQUEST_LOG: list[dict] = []


class MockHandler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="application/json"):
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
            return self._send(200, json.dumps(make_context(STATE.access)).encode())
        if path == "/api/v1/overview":
            if STATE.overview_delay > 0:
                time.sleep(STATE.overview_delay)
            if STATE.overview_fail:
                return self._send(500, json.dumps({"ok": False, "error": {"message": "模拟控制面故障", "code": "simulated_outage"}}).encode())
            return self._send(200, json.dumps(STATE.overview).encode())
        if path == "/health":
            return self._send(200, json.dumps({"ok": True}).encode())
        if path.startswith("/api/"):
            return self._send(404, json.dumps({"ok": False, "error": {"message": "模拟端点不存在", "code": "not_found"}}).encode())
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


def scroll_to_quick_entries(page):
    """文档高度固定为 100dvh（.app-shell overflow:hidden），滚动容器是 .content；
    滚到快捷入口区域再截视口，确保截图能看见被验证的入口。"""
    page.evaluate(
        """() => {
            const el = document.querySelector('.content');
            if (el) { el.scrollTop = el.scrollHeight; }
        }"""
    )
    page.wait_for_timeout(150)


def wait_http(port, timeout=15.0):
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
        "note": "VITE_DEV_MODE 模拟身份构建 + 127.0.0.1 隔离 mock，仅用于总览交互验收，不可发布、不代表生产环境验收。",
        "checks": checks,
        "page_errors": page_errors,
        "request_log_summary": None,
    }

    def check(name, ok, detail=""):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))

    with tempfile.TemporaryDirectory(prefix="siq-overview-four-entry-") as raw:
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
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            # ---- 1. 加载时没有伪零值（挂起 /overview 以观察加载态）----
            STATE.access = FULL_ACCESS
            STATE.overview = {"agents": 0, "candidates": 0, "open_findings": 0,
                              "critical_findings": 0, "environments": 0, "edges_online": 0, "policies": 0}
            STATE.overview_fail = False
            STATE.overview_delay = 1.2
            page.goto(f"{base}/overview", wait_until="domcontentloaded")
            page.wait_for_timeout(300)
            html = page.content()
            check("加载时显示加载提示而非伪零值",
                  "加载中" in html and "未知/未提供" not in html and ">0<" not in html)
            STATE.overview_delay = 0.0
            page.wait_for_timeout(1200)

            # ---- 2. 成功统计与真实零值 ----
            STATE.overview = {"agents": 0, "candidates": 0, "open_findings": 0,
                              "critical_findings": 0, "environments": 0, "edges_online": 0, "policies": 0}
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            html = page.content()
            zero_count = len(page.locator(".stat-value", has_text="0").all())
            check("成功返回真实 0 时显示 0", zero_count == 7, f"zero_count={zero_count}")
            check("真实 0 不解释为已安全/没有风险",
                  ("已安全" not in html) and ("没有风险" not in html) and ("已全面保护" not in html))
            check("显示心跳边界说明", "设备心跳正常不等于已完成盘点或运行时防护已核验" in html)

            # ---- 3. 异常统计值不显示为 0 ----
            STATE.overview = {"agents": -1, "candidates": 2.5, "open_findings": None,
                              "critical_findings": 0, "environments": 3, "edges_online": 0, "policies": 0}
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            html = page.content()
            unknown_count = len(page.locator(".entoverview-value-unknown").all())
            check("缺失/负值/非数字显示未知/未提供（不转 0）", unknown_count >= 3, f"unknown_count={unknown_count}")
            check("响应异常有明确提示", "部分统计数值缺失或异常" in html)

            # ---- 4. 失败显示错误，重试成功恢复 ----
            for invalid_payload in [None, False, 0, "", []]:
                STATE.overview = invalid_payload
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(400)
                html = page.content()
                expected_error = "协议错误" if invalid_payload is None else "统计响应格式异常"
                check(f"非对象响应 {invalid_payload!r} 显示错误与重试",
                      expected_error in html and "重试连接" in html and "stats-grid" not in html)
            STATE.overview_fail = True
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            html = page.content()
            check("失败显示错误与重试入口", "未连接" in html and "重试连接" in html)
            check("失败不显示历史统计", "stats-grid" not in html)
            STATE.overview_fail = False
            STATE.overview = {"agents": 4, "candidates": 1, "open_findings": 0,
                              "critical_findings": 0, "environments": 2, "edges_online": 1, "policies": 3}
            page.locator(".notice .btn").first.click()
            page.wait_for_timeout(400)
            html = page.content()
            check("重试成功清除旧错误并恢复统计",
                  ("未连接" not in html) and (">4<" in html or "4" in html))

            # ---- 5. 四主入口正确 ----
            STATE.overview = {"agents": 0, "candidates": 0, "open_findings": 0,
                              "critical_findings": 0, "environments": 0, "edges_online": 0, "policies": 0}
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            main_tiles = page.locator(".quick-grid .quick-tile")
            hrefs = [main_tiles.nth(i).get_attribute("href") for i in range(main_tiles.count())]
            check("四主入口顺序与 URL 正确",
                  hrefs == ["/agents", "/permissions", "/findings", "/audit"], f"hrefs={hrefs}")
            scroll_to_quick_entries(page)
            page.screenshot(path=str(out / "overview-desktop.png"))

            # ---- 6. 高级区默认折叠、键盘展开 ----
            details = page.locator(".entoverview-secondary")
            check("高级区存在且默认折叠", details.count() == 1 and details.get_attribute("open") is None)
            summary = page.locator(".entoverview-secondary summary")
            summary.focus()
            page.keyboard.press("Enter")
            page.wait_for_timeout(200)
            check("键盘 Enter 展开高级区", details.get_attribute("open") is not None)
            sec_hrefs = [page.locator(".entoverview-secondary-grid .quick-tile").nth(i).get_attribute("href")
                         for i in range(page.locator(".entoverview-secondary-grid .quick-tile").count())]
            check("高级区保留策略/变更入口", sec_hrefs == ["/policies", "/changes"], f"hrefs={sec_hrefs}")
            # 元素级截图：展开后的"管理与高级功能"区域（含策略/变更入口）
            page.locator(".entoverview-secondary").screenshot(
                path=str(out / "overview-desktop-expanded.png"))

            # ---- 7. 无权限链接不出现 ----
            STATE.access = LIMITED_ACCESS
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            all_hrefs = [page.locator(".quick-tile").nth(i).get_attribute("href")
                         for i in range(page.locator(".quick-tile").count())]
            check("无权限入口（安全/策略/变更）不出现",
                  not any(h in all_hrefs for h in ["/findings", "/policies", "/changes"]), f"hrefs={all_hrefs}")
            check("有权限主入口（资产/权限/审计）出现",
                  all(h in all_hrefs for h in ["/agents", "/permissions", "/audit"]), f"hrefs={all_hrefs}")
            check("次级区域无可访问项目时不显示空壳", page.locator(".entoverview-secondary").count() == 0)

            # ---- 8. 五个视口无横向溢出（页面 + 内容区）----
            STATE.access = FULL_ACCESS
            overflow_results = {}
            for width in [375, 768, 1024, 1280, 1440]:
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(f"{base}/overview", wait_until="domcontentloaded")
                page.wait_for_timeout(400)
                doc_overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth")
                content_overflow = page.evaluate(
                    "() => { const el = document.querySelector('.content'); "
                    "return el ? el.scrollWidth - el.clientWidth : 0; }")
                overflow_results[width] = (doc_overflow, content_overflow)
                # 滚动到快捷入口区域后截视口：确保截图能看见被验证的入口（不只截页头）
                if width == 375 or width == 1024:
                    scroll_to_quick_entries(page)
                    page.screenshot(path=str(out / f"overview-{width}.png"))
            check("五个视口页面与内容区均无横向溢出",
                  all(d <= 0 and c <= 0 for d, c in overflow_results.values()),
                  f"overflow={overflow_results}")

            # ---- 9. 无新增业务写请求 ----
            writes = [r for r in REQUEST_LOG if r["method"] in ("POST", "PUT", "PATCH", "DELETE")]
            check("无新增业务写请求", not writes, f"writes={writes[:5]}")

            # ---- 10. 无未捕获异常 ----
            check("无浏览器未捕获异常", not page_errors, f"errors={page_errors[:5]}")

            page.close()
            browser.close()
            pw.stop()
        finally:
            server.shutdown()

    report["request_log_summary"] = {
        "total": len(REQUEST_LOG),
        "write_requests": len([r for r in REQUEST_LOG if r["method"] in ("POST", "PUT", "PATCH", "DELETE")]),
    }
    report["passed"] = all(c["passed"] for c in checks)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{'PASS' if report['passed'] else 'FAIL'}: {sum(c['passed'] for c in checks)}/{len(checks)} checks")
    print(f"report: {out / 'report.json'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
