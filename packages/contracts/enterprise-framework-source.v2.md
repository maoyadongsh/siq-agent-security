# Enterprise framework source v2 — Hermes profile evidence

Additive ingestion version; OpenClaw enterprise-framework-source/v1 remains unchanged.
Hermes may report a string attribute `framework_source` containing exact fields:
schema_version=enterprise-framework-source/v2, framework=hermes, instance_key,
config_sha256, evidence_id. Keys are unique; all values are strings; JSON is at
most 2048 UTF-8 bytes. instance_key and config_sha256 are 64 lowercase hex.

instance_key is the existing profile identity SHA-256 of the normalized absolute
profile directory, not a new runtime identity. Candidate must be hermes_profile,
framework=hermes, ID hermes:v2:KEY and locator hermes://profiles/v2/KEY; KEY must
equal instance_key. The authenticated task connector must be hermes. The source
must reference exactly one candidate-referenced evidence in this batch, with
source_type=manifest, subject_ref=candidate ID, source_locator=KEY/config.yaml,
and content_hash=config_sha256. Existing task, tenant, device, batch and evidence
signature checks remain mandatory; this attribute is not independent attestation.

Collector emits only from an explicitly included, successfully read, complete
config.yaml evidence. No source for SOUL.md-only or truncated config; no fallback
to inferred paths or partial hashes. Missing source on an older client remains
valid and means unknown. Toolsets are not installed Skills or effective rights.

This version identifies a historical profile configuration report, not an
executing instance, Skill installation/loading, shared sandbox or protection.
## Read projection

The existing framework-source GET returns enterprise-framework-source-view/v2
for Hermes assets, with the same exact fields and unknown/history states as v1.
A successful v2 source requires framework=hermes, the profile instance key
matching the asset locator, and unique evidence matching tenant, device,
environment, manifest type, candidate subject, config hash and KEY/config.yaml.
Missing/corrupt evidence remains unavailable; missing declaration remains unknown.
OpenClaw continues to use view/v1 and requires framework=openclaw. Consumers must
validate the version/framework pair, not accept arbitrary framework names.
Both retain runtime_status=unverified, skill_relationship_status=unresolved and
effective_permissions=null. No authorization, storage or write API is added.

Framework inventory returns enterprise-framework-role-inventory/v2 if a page
contains any source-view/v2, otherwise retains inventory/v1. Inventory/v2 accepts
the two explicitly known source projection versions; v1 contains only view/v1.
Pagination, filters, read permissions, tenant scope and page coverage are unchanged.
Old strict consumers may reject v2; deploy producer/consumer together, never map
Hermes to OpenClaw to bypass validation. Current tree/detail consumers use the
same scoped grouping and styles; this is still not a runtime or Skill relation.
