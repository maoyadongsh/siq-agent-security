# Enterprise Linux user setup orchestration v1

`setup-enterprise` combines existing gates without weakening them: current
explicitly confirmed plan -> pinned signed staging/reverification -> register
with expected environment OR recover existing pending identity OR reuse matching
registered identity -> persist discovery consent -> install user service.
Only explicit --start enables/starts the service; default configures only.
Only user service mode is supported; system mode must be rejected, not downgraded.

Plan digest, expected tenant/environment/origin and actual architecture are checked
before orchestration. Conflicting/unreadable local identity fails before staging.
First registration requires --enrollment-code-stdin; pending recovery never creates
a new identity or reads a new enrollment code. Recovery uses original signature
identity/credential journal and original window. No retry drops an environment,
consent, signature or TLS requirement. --resume-stage uses verified prior staging.

Progress is NDJSON: phase/status/optional stage_path only. A staged record is
emitted before registration so a caller can resume after later failure. Stop at
the first failed step, fixed error names the phase without underlying content.
Output failure stops later work. Partial private files and identities remain;
no rollback, recursive cleanup or deletion. Caller must retain stage_path.
Final configured_only/service_active_only is not heartbeat, inventory or protection.

Cancellation is checked before preparation and between every subsequent phase.
Already completed phases retain progress and resume paths; cancellation never
starts the next identity/consent/service phase. In-flight staging may finish its
bounded file work before cancellation is observed; no atomic rollback is claimed.
Waiting for a stdin enrollment code is cancellable without closing the caller's
stream. Its reader may remain blocked until process exit/input closes; this helper
is for the terminating CLI, not a long-running daemon input loop.

This consolidates commands but does not yet implement package download, graphical
scope preview, automatic framework selection, first-scan scheduling or full update
and uninstall lifecycle. Final user UX and production signed full-run validation
remain pending; mocked orchestration tests are not publisher/systemd acceptance.
