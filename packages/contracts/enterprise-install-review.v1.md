# Enterprise installation review v1

`setup-enterprise --review-only --plan FILE --tenant ID --environment ID
--control-plane ORIGIN [--start]` validates the current plan/context/host and
prints indented JSON without requiring a release, enrollment code or confirmation
digest. It must not read device credential state, write files, stage, enroll,
activate services or scan. Context mismatch/expired/invalid plan fails closed.

Exact output fields: schema_version=`enterprise-install-review/v1`,
status=`review_only`, confirmation_sha256 (raw input file digest), start_service
(explicit requested mode), release_signature_verified=false,
requires_explicit_confirmation=true, business_permissions_granted=false,
plan (complete enterprise-install-plan/v1), notice (human boundary explanation).

The plan shows tenant/environment/origin, expiry, platform/service mode, selected
Connectors and explicit root/include scope. It does not assert installed software,
actual Connector capabilities, source authenticity or device readiness. Confirmation
must be a separate user choice after review; no auto-approval based on this output.
Changing even whitespace in the original file changes its confirmation digest.
