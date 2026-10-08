# Native Skill context management V1

OPT-08 lifecycle management for the existing signed `skill-execution-context/v2`
store. This protocol does not issue contexts or grant execution permission.
The legacy `/v1/skill-contexts` routes retain their v1 meaning.

- `GET /v2/skill-contexts?install_id=…`: administrator-only signed history.
  Optional `session_id`, `after` (exclusive context ID cursor), and `limit`
  (1–64, default 32). Unknown or duplicate query keys are rejected. Results
  are sorted by context ID, not by creation time; later requests may observe
  concurrent insertions, so this is not a frozen snapshot. Scan at most the
  existing 4096-record store budget; malformed state fails closed. Response:
  `local-skill-context-management/v2`, `contexts` (signed context and nullable
  signed revocation), and `next_after` (empty at the end).
- `GET /v2/skill-contexts/{id}`: administrator-only
  `local-native-skill-context-record/v1` containing the signed context and
  nullable signed revocation. Historical reading does not require the grant,
  installation, task, or runtime to remain live.
- `POST /v2/skill-contexts/{id}/revoke`: exact
  `local-skill-execution-context-revoke/v2` request with original
  `expected_context_signature`, a valid `actor_id`, and `confirm_revoke=true`.
  Returns the existing signed `skill-execution-context-revocation/v2` tombstone.
  Audit the authorized attempt before writing; an audit failure prevents the
  mutation. The store also audits publication. Repeating the same confirmation
  returns the same tombstone; wrong signatures remain conflicts even after
  revocation. Revoking a parent invalidates descendants on their next check.

All routes require existing loopback/Host/origin and administrator authentication,
return `Cache-Control: no-store`, and do not accept runtime or native publisher
credentials. There is no public create, edit, restore, or delete route.
The native store must already be bound during daemon startup; a missing store
returns 503. Once bound, management remains available after runtime verification
fails, so a host outage cannot prevent withdrawing existing authority.

Malformed requests return 400; absent exact contexts 404; wrong original
signatures 409; unavailable/corrupt state 503; audit failure 500. No raw paths,
credentials, parameters or Skill contents appear in error responses. Contexts
and tombstones retain their existing immutable signatures and state paths.

The management list uses bounded iteration and a request deadline. It is a
history view, not a live `effective` permission statement. Successful revocation
does not undo an already completed external effect or prove that a running
handler was terminated. Runtime checks, effect-time checks and the business
Supervisor retain their existing responsibilities.
