# OpenShell policy safety v2

This is a client safety contract, not a new OpenShell server protocol. Existing
API envelopes remain compatible; v2 operation bindings live in receipt evidence.

Implementation tracking: the 2026-09-15 O01/O02/O03 batches implement the
policy-fidelity, process-local rollback and bounded CLI transport requirements.
Their component checks are recorded separately from real-gateway/native
acceptance. O04 capability requirements below remain targets. See the overall
taskbook v4.1 section 15 for the current acceptance status.

## O01 snapshot and policy fidelity

`policy get <target> --full` is accepted only when it has exactly one YAML
document delimiter and exactly one canonical positive decimal `Active` revision
in the metadata preceding that delimiter. `Version` is descriptive metadata and
must not be substituted for a missing `Active`. Duplicate metadata keys,
duplicate YAML mapping keys, aliases/anchors/tags, merge keys, non-empty flow
collections, multi-document input, non-string mapping keys and ambiguous
implicit scalars are rejected before a write.

An accepted snapshot contains the complete parsed policy document plus these
derived values:

- `policy_digest = sha256(canonical_json(full_policy))`;
- `static_digest = sha256(canonical_json(full_policy without network_policies))`;
- compatibility projections (`filesystem`, `network`, `process`) which are never
  substitutes for either digest.

The Go parser intentionally supports only the shared, lossless YAML subset. The
Python parser accepts the same subset even though PyYAML can parse more forms.
Both implementations consume `testdata/openshell-policy-safety.v2.json`.

Network compilation accepts only `effect=allow`, one host/port endpoint and one
or more explicit absolute binary paths. Deny, method, path, provider, protocol,
purpose and every unknown rule/endpoint/binary field fail before `policy set`.
The update is made by cloning the full current policy and replacing only
`network_policies`; all other top-level and nested fields remain semantically
identical. A plan requests generation only when an explicitly supplied static
section differs from the actual current section, not merely because a static
field is present.

After `policy set`, the client reads the active policy again and requires both
the gateway-reported revision and the complete expected `policy_digest` to
match. Gateway hashes and host/port projections remain supplementary evidence.

## O02 process-local operation binding

Every apply creates an unpredictable client-generated `operation_id` and a
private bounded operation record. The public receipt contains the operation ID,
target, exact base revision/digest, applied revision/digest and result
(`applied` or `no_op`), but rollback trusts the private record and live readback,
never those caller-supplied fields alone. The private record retains the exact
base policy snapshot. This P0 contract deliberately adds no persistent state
format: eviction, process restart, a missing record or a receipt mismatch makes
rollback unavailable rather than reconstructing history.

Clients serialize apply and rollback per target. Immediately before every write
they re-read and compare revision plus complete digest; immediately after every
write they require the new revision plus expected complete digest. These checks
reduce same-process races and detect observed external drift, but are not an
atomic compare-and-swap against another process or gateway writer.

A rollback whose apply result was `no_op` performs no `policy set`, after first
confirming the live revision and digest still match the operation record. A
changed rollback additionally requires a trusted in-process authorizer, invoked
with the retained base snapshot, and rechecks live state after authorization.
The authorizer must derive current authority from authenticated server state;
it cannot be a boolean or evidence value supplied in the request. Successful
rollback consumes the operation record. Unknown, already consumed, wrong-target,
forged, drifted or currently unauthorized operations fail closed.

- Network changes preserve the entire parsed policy, including Landlock and
  extensions. Unsupported YAML, duplicate keys, ambiguous scalars and missing or
  invalid active revision fail closed. Digests use canonical JSON, never YAML text.
- Only allow host/port rules with explicit absolute binary paths are compilable.
  Deny, method/path/provider restrictions and unknown fields must not be dropped.
- The full expected policy must match readback. Host/port projection is not L7 or
  behavioral verification. Planning compares actual static sections, not presence.
- Process-local serialization covers clients in one process. Before each write,
  revision and full digest are rechecked; after each write, both are verified.
  This is NOT atomic CAS against other processes or external writers.
- A receipt binds an unpredictable operation ID, target, exact base revision and
  digest, applied revision and digest. The client retains the base snapshot in a
  bounded private operation registry. Unknown/restarted registry refuses rollback.
  Caller-supplied evidence alone is not trusted. Drift refuses rollback. A no-op
  rollback does not write. A changed rollback needs a trusted current-authority
  authorizer; absent authorizer refuses (no revoked Grant can be revived).
- CLI stdout/stderr share a byte budget while running. Timeout, overflow and
  pipe-drain waits are bounded. No raw CLI errors or caller arguments in public
  errors. Environment forwarding uses an exact allowlist, never credential prefixes.
- Default native calls introduce no OpenShell subprocess. Performance measurements
  distinguish component microbenchmarks from real sandbox or end-user latency.

Real backend enforcement and cross-process atomicity remain separate acceptance
requirements. New persistent operation storage or backend execution is out of P0.
