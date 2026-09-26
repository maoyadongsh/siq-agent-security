# Enterprise Linux device state read v1

LoadState (serve, heartbeat and task CLI) opens the canonical absolute state path
through descriptor-relative no-follow directory traversal. Ancestors must belong
to root/current user and disallow group/world writes, except root-owned sticky
directories such as /tmp. The final directory must belong to current user and
be owner-only. State must be an owner-only, current-user-owned, regular single-link
file; symlinks, FIFOs, devices, oversized or changing files are rejected.
Read bound is installation plan MaxBytes plus 8192. A bounded-depth token walk rejects
duplicate JSON keys, trailing values and invalid UTF-8 before state decoding. Existing unknown
state fields retain forward-compatible handling. Missing state retains the
not-registered error; unsafe/malformed state yields fixed, path-free diagnostics.

No permission repair, deletion, re-registration or identity replacement occurs.
These checks precede outbound requests. This does not defend against a trusted
same-user/root adversary, certify the control-plane origin, or change registration
and save semantics. Non-Linux state reading is unchanged and not claimed to have
these Linux guarantees. Relative SIQ_EDGE_STATE_DIR is not accepted on Linux;
use an absolute private directory created by the installer.
