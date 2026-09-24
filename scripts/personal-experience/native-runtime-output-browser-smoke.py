#!/usr/bin/env python3
"""Real native framework hooks to encrypted output and paired browser; no model."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import expect, sync_playwright

from background_setup_harness import BackgroundSetupMixin, fixture_directory

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "fixture", ROOT / "scripts/validate-intent-v2-hermes.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def file_ref(path):
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


class OpenClawHarness(fixture.Harness):
    platform = "openclaw"
    read_tool = "read"
    write_tool = "write"

    def __init__(self, root, args):
        super().__init__(root, args)
        self.oc = Path(self.env["HOME"]) / ".openclaw"
        self.oc.mkdir()
        self.native_metadata = None
        self.env.update(
            {
                "OPENCLAW_STATE_DIR": str(self.oc),
                "OPENCLAW_CONFIG_PATH": str(self.oc / "openclaw.json"),
                "OPENCLAW_DISABLE_BUNDLED_PLUGINS": "1",
            }
        )
        (self.oc / "openclaw.json").write_text(
            json.dumps({"plugins": {"slots": {"memory": "none"}}})
        )

    def native(self, calls):
        spec_path, result = self.root / "oc-input.json", self.root / "oc-result.json"
        result.unlink(missing_ok=True)
        # Keep one routing key across two host UUID epochs: reset must not reuse
        # the preceding session's capture grant or activity output.
        native_calls = [
            {
                **call,
                "session_id": "agent:fixture:shared-routing-key",
                "session_epoch": call["session_id"],
            }
            for call in calls
        ]
        spec_path.write_text(
            json.dumps(
                {
                    "openclaw_root": str(self.args.openclaw_root),
                    "workspace": str(self.workspace),
                    "calls": native_calls,
                    "agent_id": "fixture",
                    "result_path": str(result),
                }
            )
        )
        self.command(
            [
                str(self.args.node),
                str(ROOT / "scripts/openclaw-native-worker.mjs"),
                str(spec_path),
            ]
        )
        payload = json.loads(result.read_text())
        self.native_metadata = {
            key: value for key, value in payload.items() if key != "outputs"
        }
        return payload["outputs"]


class BackgroundHermesHarness(BackgroundSetupMixin, fixture.Harness):
    pass


class BackgroundOpenClawHarness(BackgroundSetupMixin, OpenClawHarness):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--platform", choices=["hermes", "openclaw"], default="hermes")
    parser.add_argument("--hermes-root", type=Path)
    parser.add_argument("--openclaw-root", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--background-service", action="store_true", help="use real isolated systemd setup/teardown, never direct serve")
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    if args.platform == "hermes" and not args.hermes_root:
        parser.error("Hermes requires --hermes-root")
    if args.platform == "openclaw" and not (args.openclaw_root and args.node):
        parser.error("OpenClaw requires --openclaw-root and --node")
    args.hermes_root = (args.hermes_root or Path("/unused-hermes-root")).resolve()
    if args.openclaw_root:
        args.openclaw_root = args.openclaw_root.resolve()
        args.node = args.node.resolve()
    args.hermes_python = args.hermes_root / ".venv/bin/python"
    args.hermes_cli = args.hermes_root / ".venv/bin/hermes"
    args.installer_managed_profile = True
    args.out_dir.mkdir(parents=True, exist_ok=False)
    checks, failure = {}, None
    runtime_files = (
        [
            args.hermes_cli,
            args.hermes_root / "model_tools.py",
            args.hermes_root / "hermes_cli/plugins.py",
            ROOT / "adapters/runtime/hermes-agentshield/__init__.py",
        ]
        if args.platform == "hermes"
        else [
            args.node,
            args.openclaw_root / "package.json",
            ROOT / "scripts/openclaw-native-worker.mjs",
            ROOT / "adapters/runtime/openclaw-agentshield/index.ts",
        ]
    )
    artifacts = [
        file_ref(path)
        for path in [
            args.binary,
            Path(__file__).resolve(),
            ROOT / "scripts/validate-intent-v2-hermes.py",
            ROOT / "scripts/personal-experience/background_setup_harness.py",
            ROOT / "scripts/personal-experience/installed_user_service_driver.py",
            *runtime_files,
        ]
    ]
    native_metadata = None
    service_checks = {}
    setup_seconds = None
    cleanup = {"safe": False}
    try:
        with fixture_directory(args, cleanup) as raw:
            harness_type = fixture.Harness if args.platform == "hermes" else OpenClawHarness
            if args.background_service:
                harness_type = BackgroundHermesHarness if args.platform == "hermes" else BackgroundOpenClawHarness
            h = harness_type(
                Path(raw), args
            )
            shutil.copy2(args.binary, h.binary)
            try:
                h.start()
                target = next(
                    i
                    for i in h.api("/v1/adapter/instances?platform=" + args.platform)[
                        "instances"
                    ]
                    if (i["name"] == "work" if args.background_service and args.platform == "hermes" else i["active"])
                )
                agent = "hri-" + target["instance_id"][3:]
                skill = Path(raw) / "output-skill"
                skill.mkdir()
                (skill / "SKILL.md").write_text(
                    f"---\nname: output-fixture\ndescription: Read synthetic output.\nallowed-tools: {h.read_tool}\n---\nRead an approved fixture.\n"
                )
                admission = h.api("/v1/admit", {"path": str(skill)})["admission"]
                grant = h.api(
                    "/v1/grants",
                    {
                        "admission_id": admission["admission_id"],
                        "platform": args.platform,
                        "subject_id": agent,
                        "subject_type": "agent_instance",
                        "redact_secrets": True,
                    },
                )
                grant_path = "/v1/grants/" + grant["grant"]["grant_id"]

                def action(name, **extra):
                    nonlocal grant
                    response = h.api(
                        grant_path + "/" + name,
                        {
                            "expected_revision": grant["state_revision"],
                            "actor_id": "fixture-human",
                            **extra,
                        },
                    )
                    grant = h.api(grant_path)
                    return response

                action(
                    "patch-desired",
                    tools=[h.read_tool],
                    filesystem={"read_only": [str(h.workspace)], "read_write": []},
                )
                for index, conflict in enumerate(grant["grant"]["overlap_conflicts"]):
                    if conflict["resolution"] == "unresolved":
                        action("resolve-overlap", index=index)
                challenge = action("challenge")["challenge"]
                action(
                    "approve",
                    challenge_id=challenge["challenge_id"],
                    nonce=challenge["nonce"],
                )
                action("deploy")
                issued = h.api(
                    "/v1/runtime-identities",
                    {
                        "schema_version": "local-runtime-identity-create/v1",
                        "instance_id": target["instance_id"],
                        "grant_id": grant["grant"]["grant_id"],
                        "expected_grant_revision": grant["state_revision"],
                        "actor_id": "fixture-human",
                        "session_ttl_seconds": 600,
                    },
                    expected=201,
                )
                identity = issued["identity"]["identity_id"]
                plan = h.api(
                    "/v1/adapter/preview",
                    {
                        "platform": args.platform,
                        "action": "install",
                        "instance_id": target["instance_id"],
                        "runtime_identity_id": identity,
                        **(
                            {"native_enable": True} if args.platform == "hermes" else {}
                        ),
                    },
                )
                assert (
                    plan["schema_version"] == "local-adapter-plan/v3"
                    and plan["runtime_verified"] is False
                )
                h.api(
                    "/v1/adapter/install",
                    {
                        "platform": args.platform,
                        "instance_id": target["instance_id"],
                        "runtime_identity_id": identity,
                        "plan_id": plan["plan_id"],
                        "plan_digest": plan["plan_digest"],
                        "actor_id": "fixture-human",
                    },
                )
                if args.platform == "hermes":
                    profile = Path(h.env["HERMES_HOME"])
                    installed = profile / "plugins/siq-agent-security/__init__.py"
                    assert (
                        installed.read_bytes()
                        == (
                            ROOT / "adapters/runtime/hermes-agentshield/__init__.py"
                        ).read_bytes()
                    )
                    assert (
                        "fixture_setting: retain"
                        in (profile / "config.yaml").read_text()
                    )
                else:
                    installed = h.oc / "plugins/siq-agent-security/index.ts"
                    assert (
                        installed.read_bytes()
                        == (
                            ROOT / "adapters/runtime/openclaw-agentshield/index.ts"
                        ).read_bytes()
                    )
                    assert (
                        json.loads((h.oc / "openclaw.json").read_text())["plugins"][
                            "slots"
                        ]["memory"]
                        == "none"
                    )
                assert (
                    Path(raw) / "hermes/config.yaml"
                ).read_text() == "fixture_default: unchanged\n"
                checks["managed_native_install_preserves_unrelated_configuration"] = (
                    True
                )
                marker = (
                    "SYNTHETIC_NATIVE_"
                    + args.platform.upper()
                    + "_OUTPUT <script>window.nativeOutputInjected=true</script>"
                )
                (h.workspace / "company-a/report.txt").write_text(marker + "\n")
                native_session = "11111111-1111-4111-8111-111111111111"
                results = h.native([h.read("before-capture", session=native_session)])
                assert marker in results[0]["result"]
                activities = h.api("/v1/task-activities?view=tasks")
                activity = next(i for i in activities["items"] if i["binding"])
                binding = activity["binding"]
                assert binding["agent_id"] == agent

                def output_list():
                    page = h.api("/v1/task-activities?view=tasks")
                    item = next(
                        i
                        for i in page["items"]
                        if i["binding"]
                        and i["binding"]["session_id"] == binding["session_id"]
                    )
                    query = urlencode({"view": "tasks", "snapshot": page["snapshot"]})
                    return h.api(
                        "/v1/task-activities/"
                        + item["activity_id"]
                        + "/outputs?"
                        + query
                    )

                assert output_list()["status"] == "disabled"
                checks["real_native_read_without_implicit_content_save"] = True
                h.api(
                    "/v1/raw-task-content/activation",
                    {
                        "schema_version": "local-raw-task-content-activate/v1",
                        "actor_id": "fixture-human",
                        "retention_seconds": 3600,
                        "budget_bytes": 64 << 20,
                    },
                    expected=201,
                )
                h.api(
                    "/v1/raw-task-content/grants",
                    {
                        "schema_version": "local-raw-task-content-grant-create/v1",
                        "task_id": binding["task_id"],
                        "kinds": ["output"],
                        "actor_id": "fixture-human",
                        "duration_seconds": 600,
                        "retention_seconds": 3600,
                        "max_plaintext_bytes": 16384,
                    },
                    expected=201,
                )
                assert output_list()["items"] == []
                checks["grant_does_not_backfill_previous_output"] = True
                results = h.native([h.read("captured-read", session=native_session)])
                assert marker in results[0]["result"]
                captured = output_list()["items"]
                assert len(captured) == 1 and captured[0]["kind"] == "output"
                checks["native_post_hook_captures_exactly_one_output"] = True
                other = h.native(
                    [
                        h.read(
                            "other-session",
                            session="22222222-2222-4222-8222-222222222222",
                        )
                    ]
                )
                assert marker in other[0]["result"]
                assert output_list()["items"] == captured
                other_page = h.api("/v1/task-activities?view=tasks")
                other_activity = next(
                    i
                    for i in other_page["items"]
                    if i["binding"]
                    and i["binding"]["session_id"] != binding["session_id"]
                )
                query = urlencode({"view": "tasks", "snapshot": other_page["snapshot"]})
                other_outputs = h.api(
                    "/v1/task-activities/"
                    + other_activity["activity_id"]
                    + "/outputs?"
                    + query
                )
                assert (
                    other_outputs["status"] == "ready" and other_outputs["items"] == []
                )
                checks[
                    "second_native_session_cannot_borrow_capture_grant_or_output"
                ] = True
                forbidden = h.workspace / "company-a/forbidden.txt"
                denied = h.native(
                    [
                        {
                            "id": "denied-write",
                            "tool": h.write_tool,
                            "session_id": native_session,
                            "params": {
                                "path": str(forbidden),
                                "content": "must-not-execute",
                            },
                        }
                    ]
                )
                assert (
                    "siq-agent-security" in denied[0]["result"]
                    and not forbidden.exists()
                )
                assert output_list()["items"] == captured
                checks["native_denied_write_not_executed_or_reported_as_output"] = True
                # Restart the actual daemon; retain encrypted records and signed identities.
                h.stop()
                h.start()
                assert output_list()["items"] == captured
                checks["daemon_restart_preserves_verified_native_output_source"] = True
                pairing = h.command(
                    [str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]]
                )
                code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1000}, locale="zh-CN"
                    )
                    errors, reads = [], []
                    page.on("pageerror", lambda _: errors.append("pageerror"))
                    page.on(
                        "request",
                        lambda r: reads.append(r.url)
                        if "/outputs/read?" in r.url
                        else None,
                    )
                    page.goto(h.endpoint + "/activities")
                    page.get_by_label("配对码", exact=True).fill(code)
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                    expect(
                        page.get_by_role("heading", name="运行记录", exact=True)
                    ).to_be_visible()
                    page.goto(h.endpoint + "/activities?task_id=" + binding["task_id"])
                    page.get_by_role("link", name="查看活动记录", exact=True).click()
                    panel = page.get_by_role(
                        "region", name="本次运行的已采集输出", exact=True
                    )
                    button = panel.get_by_role("button", name="查看输出 1", exact=True)
                    expect(button).to_be_visible()
                    assert not reads and marker not in page.locator("body").inner_text()
                    checks["native_output_page_lists_metadata_only"] = True
                    button.click()
                    dialog = page.get_by_role(
                        "dialog", name="查看已采集输出", exact=True
                    )
                    expect(
                        dialog.get_by_role("button", name="确认查看输出")
                    ).to_be_disabled()
                    dialog.get_by_role("checkbox").check()
                    dialog.get_by_role("button", name="确认查看输出").click()
                    expect(
                        dialog.get_by_role("region", name="本次运行输出正文")
                    ).to_contain_text(marker)
                    assert len(reads) == 1 and not page.evaluate(
                        "Boolean(window.nativeOutputInjected)"
                    )
                    checks["explicit_browser_read_matches_real_native_tool_result"] = (
                        True
                    )
                    expect(
                        dialog.get_by_role("heading", name="读取文件的输出", exact=True)
                    ).to_be_visible()
                    expect(
                        dialog.get_by_label("文件输出文本", exact=True)
                    ).to_have_text(
                        "1|" + marker + "\n2|"
                        if args.platform == "hermes"
                        else marker + "\n"
                    )
                    details = dialog.locator("details")
                    assert not details.evaluate("el => el.open")
                    details.locator("summary").click()
                    expect(
                        details.get_by_text(
                            "/tool/result"
                            if args.platform == "hermes"
                            else "/tool/result/content/0/text",
                            exact=True,
                        )
                    ).to_be_visible()
                    assert len(reads) == 1
                    details.locator("summary").click()
                    checks[
                        "readable_native_text_and_original_fields_without_extra_request"
                    ] = True
                    page.screenshot(
                        path=str(args.out_dir / "native-output-desktop.png"),
                        full_page=True,
                        animations="disabled",
                    )
                    page.set_viewport_size({"width": 375, "height": 812})
                    assert dialog.evaluate(
                        "(el) => el.scrollWidth <= el.clientWidth + 1"
                    )
                    expect(
                        dialog.get_by_role("button", name="关闭并清除")
                    ).to_be_visible()
                    page.screenshot(
                        path=str(args.out_dir / "native-output-mobile.png"),
                        full_page=True,
                        animations="disabled",
                    )
                    checks["mobile_output_wraps_and_close_is_available"] = True
                    dialog.get_by_role("button", name="关闭并清除").click()
                    expect(button).to_be_focused()
                    assert marker not in page.locator("body").inner_text()
                    page.reload()
                    expect(button).to_be_visible()
                    assert (
                        len(reads) == 1
                        and marker not in page.locator("body").inner_text()
                    )
                    assert marker not in page.evaluate(
                        "JSON.stringify({...localStorage,...sessionStorage})"
                    )
                    assert not errors
                    checks["close_reload_clear_native_plaintext_without_reread"] = True
                    browser.close()
            finally:
                native_metadata = getattr(h, "native_metadata", None)
                if args.background_service:
                    import sys
                    h.close(verify_reentry=sys.exc_info()[0] is None)
                    cleanup["safe"] = True
                    service_checks = h.service_checks
                    setup_seconds = h.setup_seconds
                else:
                    h.stop()
    except BaseException as exc:
        # Never write host logs, credentials, request bodies or browser DOM to evidence.
        failure = type(exc).__name__
        raise
    finally:
        result = {
            "schema_version": "siq.native-runtime-output-proof/v1",
            "passed": failure is None and bool(checks),
            "checks": checks,
            "failure": failure,
            "artifacts": artifacts,
            "platform": args.platform,
            "service_mode": "systemd_user_setup" if args.background_service else "direct_process",
            "service_checks": service_checks,
            "last_setup_seconds": setup_seconds,
            "native_metadata": native_metadata,
            "scope": "actual native loader/tool dispatch and installed hooks, paired daemon/browser; OpenClaw after relay invoked by harness; synthetic files, no model, no direct capture POST, no business config changes",
        }
        (args.out_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
