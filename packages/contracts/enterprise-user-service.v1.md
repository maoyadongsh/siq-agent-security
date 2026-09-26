# Enterprise Linux user service installation v1

`install-user-service --release FILE --stage DIR [--start]` consumes existing
registered private state and its confirmed discovery plan. Require valid plan
digest, current installation window, matching registered origin/environment,
actual architecture and service_mode=user. Independently verify pinned publisher,
manifest/plan binding and staged files before touching systemd configuration.

After plan shape, registered target and local digest verification, an expired or
not-yet-valid installation window returns `user_service_install_plan_outside_window`.
Obtain and explicitly confirm a current plan; preserve identity, staged files
and existing periodic confirmation history. This does not renew periodic consent
or permit replacing its history automatically. Missing/corrupt binding remains
a generic installation error. A successful past registration or periodic
acknowledgement does not bypass the installation window.

Install `siq-edge-discovery.service` under the current user's config/systemd/user.
No symlink directory components; ancestors owned by root/current user and not
group/world-writable (root-owned sticky shared temp ancestry permitted); final
directory current-user-owned and not group/world-writable. New unit 0600, synced,
atomic hard-link publication without replacement. Same-content retries permitted;
different/linked/unsafe existing units refused, never overwritten. Temporary
files created by this operation are cleaned; staged artifacts and identity stay.
Same-user/root tampering and lifetime verification at each later launch remain
outside this install-time check; callers keep installation ancestry stable.

Without --start only install configuration. With --start release the Edge task
lock first, then call fixed /usr/bin/systemctl without shell: --user daemon-reload,
--user enable --now UNIT, --user is-active --quiet UNIT. Each call has a 20-second
bound; fail stops subsequent steps and keeps config for retry. No sudo, system
scope, linger or raw subprocess output. Active does not prove heartbeat, discovery
or runtime protection. A failed start may leave an enabled unit; no automatic
rollback/downgrade is attempted. Running Edge lock causes install to refuse;
updates to a different unit require a separate lifecycle flow, still pending.

Cancellation is checked before local lock/state creation, before writing the unit,
after writing it and before/after each manager call. An already cancelled request
creates no installation state; cancellation between activation phases prevents
the next command and is not reported as successful activation. Already completed
file writes or manager effects remain for inspection/retry; an in-flight write may
finish and no atomic cancellation or automatic rollback is promised.

This is an internal installation building block, not final one-click UX. Tests
use temporary directories and injected service-manager calls; native lifecycle,
login/logout/reboot, production signed package and deployment remain unverified.
