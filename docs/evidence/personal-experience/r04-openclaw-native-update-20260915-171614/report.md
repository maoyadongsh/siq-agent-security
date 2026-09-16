# R04 — OpenClaw real-host Skill V1 → cancel → confirm update V2 → re-authorize → safe removal

- Date: 2026-09-15
- Script: `scripts/personal-experience/r04-openclaw-native-update-smoke.py` (sha256 a1f6a904c23d61cd3be82c4e4e11955d4d0f00a9566e47c357f26767b038d22a)
- Binary: batch candidate `agentshield` sha256 15d688fdd4652e9efb544ece769142b60725bc0a5d2deae233062f6b910e0701 (copied, never rebuilt)
- Host: real OpenClaw 2026.5.12 via `openclaw agent --local` on Node v22.22.1, Linux 6.17.0-1014-nvidia
- Result: **pass — 29/29 checks**, run exit code 0
- Structured results: `r04-openclaw-native-update.json`
- Attribution level: `controlled_session` throughout (OpenClaw exposes no trustworthy per-task Skill tool-causality field → `controlled_task` is NOT claimed)

## Journey coverage

| Journey step | Checks (all pass) |
|---|---|
| 1–2. V1 harmless skill, import/compare/confirm/install, authorize, attach | missing_sec_denied_before_v1_read, v1_native_read_allowed_with_verified_session_attribution, v1_call_binding_recomputed, v1_attribution_correlates_grant_install_sec |
| 3. Real OpenClaw tool path reads V1 data with attribution correlation | (covered by the four checks above: real hook → decision receipt → SEC → grant → install digest correlation) |
| 4. Import V2, cancel; V1 unchanged | up01_import_generates_check_data_only, comparison_requires_confirmation_with_content_and_permission_diff, comparison_is_read_only, up02_cancel_and_repeated_requests_keep_v1 |
| 5. Confirm update → V1 authority invalidated; V2 gains nothing automatically | up06_user_modified_target_not_silently_overwritten, prepared_update_leaves_v1_in_place_before_confirmation, up04_new_permissions_require_fresh_confirmation, up03_candidate_drift_after_approval_refused, up08_commit_after_daemon_restart_from_recorded_plan, update_replaces_target_bytes, update_revokes_v1_grant, v1_runtime_identity_becomes_unavailable, up09_old_context_cannot_authorize_new_version |
| 6. Re-authorize/bind V2, real host loads V2, executed content matches new digest | v2_activation_identity_and_adapter_rebind, v2_new_session_pre_sec_denied, v2_native_read_allowed_with_new_sec, v2_loaded_in_native_catalog |
| 7. Safe removal; unknown user files preserved | removal_revokes_authority_and_removes_target, v2_identity_survives_nothing_after_removal, unknown_user_files_preserved, host_config_final_state_preserved, receipt_chain_verified |

## UP01–UP10 negative/concurrent acceptance

| ID | Result | Mechanism exercised |
|---|---|---|
| UP01 | pass | V2 import produces only check/scheduling data; operations count, identity set, grant revision and target bytes all unchanged; V2 not in catalog; removal not_requested |
| UP02 | pass | Cancel + duplicate comparison requests keep V1 running with the original SEC; no second update side effect |
| UP03 | pass | Commit with tampered plan_signature refused after approval (no TOCTOU window) |
| UP04 | pass | patch-desired after approval refused ("only allowed in pending_approval"); V1's confirmation cannot widen permissions |
| UP05 | partial | Stale-binding refusals exercised; two live operators racing is out of scope at this interface |
| UP06 | pass | User-edited install target detected before commit; update refused, user bytes restored; not silently overwritten |
| UP07 | pass | Candidate mutated after import → stale digest → permission issuance refused |
| UP08 | pass | Daemon restart between plan preparation and commit; recorded plan accepted, commit succeeds |
| UP09 | pass | Old-session SEC on V2: hook fail-closes locally before attribution ("instance session could not be verified"), no decision receipt, no content leak (observed, receipts unchanged); additionally the product structurally forbids re-binding an enrolled session to a new runtime identity |
| UP10 | pass (observed evidence level) | Source directory removed → re-comparison either refuses or proceeds safely;失效来源不改安装与权限 |

## Key product property recorded as evidence

`runtimeidentity.Store.Enroll` refuses to switch an already-bound session to a
new runtime identity, and SEC issuance requires a per-grant session binding.
After the V2 update the pre-update session can therefore never be re-bound.
The post-update journey uses an explicit **new OpenClaw session**
(`openclaw agent --session-id …`) — a supported CLI path, not a manual
production-state replacement. Effective session ids are OpenClaw-namespaced
(`agent:<agent>:explicit:<id>`); the SEC is issued against the effective id
taken from the real decision receipt. Failed attempts proving this chain are
kept in `failed-run14…15.stderr`.

## Limitations (honest boundaries)

1. Local deterministic model fixture and synthetic operator; no external/paid model.
2. Candidate V2 is an explicitly imported local directory; public-network scheduled fetch is a separate chain (does not close J6).
3. Session-level attribution only (`controlled_session`); same-UID compromise and OS sandbox isolation remain outside the SEC threat boundary.
4. UP05 covers stale-binding refusals, not two live operators racing; UP10 records the product's chosen safe behaviour (observed level).
5. Update flows here are local-dir journeys; production Git obeys R03 and is unchanged.

## Files

- `r04-openclaw-native-update.json` — structured per-check results (29 pass), up_coverage, install/content digests, receipt count, limitations
- `commands.txt` — commands, exit codes, failed-run inventory, redaction scan result
- `identity.txt` — sha256 of binary + script, node/kernel versions
- `failed-run13…15.stderr` — retained redacted failure samples (never deleted to claim all-green)
