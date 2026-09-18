# R07 — full user journey: browser console × real daemon × real OpenClaw host

- Date: 2026-09-15
- Script: `scripts/personal-experience/r07-linux-user-journey-smoke.py` (sha256 e987865aaa9d0ec9caf23c50a595935dceaedf0f61938bf8992f9b0d3c95da5d)
- Binary: batch candidate `agentshield` sha256 15d688fdd4652e9efb544ece769142b60725bc0a5d2deae233062f6b910e0701 (copied per run, never rebuilt; the embedded-UI binary must not change — product-fix rewrites were rejected in favour of honest test-flow fixes)
- Host: real OpenClaw 2026.5.12 via Node v22.22.1, Linux 6.17.0-1014-nvidia (aarch64); headless Chromium (Playwright) drives the embedded console UI
- Result: **pass — 23/23 journey checks + nested L2 leg 29/29 (UP01–UP10)**, run 19 exit code 0
- Structured results: `r07-linux-user-journey.json`
- Attribution level: `controlled_session` (inherited from the L2 leg; no per-task tool causality is claimable)

## Journey coverage (12 steps → 23 checks, all pass)

| Journey step | Checks (all pass) |
|---|---|
| 0. Fresh-daemon default (pre-activation, API level) | r07_step10a_raw_content_store_default_disabled — status=disabled, default_capture=false, activation=404, asserted BEFORE the managed fixture chain opts the store in |
| 1. Daemon health | r07_step1_daemon_health_paired |
| 2. UI pairing incl. wrong-code retry; agent discovery | r07_step2_ui_pairing_with_wrong_code_retry, r07_step2_ui_bindings_discovers_openclaw |
| 3. Confirm access (grants) | r07_step3_ui_grants_shows_v1_grant |
| 4. Real host allowed action with attribution | r07_step4_sec_issued_for_real_session, r07_step4_allow_read_with_session_attribution, r07_step4_call_binding_recomputed, r07_step4_attribution_correlates_grant_install_sec |
| 5. Overreach denied fail-closed + UI receipts consistency | r07_step5_missing_authority_denied_fail_closed, r07_step5_ui_receipts_consistent_with_deny |
| 6. Approval hold lands in SIQ → UI approve → replay 409 | r07_step6_hold_lands_in_siq_confirmations, r07_step6_ui_approval_records_confirmation, r07_step6_replayed_approval_rejected |
| 7. Nested L2 leg: V1 → cancel → confirm update V2 → re-authorize → removal | r07_step7_update_leg_v1_cancel_confirm_v2_remove (plus the full nested 29-check r04 leg reported under `nested_legs`) |
| 8. Interrupt service; UI session invalidation + repair | r07_step8_interrupt_invalidates_ui_session, r07_step8_retry_and_keyboard_repair |
| 9. Receipts/activities render after recovery | r07_step9_receipts_activities_render_after_recovery |
| 10. Raw-content opt-in state honesty + purge semantics | r07_step10_raw_content_opt_in_ui_and_per_task_gating, r07_step10_raw_content_purge_expired_only |
| 11. Mobile viewport; adapter uninstall preserves host config | r07_step11_mobile_confirmations_usable, r07_step11_adapter_uninstall_preserves_host_config |
| 12. Logout returns console to pairing | r07_step12_logout_ends_session |

## Step-10 root cause and honest fix (runs 14–17)

The journey originally expected the raw-content store to be OFF in settings
(`原文记录关闭。` + enable form). That expectation was untestable inside this
journey: the inherited managed-fixture `setup_authority()`
(`openclaw-managed-native-smoke.py`) POSTs `/v1/raw-task-content/activation`
(actor `automated-fixture-operator`, retention 1 h, budget 16 MiB) BEFORE the
browser journey, so the nested L2 leg can do per-task native captures. The
activation is one-way (no deactivate API; only `/v1/raw-task-content/purge-expired`
removes records). Run 16's dump matched this exactly (1 小时 / 16 MiB / the
journey-start timestamp). Not a product defect.

