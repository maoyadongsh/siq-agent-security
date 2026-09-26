# Enterprise installation options v1

Authenticated GET `/api/v1/environments/{environment_id}/install-options` (Gateway
prefix /api/agent-security/v1). Locate the tenant-scoped environment first (404),
then require both env:manage and edge:manage (403). Read-only: no plan, enrollment,
device, scan, business grant or mutation audit is created.

Exact fields: schema_version=enterprise-install-options/v1, environment_id,
control_plane_origin, allowed_service_modes, releases, purpose=discovery_only,
release_signature_verified=false. Releases use the controlled installation catalog
shape: target_arch, release_version, release_manifest_sha256 and Connector entries
(id/version/artifact_sha256/protocol_version/scope roots/include).

Only configured user service mode is currently offered, matching the shipped
orchestrator; a system-only catalog is unavailable, not silently downgraded.
Trusted-origin semantics and scope validation are shared with plan issuance.
Missing/unsafe/invalid catalog yields fixed 503 install_options_unavailable, no
internal path/error/body disclosure. Success is Cache-Control: no-store.
Catalog visibility is not publisher verification or proof of host capabilities;
frontend must obtain explicit scope consent and clients still verify signed files.
