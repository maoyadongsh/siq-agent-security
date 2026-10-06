"""P06 browser journey through the candidate's embedded UI and unchanged API."""
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common import write_json
from management_trial import Client

WRAPPER = "/home/maoyd/.codex/skills/playwright/scripts/playwright_cli.sh"
CHROME = "/home/maoyd/.cache/ms-playwright/chromium-1246/chrome-linux-arm64/chrome"


def run(h, out, gold):
    root = out / "output/playwright"
    root.mkdir(parents=True)
    session = "p01browser" + secrets.token_hex(5)
    config = root / "cli.config.json"
    write_json(config, {"browser": {"launchOptions": {"headless": True, "executablePath": CHROME, "chromiumSandbox": False},
                                    "contextOptions": {"viewport": {"width": 1440, "height": 1000}}}})
    client = Client(h, lambda _: None)
    renewal = client.request("renew", "/v1/session/pairing", credential="recovery", body={},
                             headers={"X-SIQ-Local-CLI": "1"}, issuance=True)
    pairing = {"code": renewal["code"]}
    observations = {"stages": {}, "scope": "candidate embedded discovery UI; no business API mock"}

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path == "/pairing-input":
                if self.headers.get("Origin") or "code" not in pairing:
                    status, body = 410, b'{}'
                else:
                    status, body = 200, json.dumps({"code": pairing.pop("code")}).encode()
                content_type = "application/json"
            else:
                status, body = 200, b'<!doctype html><title>P06 controlled cross-origin fixture</title><h1>P06 controlled cross-origin fixture</h1><p>Owned evaluation page. No external destination.</p>'
                content_type = "text/html"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    fixture_origin = f"http://127.0.0.1:{fixture.server_port}"
    index = 0
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")}
    env.update(CI="1", NO_UPDATE_NOTIFIER="1", npm_config_offline="true")

    def cli(*args):
        nonlocal index
        index += 1
        response = subprocess.run(["bash", WRAPPER, "--session=" + session, *args], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=45, check=False)
        text = response.stdout + response.stderr
        for secret in client.secrets:
            text = text.replace(secret, "[REDACTED]")
        (root / f"command-{index:03d}.txt").write_text(text)
        if response.returncode or "### Error" in text:
            raise ValueError("browser command failed; inspect sanitized command log")
        return text

    def evaluate(code):
        text = cli("run-code", code)
        return json.loads(text.split("### Result", 1)[1].split("###", 1)[0].strip())

    def snapshot(name, required=None):
        deadline = time.monotonic() + 15
        while True:
            text = cli("snapshot")
            inline = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
            match = re.search(r"\[Snapshot\]\(([^)]+)\)", text)
            value = inline[1] if inline else (root / match[1]).read_text() if match else ""
            if required is None or required in value or time.monotonic() > deadline:
                break
            time.sleep(0.2)
        (root / (name + ".yaml")).write_text(value)
        return value

    def ref(snapshot_text, label):
        for line in snapshot_text.splitlines():
            if label in line:
                match = re.search(r"\[ref=((?:f\d+)?e\d+)\]", line)
                if match:
                    return match[1]
        raise ValueError("fresh snapshot lacks requested UI element")

    def checkpoint():
        observations["browser"] = evaluate("async page => { const p=page.context().__siqProbe; await Promise.race([Promise.allSettled([...p.pending]),new Promise(resolve=>setTimeout(resolve,5000))]); return {responses:p.responses,consoles:p.consoles,wire:p.wire.filter(r=>r.probe),pending_at_capture:p.pending.size}; }")
        write_json(out / f"checkpoint-{index:03d}.json", observations)

    def storage():
        return evaluate("async page => { const p=page.context().__siqProbe; const cookies=await page.context().cookies(); const secrets=[...p.secrets,...cookies.map(c=>c.value)]; return await page.evaluate(secrets=>({local_keys:Object.keys(localStorage),session_keys:Object.keys(sessionStorage),credential_hits:[...Object.values(localStorage),...Object.values(sessionStorage)].filter(v=>secrets.some(s=>s&&v.includes(s))).length,session_cookie_visible:document.cookie.includes('siq_session_')}),secrets); }")

    def state(name, pairing_page=False):
        value = snapshot(name, "管理配对" if pairing_page else "退出")
        observations[name] = {"pairing": "管理配对" in value, "dashboard": "退出" in value and "管理配对" not in value}
        return value

    def capture(name, required):
        snapshot(name, required)
        observations["stages"][name] = {"api": h.api("/v1/assets"), "discovery": h.api("/v1/discovery"),
            "dom": evaluate("async page => await page.evaluate(()=>({path:location.pathname+location.search,headers:[...document.querySelectorAll('main table thead th')].map(e=>e.innerText),rows:[...document.querySelectorAll('main table tbody tr')].map(tr=>({cells:[...tr.querySelectorAll('td')].map(e=>e.innerText),hrefs:[...tr.querySelectorAll('a')].map(a=>a.getAttribute('href'))})),buttons:[...document.querySelectorAll('main button')].map(e=>e.innerText),text:document.querySelector('main').innerText}))")}
        cli("screenshot", "--filename=" + name + ".png")
        checkpoint()
        write_json(out / ("stage-" + name + ".json"), observations["stages"][name])

    def wait_scan(previous=None):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = h.api("/v1/discovery")
            if status["run"]["state"] in ("partial", "succeeded") and status["run"]["run_id"] != previous:
                return
            time.sleep(0.1)
        raise ValueError("UI discovery action did not complete")

    try:
        cli("open", h.endpoint, "--config", str(config))
        cli("run-code", "--filename", str(Path(__file__).with_name("browser_management_probe.js")))
        s = snapshot("unpaired", "手动配对")
        cli("click", ref(s, "手动配对 / 旧版本连接"))
        s = snapshot("manual-pairing", 'textbox "配对码"')
        input_ref = ref(s, 'textbox "配对码"')
        evaluate("async page => { const r=await fetch(" + json.dumps(fixture_origin + "/pairing-input") + "); const v=await r.json(); page.context().__siqProbe.secrets.push(v.code); await page.locator(" + json.dumps("aria-ref=" + input_ref) + ").fill(v.code); return {filled:true}; }")
        cli("click", ref(s, 'button "建立管理会话"'))
        snapshot("paired", "退出管理")
        wait_scan()
        capture("frameworks", "智能体框架（4）")
        s = snapshot("before-roles", "智能体角色（4）")
        cli("click", ref(s, 'button "智能体角色（4）"'))
        capture("roles", 'cell "候选"')
        s = snapshot("before-skills", "Skill（6）")
        cli("click", ref(s, 'button "Skill（6）"'))
        capture("skills", 'cell "未准入"')
        s = snapshot("before-rescan", "重新发现")
        previous = h.api("/v1/discovery")["run"]["run_id"]
        cli("click", ref(s, 'button "重新发现"'))
        wait_scan(previous)
        capture("rescanned", 'cell "未准入"')
        s = snapshot("before-expand", "高级选项：补充目录与扫描范围")
        cli("click", ref(s, 'generic "高级选项：补充目录与扫描范围"'))
        s = snapshot("extra-directory", 'textbox "额外目录（可选）"')
        cli("fill", ref(s, 'textbox "额外目录（可选）"'), gold["project"])
        s = snapshot("before-preview", "预览扫描范围")
        cli("click", ref(s, 'button "预览扫描范围"'))
        capture("preview", 'button "添加目录并扫描"')
        s = snapshot("before-register", 'button "添加目录并扫描"')
        previous = h.api("/v1/discovery")["run"]["run_id"]
        cli("click", ref(s, 'button "添加目录并扫描"'))
        wait_scan(previous)
        capture("registered", "Skill（8）")
        cli("reload")
        capture("reloaded", "Skill（8）")
    finally:
        try:
            checkpoint()
        except Exception as exc:  # noqa: BLE001 -- preserve partial browser observations
            observations["final_capture_error"] = type(exc).__name__
        closed = False
        try:
            cli("close")
            closed = True
        finally:
            fixture.shutdown()
            fixture.server_close()
            thread.join(timeout=5)
            observations["cleanup"] = {"browser_closed": closed, "fixture_closed": not thread.is_alive()}
            write_json(out / "browser-observations.json", observations)
    return observations
