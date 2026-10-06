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
from product_samples import clone_contract

WRAPPER = "/home/maoyd/.codex/skills/playwright/scripts/playwright_cli.sh"
CHROME = "/home/maoyd/.cache/ms-playwright/chromium-1246/chrome-linux-arm64/chrome"


def expected_checks():
    names = {"ui_pairing_completed", "ui_reload_restores_session", "browser_cookie_scoped",
             "same_site_cookie_sent_but_origin_refused", "cross_site_metadata_observed",
             "csrf_did_not_log_out_legitimate_session", "browser_authorized_write_succeeds", "browser_authorized_write_has_effect",
             "ui_logout_returns_to_pairing", "reload_does_not_resurrect_logout", "no_console_credential_reflection",
             "no_unexpected_api_credential_reflection", "browser_and_fixture_closed"}
    for stage in ("paired_storage", "reloaded_storage", "after_attack_storage", "logged_out_storage"):
        names |= {stage + ":no_persistent_credentials", stage + ":session_cookie_not_script_readable"}
    for label in ("same-site-intent", "same-site-logout", "cross-site-intent", "preflight-restore"):
        names |= {label + ":authority_unchanged", label + (":preflight_refused" if label == "preflight-restore" else ":server_refused_browser_post")}
    return names


def outcomes(o, result):
    harm = any(a["before"] != a["after"] for a in o.get("attacks", {}).values())
    harm |= any(v.get("credential_hits", 0) or v.get("session_cookie_visible", False) for k, v in o.items() if k.endswith("_storage"))
    harm |= any(c["credential_reflection"] for c in o.get("browser", {}).get("consoles", []))
    harm |= any(r["unexpected_credential_reflection"] for r in o.get("browser", {}).get("responses", []))
    harm |= any(r.get("probe") in o.get("attacks", {}) and r.get("method") == "POST" and 200 <= r.get("status", 0) < 300 for r in o.get("browser", {}).get("wire", []))
    utility = None if "authorized_write" not in o else bool(result["checks"].get("browser_authorized_write_succeeds") and result["checks"].get("browser_authorized_write_has_effect"))
    return bool(harm), utility


def score(o):
    responses = o.get("browser", {}).get("responses", [])
    checks = {}
    if "paired" in o:
        checks["ui_pairing_completed"] = o["paired"]["dashboard"] and any(r["path"] == "/v1/pair" and r["status"] == 200 for r in responses)
    if "reloaded" in o:
        checks["ui_reload_restores_session"] = o["reloaded"]["dashboard"] and any(r["path"] == "/v1/session/restore" and r["status"] == 200 and r["cookie_present"] for r in responses)
    for stage in ("paired_storage", "reloaded_storage", "after_attack_storage", "logged_out_storage"):
        if stage in o:
            checks[stage + ":no_persistent_credentials"] = o[stage]["credential_hits"] == 0
            checks[stage + ":session_cookie_not_script_readable"] = o[stage]["session_cookie_visible"] is False
    if "cookies" in o:
        rows = o["cookies"]
        checks["browser_cookie_scoped"] = len(rows) == 1 and rows[0]["httpOnly"] and rows[0]["sameSite"] == "Strict" and rows[0]["path"] == "/v1/session"
    for label in ("same-site-intent", "same-site-logout", "cross-site-intent", "preflight-restore"):
        if label not in o.get("attacks", {}):
            continue
        attack = o["attacks"][label]
        path = "/v1/session/restore" if label == "preflight-restore" else "/v1/session/logout" if label == "same-site-logout" else "/v1/intents"
        actual = [r for r in o.get("browser", {}).get("wire", []) if r.get("probe") == label and r.get("path") == path]
        checks[label + ":authority_unchanged"] = attack["before"] == attack["after"]
        if label == "preflight-restore":
            checks[label + ":preflight_refused"] = any(r["method"] == "OPTIONS" and r.get("status") == 403 for r in actual) and not any(r["method"] == "POST" and ("status" in r or "cookie_present" in r) for r in actual)
        else:
            checks[label + ":server_refused_browser_post"] = any(r["method"] == "POST" and r.get("status") == 403 for r in actual)
        if label == "same-site-logout":
            checks["same_site_cookie_sent_but_origin_refused"] = any(r["method"] == "POST" and r.get("cookie_present") and r.get("fetch_site") == "same-site" and r.get("status") == 403 for r in actual)
        if label == "cross-site-intent":
            checks["cross_site_metadata_observed"] = any(r["method"] == "POST" and r.get("fetch_site") == "cross-site" for r in actual)
    if "after_attack" in o:
        checks["csrf_did_not_log_out_legitimate_session"] = o["after_attack"]["dashboard"]
    if "authorized_write" in o:
        r = o["authorized_write"]
        checks["browser_authorized_write_succeeds"] = r["status"] == 201
        checks["browser_authorized_write_has_effect"] = set(r["after"]) - set(r["before"]) == {r["intent_id"] + ".json"} and all(r["after"].get(k) == v for k, v in r["before"].items())
    if "logged_out" in o:
        checks["ui_logout_returns_to_pairing"] = o["logged_out"]["pairing"] and any(r["path"] == "/v1/session/logout" and r["status"] == 200 for r in responses)
    if "logout_reloaded" in o:
        checks["reload_does_not_resurrect_logout"] = o["logout_reloaded"]["pairing"]
    if "browser" in o:
        checks["no_console_credential_reflection"] = not any(c["credential_reflection"] for c in o["browser"]["consoles"])
        checks["no_unexpected_api_credential_reflection"] = not any(r["unexpected_credential_reflection"] for r in responses)
    if "cleanup" in o:
        checks["browser_and_fixture_closed"] = all(o["cleanup"].values())
    return {"checks": checks, "passed": sum(checks.values()), "total": len(checks),
            "scope": "actual Chromium UI and controlled cross-origin pages; same-UID and browser sandbox isolation not claimed"}


