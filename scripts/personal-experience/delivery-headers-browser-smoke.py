#!/usr/bin/env python3
"""OPT-13: actual local binary, pinned Nginx and an isolated proxy, no live IAM.

Requires the production enterprise build with /agent-security/ base, Docker,
and Playwright Chromium. Creates only owned containers/network and private local
state. Never prints pairing/session credentials. No model or business fixtures.
"""

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HEADERS = ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options",
           "Referrer-Policy", "Permissions-Policy", "Cache-Control", "Content-Type")
NGINX_IMAGE = "nginx:1.29.7-alpine3.23@sha256:e7257f1ef28ba17cf7c248cb8ccf6f0c6e0228ab9c315c152f9c203cd34cf6d1"
HTTP = build_opener(ProxyHandler({}))


def require(ok, label):
    if not ok:
        raise RuntimeError(label)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=45, check=False)
    require(result.returncode == 0, "owned_nginx_command_failed")
    return result.stdout.strip()


def request(url, method="GET", headers=None):
    try:
        response = HTTP.open(Request(url, method=method, headers=headers or {}), timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def common_headers(headers, no_content_type=False):
    return (headers.get("X-Content-Type-Options") == "nosniff"
            and headers.get("X-Frame-Options") == "DENY"
            and headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
            and headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"
            and "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")
            and "script-src 'self'" in headers.get("Content-Security-Policy", "")
            and "connect-src 'self'" in headers.get("Content-Security-Policy", "")
            and headers.get("Strict-Transport-Security") is None
            and headers.get("Access-Control-Allow-Origin") is None
            and len(headers.get_all("Content-Type", [])) == (0 if no_content_type else 1))


def response_matrix(base, prefix, js, css, font, local, records):
    cases = [("html", "/", "GET", 200, "text/html", False, {}),
             ("spa", "/overview", "GET", 200, "text/html", False, {}),
             ("javascript", js, "GET", 200, "javascript", True, {}),
             ("stylesheet", css, "GET", 200, "text/css", True, {}),
             ("font", font, "GET", 200, "font/woff2", font.startswith("/assets/"), {}),
             ("head", js, "HEAD", 200, "javascript", True, {}),
             ("range", js, "GET", 206, "javascript", True, {"Range": "bytes=0-15"}),
             ("missing_asset", "/assets/missing.js", "GET", 404, "", False, {}),
             ("extensionless_asset", "/assets/missing", "GET", 404, "", False, {}),
             ("method", js, "POST", 405, "", False, {})]
    if local:
        cases += [("config", "/ui-config.json", "GET", 200, "application/json", False, {}),
                  ("unauthorized", "/v1/status", "GET", 401, "application/json", False, {}),
                  ("host_rejection", "/", "GET", 403, "", False, {"Host": "attacker.invalid:47611"}),
                  ("origin_rejection", "/v1/status", "GET", 403, "", False, {"Origin": "https://attacker.invalid"})]
    else:
        cases += [("health", "/health", "GET", 200, "text/plain", False, {})]
    for name, path, method, expected, mime, immutable, headers in cases:
        status, actual, body = request(base + prefix + path, method, headers)
        require(status == expected, name + "_status")
        require(common_headers(actual), name + "_headers")
        if mime:
            require(mime in actual.get("Content-Type", ""), name + "_mime")
        cache = actual.get("Cache-Control", "")
        require(cache == "public, max-age=31536000, immutable" if immutable else
                cache == "no-store" if local or expected >= 400 or name == "health" else cache == "no-cache",
                name + "_cache")
        if method == "HEAD":
            require(not body, "head_body")
        if name == "range":
            require(len(body) == 16, "range_body")
        records.append({"case": name, "status": status, "headers": {key: actual.get(key) for key in HEADERS}})
    if not local:
        _, headers, _ = request(base + prefix + js)
        status, headers, body = request(base + prefix + js, headers={"If-None-Match": headers["ETag"]})
        require(status == 304 and not body and common_headers(headers, no_content_type=True)
                and headers.get("Cache-Control") == "public, max-age=31536000, immutable", "conditional_asset")
        records.append({"case": "conditional_asset", "status": status,
                        "headers": {key: headers.get(key) for key in HEADERS}})


