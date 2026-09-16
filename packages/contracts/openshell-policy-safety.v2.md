# OpenShell policy safety v2

This is a client safety contract, not a new OpenShell server protocol. Existing
API envelopes remain compatible; v2 operation bindings live in receipt evidence.

Implementation tracking: the 2026-09-15 O01/O02/O03 batches implement the
policy-fidelity, process-local rollback and bounded CLI transport requirements.
Their component checks are recorded separately from real-gateway/native
acceptance. O04 details are superseded by openshell-capability-evidence.v3.md. See the overall
taskbook v4.1 section 15 for the current acceptance status.

## O01 snapshot and policy fidelity

`policy get <target> --full` is accepted only when it has exactly one YAML
document delimiter and a canonical positive decimal `Active` or `Version` revision
in the metadata preceding that delimiter (both CLI output forms are covered by
the shared vectors). When both occur they must agree; neither may default to 1.
Missing revision, conflicting values, duplicate metadata keys,
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

## O04 capability facts and evidence levels (implemented 2026-09-15)

A probe result must never collapse distinct facts into one `supported` or
`connected` boolean. Adapters report these fact categories separately:

1. `client_expressible` — what this client adapter version can express in a
   policy document (compile-time fact about the adapter itself).
2. `documented` — what OpenShell docs or historical evidence records, always
   tagged with the observation date and instance scope. Historical observations
   never describe the current endpoint unless reconfirmed against it.
3. `configured` — what the local configuration currently points to (endpoint,
   gateway name from `gateway info`, CLI binary). `gateway info` is a local
   config print and proves nothing about reachability.
4. `handshake_verified` — a live `status` invocation succeeded AND its output
   structurally matched the expected OpenShell server-status shape (a
   `Server Status` heading plus a `Gateway:` name line). Empty, unrelated or
   rc=0-but-wrong-protocol output never upgrades this level.
5. `readback_verified` — `policy get --full` returned a parseable snapshot for
   a named target with revision and digest.
6. `enforcement_verified` — reserved. Only real behavioral fixtures observed
   against the current endpoint may set it; component tests must not.

Derived fields carry their own provenance:

- `cli_version` (from `--version` or gateway-info text) and `gateway_version`
  (only when the live `status`/handshake output states it) are separate fields.
  A CLI version alone never fills `gateway_version`, never upgrades any
  capability level, and only feeds a descriptive `schema_version` hint
  (`unknown-policy-v1` while the gateway version is unknown).
- Version and gateway-name caches require an explicit CLI/endpoint fingerprint
  including TLS mode and CLI file identity, plus observation time. Indirect
  PATH/env.sh selection is not reusable; failed refresh clears cached evidence.
- Legacy boolean fields (`dynamic_network_update`, `static_filesystem`,
  `static_process`, `landlock`, `revision_support`) remain for compatibility
  and keep their historical-documentation semantics; consumers that need a
  current-instance claim must use the evidence fields and capability document
  instead. New fields are additive; existing JSON keys keep their meanings.
- `max_filesystem_paths` remains the contract default and is reported as
  unmeasured (not as a tested limit).

Diagnostics implement: `unconfigured`, `configured_unreachable`,
`identity_unconfirmed` (protocol mismatch or handshake shape wrong),
`handshake_verified` (protocol response only),
`policy_readable` (readback verified, enforcement unverified),
`evidence_expired`. `behavior_verified` is reserved without a current producer. Each state carries a
short actionable next step.
