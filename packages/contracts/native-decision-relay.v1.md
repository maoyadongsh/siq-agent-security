# Native decision relay v1

This is an explicit extension to the authenticated native host channel for
OpenShell profiles that do not expose the host daemon through the sandbox
network. It reuses the existing `/v1/decide` authority and unique prepared-call
binding. It does not grant authority from a channel event.

The trusted launcher pins the same Publisher, subject, RuntimeGuard, loopback
daemon endpoint and one scoped runtime identity credential. The credential is
host-only; no publisher/admin credential, chosen URL, header or proxy is accepted
from the runtime. The runtime authenticates host responses under the protected
mount or explicit image profile. The host authenticates every request's kernel
peer before dispatch.

The event is exactly:

```json
{
  "schema_version": "native-decision-relay/v1",
  "request": {
    "platform": "hermes",
    "agent_id": "hri-00000000000000000000000000000000",
    "session_id": "launcher-pinned-session",
    "runtime_task_id": "actual-task",
    "tool": "read_file",
    "tool_call_id": "actual-call",
    "params": {"path": "/sandbox/example"}
  }
}
```

All seven request fields are required, unknown fields are rejected. Identity
fields must equal the launcher's subject; task/tool/call identifiers are nonempty
strings of at most 256 UTF-8 bytes without controls. Params must be an object.
The existing 64 KiB packet limit applies to the whole frame; raw parameters are
transported only for the existing HTTP decision and are never logged by the relay.
The call must have a matching prior `call_prepare`; the Go daemon rejects missing,
replayed or changed bindings under its existing online contract.

The host verifies the runtime before and after one bounded HTTP POST to the fixed
`127.0.0.1` endpoint using the fixed runtime credential. No redirects, proxy,
credential fallback or automatic retry. It returns only `action` (`allow`, `deny`
or `hold`) and the daemon's nonempty bounded `receipt_id`; it never forwards
parameter rewriting, extra Authority, headers or secrets. Non-200, malformed,
oversize or unavailable responses return the fixed error object
`{"error":"native_host_unavailable"}`. The runtime treats this as failure to
authorize, never as an allow or a fabricated signed receipt.

Lifecycle events continue through Publisher unchanged. Decision relay remains
an explicitly wired trusted-launcher component; it does not open native identity
creation or claim completion of the real two-Skill business acceptance.