def browser_defenses(page, css_url, attacker, checks):
    violations, console = [], []
    page.on("console", lambda message: console.append(message.text))
    page.evaluate("""() => { window.__siqViolations=[];
      document.addEventListener('securitypolicyviolation', e => window.__siqViolations.push(e.effectiveDirective));
      const s=document.createElement('script'); s.textContent='window.__siqInjected=true'; document.head.append(s); }""")
    page.wait_for_function("window.__siqViolations.includes('script-src-elem')")
    require(page.evaluate("window.__siqInjected !== true"), "inline_script_executed")
    checks["inline_script_rejected"] = True
    require(page.evaluate("""url => fetch(url).then(() => false).catch(() => true)""", attacker + "/probe"),
            "cross_origin_connect_allowed")
    violations = page.evaluate("window.__siqViolations")
    require("connect-src" in violations, "missing_connect_violation")
    checks["off_origin_connect_rejected"] = True
    failed = page.evaluate("""url => new Promise(resolve => {
      const s=document.createElement('script'); s.src=url;
      s.onload=()=>resolve(false); s.onerror=()=>resolve(true); document.head.append(s);
    })""", css_url)
    require(failed and any("MIME type" in message for message in console), "css_as_script_not_rejected")
    checks["wrong_script_mime_rejected"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--web-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    binary, web = args.binary.resolve(), args.web_dir.resolve()
    require(binary.is_file() and (web / "index.html").is_file(), "candidate_missing")
    args.out_dir.mkdir(parents=True, exist_ok=False)
    image = docker("image", "inspect", NGINX_IMAGE, "--format", "{{.Id}}")
    network, containers, daemon = None, [], None
    records, checks = {}, {}
    attack_counts = {"probe": 0}

    class Attacker(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path == "/probe":
                attack_counts["probe"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<!doctype html><title>Isolated cross-origin fixture</title>")

    with tempfile.TemporaryDirectory(prefix="siq-headers-") as raw:
        root = Path(raw)
        home = root / "home"
        home.mkdir(mode=0o700)
        env = {"PATH": os.environ["PATH"], "HOME": str(home),
               "SIQ_AGENT_SECURITY_STATE_DIR": str(root / "state"), "XDG_CONFIG_HOME": str(home / ".config")}
        with socket.socket() as port_sock:
            port_sock.bind(("127.0.0.1", 0))
            port = port_sock.getsockname()[1]
        local = f"http://127.0.0.1:{port}"

        def cli(*command):
            result = subprocess.run([str(binary), *command, "--port", str(port)], env=env,
                                    capture_output=True, text=True, timeout=20, check=False)
            require(result.returncode == 0, "isolated_daemon_cli_failed")
            return result.stdout

        attacker = ThreadingHTTPServer(("127.0.0.1", 0), Attacker)
        thread = threading.Thread(target=attacker.serve_forever, daemon=True)
        thread.start()
        attack_url = f"http://127.0.0.1:{attacker.server_port}"
        try:
            cli("init")
            daemon = subprocess.Popen([str(binary), "serve", "--port", str(port)], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                require(daemon.poll() is None, "isolated_daemon_exited")
                try:
                    if request(local + "/healthz")[0] == 200:
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("isolated_daemon_not_ready")
            suffix = uuid.uuid4().hex[:12]
            # Current Docker does not publish ports on --internal networks.
            # Use an owned bridge with ports bound only to host loopback; these
            # static Nginx instances have no credentials or external upstreams.
            network = docker("network", "create", "siq-headers-" + suffix)
            backend_name = "siq-headers-web-" + suffix

            def launch(name, product_conf):
                folder = root / name
                folder.mkdir()
                (folder / "product.conf").write_text(product_conf)
                (folder / "nginx.conf").write_text("""worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 128; }
http {
  include /etc/nginx/mime.types;
  default_type application/octet-stream;
  access_log off;
  client_body_temp_path /tmp/client;
  proxy_temp_path /tmp/proxy;
  fastcgi_temp_path /tmp/fastcgi;
  uwsgi_temp_path /tmp/uwsgi;
  scgi_temp_path /tmp/scgi;
  include /run/probe/product.conf;
}
""")
                container = docker("create", "--pull=never", "--name", name, "--read-only", "--network", network,
                                   "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop=ALL",
                                   "--security-opt=no-new-privileges", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
                                   "--publish", "127.0.0.1::80", "--mount", f"type=bind,src={folder},dst=/run/probe,readonly",
                                   "--mount", f"type=bind,src={web},dst=/usr/share/nginx/html,readonly",
                                   "--mount", f"type=bind,src={ROOT / 'apps/web/security-headers.inc'},dst=/etc/nginx/conf.d/security-headers.inc,readonly",
                                   "--entrypoint", "nginx", image, "-c", "/run/probe/nginx.conf", "-g", "daemon off;")
                containers.append(container)
                docker("start", container)
                published = docker("port", container, "80/tcp")
                require(re.fullmatch(r"127\.0\.0\.1:[0-9]+", published) is not None, "unexpected_published_address")
                base = "http://" + published
                for _ in range(50):
                    try:
                        if request(base + "/health")[0] == 200:
                            return base
                    except OSError:
                        time.sleep(.1)
                raise RuntimeError("owned_nginx_not_ready")

            direct = launch(backend_name, (ROOT / "apps/web/nginx.conf").read_text())
            gateway = launch("siq-headers-proxy-" + suffix, """server {
listen 80;
location /agent-security/ { proxy_pass http://BACKEND/; }
location = /health { proxy_pass http://BACKEND/health; }
}
""".replace("BACKEND", backend_name))
            html = (web / "index.html").read_text()
            js = re.search(r'src="/agent-security(/assets/[^" ]+\.js)"', html)[1]
            css = re.search(r'href="/agent-security(/assets/[^" ]+\.css)"', html)[1]
            font = "/assets/" + next((web / "assets").glob("*.woff2")).name
            local_html = request(local + "/")[2].decode()
            local_js = re.search(r'src="(/assets/[^" ]+\.js)"', local_html)[1]
            local_css = re.search(r'href="(/assets/[^" ]+\.css)"', local_html)[1]
            for name, base, prefix, script, style, font_path, is_local in (
                ("local", local, "", local_js, local_css, "/fonts/dm-serif-display-latin-400-normal.woff2", True),
                ("enterprise_direct", direct, "", js, css, font, False),
                ("enterprise_proxy", gateway, "/agent-security", js, css, font, False),
            ):
                records[name] = []
                response_matrix(base, prefix, script, style, font_path, is_local, records[name])
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                page_errors = []
                page.on("pageerror", lambda _: page_errors.append("pageerror"))
                page.goto(local + "/overview")
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                page.get_by_text("手动配对 / 旧版本连接", exact=True).click()
                pairing = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", cli("pair"))[0]
                page.get_by_label("配对码", exact=True).fill(pairing)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                page.reload()
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                checks["local_pair_and_cookie_restore"] = True
                page.goto(local + "/settings")
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                require(page.locator("link[rel=stylesheet]").evaluate("e => !!e.sheet"), "local_css_missing")
                require(not page_errors, "local_management_page_error")
                checks["local_management_navigation_with_styles"] = True
                checks["local_browser"] = {}
                browser_defenses(page, local + local_css, attack_url, checks["local_browser"])
                page.get_by_role("button", name="退出管理", exact=True).click()
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                checks["local_logout"] = True
                enterprise = context.new_page()
                enterprise_errors = []
                enterprise.on("pageerror", lambda _: enterprise_errors.append("pageerror"))
                enterprise.goto(gateway + "/agent-security/overview")
                expect(enterprise.get_by_role("heading", name="欢迎回来", exact=True)).to_be_visible()
                require(enterprise.locator("link[rel=stylesheet]").evaluate("e => !!e.sheet"), "enterprise_css_missing")
                require(not enterprise_errors, "enterprise_login_page_error")
                checks["enterprise_production_login_renders_with_styles"] = True
                checks["enterprise_browser"] = {}
                browser_defenses(enterprise, gateway + "/agent-security" + css, attack_url, checks["enterprise_browser"])
                for name, target in (("local", local + "/overview"), ("enterprise", gateway + "/agent-security/overview")):
                    frame_page = context.new_page()
                    messages = []
                    frame_page.on("console", lambda message, captured=messages: captured.append(message.text))
                    frame_page.goto(attack_url)
                    frame_page.evaluate("url => {const f=document.createElement('iframe'); f.src=url; document.body.append(f)}", target)
                    frame_page.wait_for_function("document.querySelector('iframe') !== null")
                    for _ in range(30):
                        if any("frame-ancestors" in message or "X-Frame-Options" in message for message in messages):
                            break
                        frame_page.wait_for_timeout(100)
                    require(any("frame-ancestors" in message or "X-Frame-Options" in message for message in messages), name + "_frame_not_blocked")
                    checks[name + "_framing_rejected"] = True
                    frame_page.close()
                require(attack_counts["probe"] == 0, "off_origin_probe_reached_receiver")
                checks["blocked_connects_have_no_receiver_effect"] = True
                browser.close()
        finally:
            if daemon is not None and daemon.poll() is None:
                try:
                    stopped = subprocess.run([str(binary), "stop", "--confirm-stop"], env=env,
                                             capture_output=True, timeout=45, check=False)
                    require(stopped.returncode == 0, "owned_daemon_stop_failed")
                    daemon.wait(timeout=15)
                finally:
                    if daemon.poll() is None:
                        daemon.terminate()
                        daemon.wait(timeout=10)
            for container in reversed(containers):
                docker("rm", "-f", container)
            if network is not None:
                docker("network", "rm", network)
            attacker.shutdown()
            attacker.server_close()
            thread.join(timeout=2)
    result = {"schema_version": "siq.delivery-headers-validation/v1", "binary_sha256": digest(binary),
              "nginx_image": image, "nginx_pinned_reference": NGINX_IMAGE,
              "enterprise_html_sha256": digest(web / "index.html"),
              "product_nginx_config_sha256": digest(ROOT / "apps/web/nginx.conf"),
              "header_config_sha256": digest(ROOT / "apps/web/security-headers.inc"),
              "scope": "isolated_local_binary_and_real_nginx_with_controlled_proxy",
              "production_gateway_verified": False, "production_iam_verified": False,
              "dns_rebinding_chain_tested": False, "model_calls": 0,
              "responses": records, "checks": checks}
    (args.out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"result": "passed", "response_cases": sum(map(len, records.values())), "checks": checks}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - browser tracebacks can contain the private pairing input
        label = str(error) if type(error) is RuntimeError and re.fullmatch(r"[a-z_]+", str(error)) else type(error).__name__
        print(json.dumps({"result": "failed", "category": label}), file=sys.stderr)
        raise SystemExit(1) from None
