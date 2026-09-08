> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Demo evidence readback and renewed pairing

The authenticated task-list snapshot includes `skills`, the names in the
application's closed built-in registry. The UI presents this as the available
task Skills, not an SIQ effective permission claim. Per-action authorization
and allowed tools/effects still come from SIQ and the committed Intent.

Action snapshots may contain `provenance_readbacks`, an array of parameter path,
provenance reference, readback time, `resolved`/`unavailable` status, and either
the original assertion returned by existing SIQ `/v1/provenance-resolve` or a safe
error category. Queries use only the action's existing references and the
operator-owned task scope. The browser cannot choose a scope, reference or admin
route. Resolution is descriptive evidence at the recorded time; it does not
authorize execution or override the original decision, revocation or HOLD recheck.

For `/recipient`, `matches_operator_contact` states only whether the actual
proposed scalar equals the operator's trusted-directory value. Equality does not
change its provenance. The UI displays SIQ-returned source type/trust, assertion
digest/scope/parents and the actual decision, including the same-value MCP denial.
A failed readback is shown as unavailable, never as a fabricated source label.
These optional display reads do not change an otherwise completed decision.
Allowed tools are inspected after execution/observation, so display traffic is
not inserted between an allow decision and tool entry. Denied/held actions are
inspected after their decision; approval still requires the existing recheck.

Authenticated `POST /hackathon/v1/pairing/renew` with exactly `{}` replaces any
unused pairing code with a fresh one-use, five-minute code. It returns
`{pairing_code, expires_in:300}` only to the authenticated operator. Existing
sessions, tasks and SIQ authority remain intact. The standard same-origin/custom
header checks apply. This endpoint is not callable by an unpaired browser or by
the model. `scripts/hackathon/pair.sh` uses the existing private local controller
credential and prints the new code to the local operator; it does not restart or
reset state. Pairing codes never enter public task snapshots or health responses.

## Validation

The [five application captures](evidence/provenance-readbacks-20260908.json)
include actual source assertion readbacks from SIQ, receipt chains and effect
readbacks. They use the explicit fixture model. The
[browser run](evidence/dashboard-provenance-final-20260908/result.json) covers
six scenarios, same-value origin explanation, persistent pairing errors and
renewed pairing in a second browser context. Both old and new cookies successfully
read the same task history; mobile layout and no-localStorage checks pass.

Application tests additionally resolve a revoked issuer as unavailable, check
the actual trusted-directory and MCP assertion types/scopes, reject unauthenticated
or cross-origin renewal, enforce one-use codes and preserve completed task state.
Allowed-tool entry precedes optional provenance display reads.
