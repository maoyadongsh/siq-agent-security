# Enterprise user service upgrade review v1

Linux command: `review-enterprise-upgrade --plan FILE --from-stage DIR --to-stage DIR --tenant ID`.
Read-only preparation for ADR-061; no implicit approval, installation, service control or connector execution.
Not an alias for setup-enterprise and not a migration/upgrade success result.

Exact review fields:

- `schema_version`: `enterprise-upgrade-review/v1`.
- `status`: `reviewed_not_applied`.
- `intent`: object below.
- `confirmation_sha256`: SHA-256 of canonical intent JSON (sorted keys, compact separators,
  ASCII escaping, matching Python `json.dumps(...,sort_keys=True,separators=(',', ':'),ensure_ascii=True)`).
- `publisher_signature_verified`: true, covering both staged bundles against the compiled key.
- `service_activity`: `not_checked`; execution requires an independent stopped-service check.
- `connector_capabilities_verified`: false; review does not launch binaries.
- `requires_explicit_confirmation`: true.
- `installed`: false; `business_permissions_granted`: false.

Exact intent fields: `schema_version=enterprise-upgrade-intent/v1`, `device_identity`, `tenant_id`,
`environment_id`, `control_plane_origin`, `state_path`, `state_file_sha256`, `unit_path`, `from`, `to`.
Each side has exactly `stage_path`, `plan` (enterprise-install-plan/v1), `unit_sha256`.
Unit digests refer to exact renderUserService bytes with the respective Edge/Connector directory
and the unchanged private state directory. Current old unit must match those bytes.
Paths must be canonical absolute paths; old and new stages must be distinct and non-nested.

Use the current registered state (private owner/mode/single-link/no-symlink ancestry), its confirmed
plan digest and old signed stage. New plan must be current and target the same tenant, registered
environment, origin, architecture and user-service mode. Existing old plan may be outside its
historical installation window; it is still required to be structurally valid and signed-stage bound.
Both releases and selected artifacts are independently verified by VerifyStagedBundle, then rechecked
at the end. Current state and unit are re-read; changing either invalidates review. New plan file raw
bytes are re-read; even whitespace mutation during review is rejected. No source scan or network I/O.

No credential, signing seed or entire private state is emitted. The opaque state digest binds those
fields without exporting them. Fixed errors explain preservation/review requirements; untrusted
exception text and private path diagnostics do not escape. Validation failure emits no review document.
Output transport failure may leave truncated bytes; the command fails, and consumers must require a
complete document and successful exit. Cancelled requests and output-write failures remain read-only.
No task-lock file is created. Machine shape: `enterprise-upgrade-review.v1.schema.json`.

Future apply/recovery commands must independently rebuild and compare intent, check actual stopped
service/task exclusivity, and use durable recovery. This review alone never changes effective authority,
periodic consent or installation status. Semantic-version ordering or publisher revocation is not
inferred from this document. Other operating systems return `enterprise_upgrade_requires_linux`.