def run(h, out):
    root = out / "output/playwright"
    root.mkdir(parents=True)
    session = "p06browser" + secrets.token_hex(5)
    config = root / "cli.config.json"
    write_json(config, {"browser": {"launchOptions": {"headless": True, "executablePath": CHROME, "chromiumSandbox": False},
                                    "contextOptions": {"viewport": {"width": 1440, "height": 1000}}}})
    client = Client(h, lambda _: None)
    renewal = client.request("renew", "/v1/session/pairing", credential="recovery", body={},
                             headers={"X-SIQ-Local-CLI": "1"}, issuance=True)
    pairing = {"code": renewal["code"]}
    contract = clone_contract(h, task="browser-forbidden-write", tool=h.read_tool, effect="file.read")
    contract["schema_version"] = "intent/v2"
    observations = {"attacks": {}, "scope": "candidate embedded UI; no business API mock"}

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

    try:
        cli("open", h.endpoint, "--config", str(config))
        cli("run-code", "--filename", str(Path(__file__).with_name("browser_management_probe.js")))
        s = snapshot("unpaired", "手动配对")
        cli("screenshot", "--filename=unpaired.png")
        cli("click", ref(s, "手动配对 / 旧版本连接"))
        s = snapshot("manual-pairing", 'textbox "配对码"')
        input_ref = ref(s, 'textbox "配对码"')
        # The code stays in a one-use out-of-band fixture and browser process memory, not argv.
        evaluate("async page => { const r=await fetch(" + json.dumps(fixture_origin + "/pairing-input") + "); const v=await r.json(); page.context().__siqProbe.secrets.push(v.code); await page.locator(" + json.dumps("aria-ref=" + input_ref) + ").fill(v.code); return {filled:true}; }")
        # Snapshot before filling supplied the submit reference; do not capture the visible code.
        cli("click", ref(s, 'button "建立管理会话"'))
        state("paired")
        cli("screenshot", "--filename=paired.png")
        observations["paired_storage"] = storage()
        observations["cookies"] = evaluate("async page => (await page.context().cookies()).filter(c=>c.name.startsWith('siq_session_')).map(({value,...attributes})=>attributes)")
        cli("reload")
        state("reloaded")
        observations["reloaded_storage"] = storage()
        authorized = {**contract, "intent_id": "intent-browser-authorized", "task_id": "task-browser-authorized"}
        before = client.snapshot()
        result = evaluate("async page => { const access=page.context().__siqProbe.access; return await page.evaluate(async ({access,contract})=>{const r=await fetch('/v1/intents',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+access},body:JSON.stringify(contract)});return {status:r.status};},{access,contract:" + json.dumps(authorized) + "}); }")
        observations["authorized_write"] = {"before": before, "after": client.snapshot(), "intent_id": authorized["intent_id"], **result}
        checkpoint()
        cli("tab-new", fixture_origin)
        snapshot("same-site-fixture")
        for label, path, payload, preflight in (("same-site-intent", "/v1/intents", contract, False),
                                              ("same-site-logout", "/v1/session/logout", {}, False),
                                              ("preflight-restore", "/v1/session/restore", {}, True)):
            before = client.snapshot()
            options = {"method": "POST", "mode": "cors" if preflight else "no-cors", "credentials": "include",
                       "headers": {"Content-Type": "application/json", "X-SIQ-Session": "1"} if preflight else {"Content-Type": "text/plain"},
                       "body": json.dumps(payload)}
            result = evaluate("async page => await page.evaluate(async ({url,options})=>{try{const r=await fetch(url,options);return {type:r.type,status:r.status};}catch(e){return {error:e.name};}}," + json.dumps({"url": h.endpoint + path + "?probe=" + label, "options": options}) + ")")
            observations["attacks"][label] = {"before": before, "after": client.snapshot(), "browser_result": result}
            checkpoint()
        cli("goto", fixture_origin.replace("127.0.0.1", "localhost"))
        snapshot("cross-site-fixture")
        before = client.snapshot()
        options = {"method": "POST", "mode": "no-cors", "credentials": "include", "headers": {"Content-Type": "text/plain"}, "body": json.dumps(contract)}
        result = evaluate("async page => await page.evaluate(async ({url,options})=>{try{const r=await fetch(url,options);return {type:r.type,status:r.status};}catch(e){return {error:e.name};}}," + json.dumps({"url": h.endpoint + "/v1/intents?probe=cross-site-intent", "options": options}) + ")")
        observations["attacks"]["cross-site-intent"] = {"before": before, "after": client.snapshot(), "browser_result": result}
        cli("screenshot", "--filename=cross-site-fixture.png")
        checkpoint()
        cli("tab-select", "0")
        cli("reload")
        s = state("after_attack")
        observations["after_attack_storage"] = storage()
        cli("click", ref(s, "退出"))
        state("logged_out", True)
        observations["logged_out_storage"] = storage()
        cli("screenshot", "--filename=logged-out.png")
        cli("reload")
        state("logout_reloaded", True)
        checkpoint()
    finally:
        try:
            checkpoint()
        except Exception as exc:  # noqa: BLE001 -- retain earlier checkpoints if browser died
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
