"""Browser CLI journey through an unchanged production build and real API.

Only the external identity service is a test fixture. The loopback proxy records
business responses without credentials; SQL observations come from the owned DB.
"""
import http.cookies
import json
import mimetypes
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from common import sha256, write_json

CASES = {"ui_assets": 200, "ui_policy_create": 201, "ui_change_create": 201}
ASSERTIONS = ["ui_self_review_blocked", "ui_approval_transaction", "ui_approved_not_effective",
              "ui_no_persistent_token", "ui_mobile_fits", "ui_cross_tenant_denied",
              "ui_disconnected_honest", "ui_owned_resources_closed"]
WRAPPER = "/home/maoyd/.codex/skills/playwright/scripts/playwright_cli.sh"


def evaluate(o):
    posts = [x for x in o.get("api", []) if x["method"] == "POST" and x["path"].endswith("/review-decision")]
    own = o.get("self_review", "")
    approved = o.get("approved", "")
    cross = o.get("cross_tenant", "")
    approve_lines = [line for line in own.splitlines() if 'radio "批准变更"' in line]
    self_blocked = 'radio "批准变更"' not in own
    if o.get("scoring_version") == 2:
        self_blocked = not approve_lines or all("[disabled]" in line for line in approve_lines)
        self_blocked &= any(x["path"] == o["review_path"] and x["status"] == 200
                            and x["body"].get("can_approve") is False
                            and "own_proposal" in x["body"].get("approve_blockers", []) for x in o.get("api", []))
    return {
        "ui_self_review_blocked": "提出者不能批准自己的变更" in own and self_blocked,
        "ui_approval_transaction": len(posts) == 1 and posts[0]["status"] == 200
            and o.get("database", {}).get("change") == [["approved", "ui-reviewer"]]
            and o["database"]["audit"] == [["ui-reviewer"]] and o["database"]["outbox"] == [[1]],
        "ui_approved_not_effective": "已批准，待部署" in approved
            and "批准后还需部署及执行验证" in approved and o.get("database", {}).get("deployments") == [[0]],
        "ui_no_persistent_token": o.get("storage") == {"local": 0, "session": 0},
        "ui_mobile_fits": o.get("mobile", {}).get("viewport") == 390
            and o.get("mobile", {}).get("width", 99999) <= 390,
        "ui_cross_tenant_denied": "暂时无法读取这份变更" in cross and "tp07-ui-policy" not in cross
            and any(x["status"] == 404 and x["path"] == o["review_path"] for x in o.get("api", [])),
        "ui_disconnected_honest": "暂时无法读取这份变更" in o.get("disconnected", "")
            and "已批准，待部署" not in o.get("disconnected", "")
            and any(x.get("fault") == "proxy_upstream_unavailable" for x in o.get("api", [])),
        "ui_owned_resources_closed": o.get("cleanup") == {"browser_closed": True, "proxy_closed": True},
    }


