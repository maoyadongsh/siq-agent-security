# OpenClaw approved held execution / v1

Status: local integration contract layered on
`openclaw-approval-checkpoint.v1.md`. It uses the existing host capability
marker and callback, plus the signed N06 execution-reservation contracts.

## Trusted sequence

For a signed `hold`, the SIQ adapter waits for local approval and returns an
OpenClaw `requireApproval` request only when the host supplies
`approvalExecutionRecheckVersion: 1`. After native platform approval, the host
must await `beforeExecute(finalParams, signal)` and treat only boolean `true` as
permission to invoke the tool.

The callback performs these steps within one bounded attempt:

1. Re-read `/v1/hold-status` with the original platform, session, agent, task,
   tool, tool-call ID, action ID, decision receipt and the host's final params.
2. Derive a distinct retry tool-call ID from the signed action and original
   call identities. The value identifies this post-approval execution attempt;
   it is not supplied by model text, tool parameters or user configuration.
3. POST `hold-execution-reserve/v1`. The daemon atomically checks current
   authority and appends a signed `hold_reservation` before returning HTTP 201.
4. Accept only an unexpired `hold-execution-status/v1` response whose status is
   `reserved` and whose action and decision receipt equal the original hold.
5. Snapshot the JSON params used for the reservation. After execution, send
   `/v1/observe` with the retry tool-call ID, the reserved params, the original
   action ID and the reservation receipt ID as `decision_receipt_id`.

The OpenClaw host still invokes its tool with its native call ID. The trusted
adapter assigns the retry ID at the execution checkpoint and translates the
matching after-hook observation. This distinction must remain visible in
receipts: the original hold uses the native call ID, while the reservation and
observation use the derived execution-attempt ID.

## Failure and recovery

Missing capability, local or platform rejection, expiry, final-param changes,
authority revocation, cancellation, timeout, an unavailable daemon, non-201
reserve response, malformed response and a repeated callback all return false.
They never authorize the tool.

If the daemon persisted the reservation but its response was lost, the adapter
cannot know whether authority reached the host. It returns false, and the
signed state remains `uncertain`. A subsequent read or callback must not execute
the tool. An administrator must inspect the external effect and use the
`hold-execution-reconcile/v1` path. This contract does not promise exactly-once
external side effects or an atomic transaction across daemon state and the
tool's target system.

## Evidence requirements

Acceptance must exercise the real OpenClaw approval manager and patched native
tool wrapper, the shipping adapter, a real SIQ daemon and receipt chain. It must
cover stock-host rejection, both approvals, each rejection and cancellation,
authority revocation during platform wait, changed final params, callback
failure/timeout, daemon disconnection, exactly one reservation for an executed
call, and observation binding to that reservation. A synthetic tool target and
automated operator may prove the control path, but must not be described as a
human UI or real external side effect.
