# Edge registration recovery v1

Additive POST `/edge/v1/registration-recovery`. Existing registration remains
single-use. A device that lost the response can prove possession of its already
pinned Ed25519 private key, without replaying enrollment or disclosing secrets.

Exact request fields: schema_version=`edge-registration-recovery/v1`,
device_identity (1..128 ASCII identifier), environment_id (1..64 ASCII identifier),
secret_hash (64 lowercase hex), signature (128 lowercase hex). Sign sorted-key
compact ASCII JSON excluding signature. The schema discriminator binds purpose.
The client MUST persist a fresh random >=256-bit recovery bearer secret before
sending; only its SHA-256 is transmitted here. Never derive it from public data.

Server derives tenant/environment/key from the existing device, validates the
signature and environment, and permits first recovery only within 15 minutes of
registration, before any heartbeat, and while not revoked. It atomically replaces
the bearer hash and creates a unique per-device recovery record plus audit. No
plaintext credential is stored or returned. Audit failure rolls back everything.
Once recorded, only the exact same request digest can be acknowledged; another
hash/request is rejected. Retries still require valid signature, the same 15-minute
window and non-revoked state. An identical retry may follow heartbeat because it
does not change state. A replay cannot rotate credentials back or extend lifetime.

Response: schema_version, edge_agent_id, environment_id, control_plane_public_key,
status=`recovered`; Cache-Control no-store. It grants no business permissions,
does not rescan, change capabilities or revive revoked devices. All authentication
failures use the same 401 error; throttling 429, malformed requests 422. TLS or
loopback HTTP and expected control-plane context are mandatory client gates.

This endpoint is not general key rotation/re-enrollment. After expiry or activity,
use an independently authorized administrative workflow (not yet implemented).
Deployment requires migration 0018. Linux native client implements
`recover-registration --control-plane ORIGIN --environment ID`, retaining a
private recovery credential journal before sending. Registration and recovery
share the Linux task lock; existing final state is never overwritten. Response
schema, environment and control-plane public key shape are checked before saving
the original identity with the recovered secret. Production rollout pending.