def run(request, identity, sql, check, events, out, candidate, base_url, a):
    assets = request("ui_assets", "GET", "/api/v1/candidates", a)
    asset = next(x for x in assets if x["name"] == "fixture-a")
    policy = request("ui_policy_create", "POST", "/api/v1/policies", a,
                     {"name": "tp07-ui-policy", "selector": {"agent_ids": [asset["id"]]}, "enforcement_mode": "block"})
    change = request("ui_change_create", "POST", "/api/v1/change-requests", a,
                     {"policy_id": policy["id"], "idempotency_key": "tp07-ui-change"})
    root = out / "output/playwright"
    root.mkdir(parents=True)
    dist = candidate / "apps/web/dist"
    session = "tp07ui" + secrets.token_hex(5)
    o = {"api": [], "scoring_version": 2, "review_path": f"/api/v1/change-requests/{change['id']}/review"}
    sessions, state = {}, {"fault": False}
    event_lock = threading.Lock()

    def emit(event, **fields):
        with event_lock:
            events.add(event, **fields)
    actors = {"operator-a": ("tp07-a", ["security_admin", "agent_owner", "reviewer", "auditor"]),
              "ui-reviewer": ("tp07-a", ["reviewer", "auditor"]),
              "ui-other": ("tp07-b", ["reviewer", "auditor"])}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body, content_type="application/json", cookie=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.do_GET()

        def do_GET(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            path = urlsplit(self.path).path
            if path.startswith("/api/iam/"):
                cookie = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
                actor = sessions.get(cookie["tp07ui"].value) if "tp07ui" in cookie else None
                issued = None
                if path.endswith("/login"):
                    value = json.loads(data)
                    actor = value.get("username") if value.get("password") == "fixture-only" else None
                    if actor in actors:
                        issued = secrets.token_hex(24)
                        sessions[issued] = actor
                if actor not in actors:
                    self.reply(401, b'{}')
                    return
                tenant, roles = actors[actor]
                token = identity(tenant, actor, roles)["Authorization"].removeprefix("Bearer ")
                self.reply(200, json.dumps({"access_token": token}).encode(), cookie=(
                    f"tp07ui={issued}; Path=/; HttpOnly; SameSite=Strict" if issued else None))
                return
            if path.startswith("/api/"):
                if state["fault"]:
                    status, body = 502, {"detail": "fixture_upstream_unavailable"}
                    capture = {"method": self.command, "path": self.path, "status": status,
                               "body": body, "fault": "proxy_upstream_unavailable"}
                else:
                    headers = {k: v for k, v in self.headers.items() if k.lower() in
                               {"authorization", "content-type", "accept"}}
                    with httpx.Client(trust_env=False, timeout=15) as client:
                        response = client.request(self.command, base_url + self.path, headers=headers, content=data)
                    status, body = response.status_code, response.json()
                    capture = {"method": self.command, "path": self.path, "status": status, "body": body}
                # Journey only accesses review/list/context endpoints; none return credentials.
                o["api"].append(capture)
                emit("ui_http", **capture)
                self.reply(status, json.dumps(body).encode())
                return
            relative = path.lstrip("/")
            target = (dist / relative).resolve()
            if not target.is_relative_to(dist.resolve()):
                self.reply(404, b'{}')
                return
            if not target.is_file():
                target = dist / "index.html"
            self.reply(200, target.read_bytes(), mimetypes.guess_type(str(target))[0] or "application/octet-stream")

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{proxy.server_port}"
    url = origin + "/changes?change=" + change["id"]
    chrome = Path("/home/maoyd/.cache/ms-playwright/chromium-1246/chrome-linux-arm64/chrome")
    config = root / "cli.config.json"
    write_json(config, {"browser": {"launchOptions": {"headless": True, "executablePath": str(chrome), "chromiumSandbox": False},
                                    "contextOptions": {"viewport": {"width": 1440, "height": 1000}}}})
    index = 0

    def cli(*args):
        nonlocal index
        index += 1
        result = subprocess.run(["bash", WRAPPER, "-s=" + session, *args], cwd=root,
                                capture_output=True, text=True, timeout=45, check=False)
        text = result.stdout + result.stderr
        (root / f"command-{index:03d}.txt").write_text(text)
        emit("ui_command", index=index, argv=list(args), exit_code=result.returncode,
                   capture_sha256=sha256(root / f"command-{index:03d}.txt"))
        if result.returncode or "### Error" in text:
            raise RuntimeError("browser_command_failed")
        return text

    def snapshot(name, required=None):
        deadline = time.monotonic() + 15
        while True:
            text = cli("snapshot")
            match = re.search(r"\[Snapshot\]\(([^)]+)\)", text)
            inline = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
            if inline:
                value = inline[1] + "\n"
            elif match:
                value = (root / match[1]).read_text()
            else:
                raise ValueError("snapshot_reference_absent")
            if required is None or required in value or time.monotonic() > deadline:
                break
            time.sleep(0.3)
        (root / (name + ".yaml")).write_text(value)
        o[name] = value
        return value

    def ref(snapshot_text, label):
        for line in snapshot_text.splitlines():
            if label in line:
                match = re.search(r"\[ref=((?:f\d+)?e\d+)\]", line)
                if match:
                    return match[1]
        raise ValueError("element_reference_absent")

    def login(actor):
        cli("cookie-clear")
        cli("goto", url)
        s = snapshot("login", 'textbox "用户名"')
        cli("fill", ref(s, 'textbox "用户名"'), actor)
        s = snapshot("login-filled")
        cli("fill", ref(s, 'textbox "密码"'), "fixture-only")
        s = snapshot("login-password")
        cli("click", ref(s, 'button "登录"'))

    try:
        cli("open", url, "--config", str(config))
        login("operator-a")
        snapshot("self_review", "提出者不能批准自己的变更")
        cli("screenshot", "--filename=self-review.png")
        login("ui-reviewer")
        s = snapshot("review_ready", 'radio "批准变更"')
        cli("check", ref(s, 'radio "批准变更"'))
        s = snapshot("review_decision", 'checkbox "我已核对')
        cli("check", ref(s, 'checkbox "我已核对'))
        s = snapshot("review_acknowledged", 'button "确认批准"')
        cli("click", ref(s, 'button "确认批准"'))
        snapshot("approved", "已批准，并已从服务端核对")
        cli("screenshot", "--filename=approved-desktop.png")
        o["database"] = {
            "change": sql("SELECT status,approver_user_id FROM change_request WHERE id=%s", (change["id"],)),
            "audit": sql("SELECT actor_id FROM audit_event WHERE resource_id=%s AND action='change.approve'", (change["id"],)),
            "outbox": sql("SELECT count(*) FROM outbox_event WHERE event_type='policy.change.approved.v1' AND payload->'payload'->>'change_request_id'=%s", (change["id"],)),
            "deployments": sql("SELECT count(*) FROM deployment WHERE change_request_id=%s", (change["id"],))}
        text = cli("eval", "() => ({local:localStorage.length,session:sessionStorage.length})")
        o["storage"] = json.loads(text.split("### Result", 1)[1].split("###", 1)[0].strip())
        cli("resize", "390", "844")
        snapshot("approved_mobile", "已批准，待部署")
        cli("screenshot", "--filename=approved-mobile.png")
        text = cli("eval", "() => ({viewport:innerWidth,width:document.documentElement.scrollWidth})")
        o["mobile"] = json.loads(text.split("### Result", 1)[1].split("###", 1)[0].strip())
        cli("resize", "1440", "1000")
        login("ui-other")
        snapshot("cross_tenant", "暂时无法读取这份变更")
        cli("screenshot", "--filename=cross-tenant.png")
        login("ui-reviewer")
        snapshot("before_disconnect", "已批准，待部署")
        state["fault"] = True
        emit("ui_lab_fault", target="owned proxy upstream requests", enabled=True)
        s = snapshot("before_refresh")
        cli("click", ref(s, 'button "刷新内容"'))
        snapshot("disconnected", "暂时无法读取这份变更")
        cli("screenshot", "--filename=disconnected.png")
    finally:
        try:
            cli("close")
            browser_closed = True
        except (RuntimeError, subprocess.TimeoutExpired):
            browser_closed = False
        proxy.shutdown()
        proxy.server_close()
        o["cleanup"] = {"browser_closed": browser_closed, "proxy_closed": True}
        o["artifacts"] = {str(p.relative_to(out)): sha256(p) for p in root.iterdir()
                          if p.is_file() and p.suffix in {".yaml", ".png", ".txt"}}
        write_json(out / "ui-observations.json", o)
        emit("ui_observations", value=o)
    for name, passed in evaluate(o).items():
        check(name, passed, {"source": "ui-observations.json", "predicate": name})