Fix (test-side, no boundary lowered — it tests MORE than before):

1. `r07_step10a_raw_content_store_default_disabled` asserts the store default at
   API level on the FRESH daemon, before `setup_authority()` runs: `status=disabled`,
   `default_capture=false`, activation record absent (404).
2. Step 10 rewritten to assert the real opted-in state honestly: ready panel with
   默认采集仍为关闭， topbar 原文仓已启用 · 按任务授权， the activation's limits
   (1 小时 / 16 MiB), and the purge flow (仅删除已到期独立密文； 任务回执和追溯记录未改动).

## Step-11b root cause (runs 14–18) — test-flow defect, not a product defect

Symptom: AdapterChangeDialog stuck on 正在检查配置并准备变更清单…, 确认应用
disabled forever, no error text.

Diagnostic chain (instrumentation added to `debug_dump` in run 18, kept):

1. JS-side fetch hook (`window.__fetchLog`, added via `add_init_script`) —
   necessary because the Playwright response listener demonstrably misses
   completed responses (the run 17 network log lacked `/v1/adapter/instances`
   although the catalog rendered).
2. Daemon stdout/stderr captured into the dump while the harness is alive, plus
   harness-token probes (`/v1/adapter/status`, `/v1/adapter/instances`) — the
   probes answered 200 with the EXPECTED post-r04-removal diagnosis
   (instance_authority fail), proving the daemon and admin session were healthy.
3. The fetch log showed exactly ONE `200 /v1/adapter/preview` and NO second
   preview fetch and NO client-side ERR line.

Conclusion: the 卸载 button opens the dialog already in uninstall mode
(`BindingsPage` passes `action: 'uninstall'`), so the dialog-open preview IS the
uninstall preview. The test's redundant `select_option("uninstall")` re-selected
the same value; Playwright still fires `change`, the dialog's onChange
unconditionally clears the plan and re-enters loading, but `action` — the
preview effect's dependency — does not change, so no re-preview ever runs.
Runs 14/16/17/18 all hit this. A real user cannot trigger it (a native select
does not fire change when the value is unchanged), so this was fixed in the
test flow (select only when the value differs), not in the product.

## Mount-race finding (product gap, recorded — deliberately not fixed in this batch)

Every guarded console page except BindingsPage lacks a `[guard]` reload
dependency: a page that mounts while App boot is still resolving `/v1/status`
has its in-flight load superseded when the load guard is recreated, leaving the
list stuck on 加载中…. The journey works around this with `goto_until`
(remount until the load wins the race, 9 call sites + post-mortem dump). This
is a real (low-severity) product race worth a product-side fix in a later batch;
the workaround does not mask any acceptance criterion here.

## Debugging-session evidence kept (redacted)

- `commands.txt` — run inventory; redacted stderr tails of failed runs 17/18;
  run 18 phase-c probe/fetch-log extracts; redaction scan results.
- Failed samples are kept, not deleted; the final pass was achieved by fixing
  the test flow, never by loosening an expectation.

## Limitations (honest boundaries)

1. The browser operator is automated (Playwright); UI journeys are not human acceptance.
2. OS desktop notifications are not exercised headlessly; covered by the dedicated notification smokes (R02).
3. Step 5 exercises missing-authority (no SEC) overreach; permission-scope overreach inside the granted read scope is not constructible at this fixture level because the host config restricts OpenClaw to the read tool.
4. Session-level attribution only (`controlled_session`).
5. Local deterministic model and synthetic operator; no external or paid model.
6. The Playwright response listener was shown to be lossy in this environment; page-side fetch outcomes are now recorded by the JS hook, and journey evidence relies on the latter for fetch forensics.

## Files

- `r07-linux-user-journey.json` — structured per-check results (23 pass), nested r04 leg (29 pass, UP01–UP10), binary/harness sha256, limitations
- `commands.txt` — commands, exit codes, failed-run tails (redacted), phase-c diagnostic extracts
- `identity.txt` — binary/script digests, toolchain versions, copy policy
- `SHA256SUMS` — digests of all files in this directory
