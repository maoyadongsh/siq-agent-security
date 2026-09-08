#!/usr/bin/env python3
"""Exercise the existing local SPA against a fresh, explicit test-mode profile."""

import argparse
import json
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads((args.state_dir / "service.json").read_text())
    if state["mode"] != "test":
        raise ValueError("deterministic browser assertions require explicit fixture model")
    launch = json.loads((args.state_dir / "service.log").read_text().splitlines()[0])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    outcomes = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(state["endpoint"] + "/demo")
        page.get_by_label("配对码", exact=True).fill("invalid-pairing-code")
        page.get_by_role("button", name="连接", exact=True).click()
        page.get_by_role("alert").filter(has_text="pairing_invalid").wait_for()
        page.wait_for_timeout(1700)  # successful polling must not erase action errors
        if "pairing_invalid" not in page.get_by_role("alert").inner_text():
            raise ValueError("pairing failure disappeared during polling")
        page.get_by_label("配对码", exact=True).fill(launch["pairing_code"])
        page.get_by_role("button", name="连接", exact=True).click()
        for scenario, label, status, count in (("normal", "正常交付", "verified", 1),
                ("research-only", "只分析，不保存或发送", "researched", 0),
                ("research-report", "分析并保存报告", "verified", 0),
                ("mcp-attack", "MCP 收件人注入", "blocked", 0), ("same-value", "同值不同来源", "blocked", 0),
                ("fake-success", "工具伪成功", "incomplete", 0), ("conflicting", "交付内容冲突", "conflicting", 1),
                ("approval", "人工审批与进程校验", "verified", 1),
                ("trifecta", "机密文件与不可信网页出网拦截", "blocked", 0)):
            page.get_by_label("场景", exact=True).select_option(scenario)
            page.get_by_role("button", name="开始任务", exact=True).click()
            if scenario == "approval":
                page.get_by_role("button", name="批准本次校验", exact=True).wait_for(timeout=30000)
                page.screenshot(path=str(args.out_dir / "approval-held.png"), full_page=True)
                page.get_by_role("button", name="批准本次校验", exact=True).click()
            page.wait_for_function("expected => document.querySelector('select[aria-label=\"查看任务\"]')?.selectedOptions[0]?.textContent.includes(expected)",
                                   arg=label + " · " + status, timeout=30000)
            page.get_by_text("受控接收端实际消息：" + str(count), exact=True).wait_for()
            expected_skills = ["secure-research", "secure-report", "secure-delivery"][:
                {"research-only": 1, "research-report": 2}.get(scenario, 3)]
            actual_skills = page.locator('[data-selected-skill]').evaluate_all(
                'nodes => nodes.map(node => node.dataset.selectedSkill)')
            if actual_skills != expected_skills:
                raise ValueError("actual selected task Skills missing")
            if page.locator(f'[data-state="{status}"]').count() == 0:
                raise ValueError("missing expected task state")
            if scenario == "fake-success" and page.locator('[data-state="verified"]').count() != 1:
                raise ValueError("tool success falsely marked task/delivery verified")
            if scenario == "fake-success":
                summary = page.locator('.demo-effect-summary').inner_text()
                if not all(value in summary for value in ('success', 'missing', 'INCOMPLETE')):
                    raise ValueError("actual tool report and missing effect were not shown separately")
            source = "MCP" if scenario in ("mcp-attack", "same-value") else "TRUSTED_DATABASE"
            provenance = page.locator(f'[data-provenance="{source}"]').filter(has_text="收件人来源")
            if scenario == "trifecta":
                source = None
                states = page.locator('[data-trifecta="decision"]').all_inner_texts()
                if states != [
                    "SIQ 决策时状态：机密数据 true · 不可信输入 false · 出网 false",
                    "SIQ 决策时状态：机密数据 true · 不可信输入 false · 出网 true",
                    "SIQ 决策时状态：机密数据 true · 不可信输入 true · 出网 true"]:
                    raise ValueError("missing stateful trifecta sequence")
                if "lethal_trifecta" not in page.locator('.demo-actions').inner_text():
                    raise ValueError("missing SIQ trifecta denial")
            elif scenario not in ("research-only", "research-report"):
                provenance.wait_for()
            else:
                source = None
            if scenario == "same-value" and "值与受信联系人相同" not in provenance.inner_text():
                raise ValueError("same-value provenance distinction missing")
            if scenario == "mcp-attack" and "值与受信联系人不同" not in provenance.inner_text():
                raise ValueError("recipient substitution explanation missing")
            page.screenshot(path=str(args.out_dir / (scenario + ".png")), full_page=True)
            outcomes.append({"scenario": scenario, "task_status": status, "messages": count,
                             "recipient_source": source, "selected_skills": actual_skills})
        opener = build_opener(ProxyHandler({}))
        request = Request(state["endpoint"] + "/hackathon/v1/pairing/renew", data=b"{}", headers={
            "Authorization": "Bearer " + state["token"], "Content-Type": "application/json", "X-SIQ-Demo": "1"})
        with opener.open(request, timeout=5) as response:
            renewed = json.load(response)
        second = browser.new_context(viewport={"width": 1440, "height": 1000})
        reconnect = second.new_page()
        reconnect.goto(state["endpoint"] + "/demo")
        reconnect.get_by_label("配对码", exact=True).fill(renewed["pairing_code"])
        reconnect.get_by_role("button", name="连接", exact=True).click()
        reconnect.get_by_label("查看任务", exact=True).wait_for()
        if reconnect.locator('select[aria-label="查看任务"] option').count() != len(outcomes):
            raise ValueError("renewed pairing lost task history")
        if page.locator('select[aria-label="查看任务"] option').count() != len(outcomes):
            raise ValueError("renewal invalidated existing session")
        for session in (context, second):
            snapshot = session.request.get(state["endpoint"] + "/hackathon/v1/tasks")
            if snapshot.status != 200 or len(snapshot.json()["tasks"]) != len(outcomes):
                raise ValueError("renewed/existing cookie cannot read task history")
        second.close()
        page.set_viewport_size({"width": 390, "height": 844})
        if not page.evaluate("document.documentElement.scrollWidth <= innerWidth"):
            raise ValueError("mobile horizontal overflow")
        page.screenshot(path=str(args.out_dir / "mobile.png"), full_page=True)
        keys = page.evaluate("Object.keys(localStorage)")
        private_cookie = all(cookie["httpOnly"] for cookie in context.cookies())
        if errors or keys or not private_cookie:
            raise ValueError("browser error or credential storage failure")
        browser.close()
    result = {"schema_version": "hackathon-browser-smoke/v1", "provider": "fixture", "cases": outcomes,
              "page_errors": errors, "local_storage_keys": keys, "cookie_http_only": private_cookie,
              "mobile_no_horizontal_overflow": True, "pairing_error_persists": True,
              "renewed_pairing_preserves_history_and_session": True}
    (args.out_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
