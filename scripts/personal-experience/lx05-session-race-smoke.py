#!/usr/bin/env python3
"""Exercise embedded-console session races against a real isolated daemon.

The browser delays an actual old /v1/status request until after sign-out and
re-pairing. Its 401 must not invalidate the new admin session. A second pass
dispatches two same-tick form submits and requires a single pairing request.
No API response, bearer or pairing code is fabricated or written to evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("lx05_b04_harness", HERE / "closure-b04-expiry-seed-runner.py")
b04 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = b04
spec.loader.exec_module(b04)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pair_code(harness) -> str:
    output = harness.command([str(harness.binary), "pair", "--port", str(harness.port)])
    found = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", output)
    require(found is not None, "pair CLI did not return a valid code")
    return found.group(0)


def pair_browser(page, harness, *, double_submit: bool = False) -> None:
    page.get_by_label("配对码", exact=True).fill(pair_code(harness))
    if double_submit:
        page.evaluate("""() => {
          const form = document.querySelector('form.login-form');
          for (let i = 0; i < 2; i++)
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }""")
    else:
        page.get_by_role("button", name="建立管理会话", exact=True).click()
    expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible(timeout=6000)


FETCH_HOOK = """(() => {
  window.__siqRace = { hold: false, pending: false, done: false, status: 0,
                       release: null, pairPosts: 0 };
  const original = window.fetch;
  window.fetch = async function(input, options) {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.pathname === '/v1/pair') window.__siqRace.pairPosts++;
    if (url.pathname === '/v1/status' && window.__siqRace.hold) {
      window.__siqRace.hold = false;
      window.__siqRace.pending = true;
      await new Promise(resolve => { window.__siqRace.release = resolve; });
      const response = await original.call(this, input, options);
      window.__siqRace.status = response.status;
      window.__siqRace.done = true;
      return response;
    }
    return original.call(this, input, options);
  };
})()"""


def run(args) -> dict:
    os.umask(0o077)
    binary, out = args.binary.resolve(), args.out.resolve()
    require(binary.is_file(), "candidate binary missing")
    require(out.parent.name.endswith("-private"), "report must be stored in *-private/")
    require(not out.exists(), "refusing to overwrite an earlier result")
    out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    root = out.parent / ("session-race-run-" + uuid.uuid4().hex)
    root.mkdir(mode=0o700)
    shutil.copy2(binary, root / "siq-agent-security")
    harness = b04.B04Harness(root, argparse.Namespace(port=None))
    report = {
        "schema_version": "linux-lx05-session-race/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "candidate_sha256": digest(binary),
        "driver_sha256": digest(Path(__file__)),
        "checks": [], "passed": False,
    }
    try:
        harness.start()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                report["browser_version"] = browser.version
                context = browser.new_context(locale="zh-CN")
                context.add_init_script(FETCH_HOOK)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda _error: errors.append("pageerror"))
                page.goto(harness.endpoint + "/overview")
                pair_browser(page, harness)

                page.evaluate("window.__siqRace.hold = true")
                page.get_by_role("button", name="刷新", exact=True).click()
                page.wait_for_function("window.__siqRace.pending === true", timeout=4000)
                page.get_by_role("button", name="退出管理", exact=True).click()
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                pair_browser(page, harness)
                page.evaluate("window.__siqRace.release()")
                page.wait_for_function("window.__siqRace.done === true", timeout=4000)
                status = page.evaluate("window.__siqRace.status")
                require(status == 401, "old bearer was not rejected by real daemon")
                # Observe the actual settled UI state, then issue a fresh admin
                # request. A stale 401 on the old client would return to pairing.
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                page.get_by_role("button", name="刷新", exact=True).click()
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                require(not errors, "browser script error after stale 401")
                report["checks"].append({"id": "old_401_preserves_new_session", "status": "pass",
                                         "old_http_status": status})

                page.get_by_role("button", name="退出管理", exact=True).click()
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                before = page.evaluate("window.__siqRace.pairPosts")
                pair_browser(page, harness, double_submit=True)
                after = page.evaluate("window.__siqRace.pairPosts")
                require(after - before == 1, "same-tick pairing submit sent multiple requests")
                require(not errors, "browser script error after duplicate submit")
                report["checks"].append({"id": "duplicate_pair_submit_single_request", "status": "pass",
                                         "request_count": after - before})
                context.close()
            finally:
                browser.close()
        report["passed"] = True
    except Exception as error:  # noqa: BLE001 -- private report stores type, not message or DOM
        report["failure_type"] = type(error).__name__
        raise
    finally:
        harness.stop()
        shutil.rmtree(root)
        with out.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    result = run(parser.parse_args())
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}))


if __name__ == "__main__":
    main()
