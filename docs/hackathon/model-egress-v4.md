> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# V4 model egress contract

The model transport is a separate trust boundary from ToolGateway. The current
implementation enforces an immutable operator classification before HTTP sends;
it does not claim that Python objects or same-UID processes are OS-isolated.

`UserTask.source_sensitivity` and each host-collected `Source.sensitivity` use
PUBLIC, INTERNAL, CONFIDENTIAL or SECRET. Unknown labels fail closed. Public
GitHub sources are not automatically classified as private. Operators must set
the appropriate classification; semantic detection of mislabeled data is not
claimed. `--source-sensitivity` and the service's `SIQ_SOURCE_SENSITIVITY` are
operator controls, absent from model output and HTTP task submission fields.

`ModelRouter` routes research and recipient-context reasoning using the highest
task/source classification. StepFun is remote; Ornith accepts only literal
loopback endpoints and is labeled local_dgx. Sensitive local calls additionally
require a fresh DGX product identity / GB10 availability check. Actual inference
success remains separate from this preflight. Locality is never model-reported.

Default application routing uses StepFun planning and local research/context
reasoning. PUBLIC research can explicitly use the primary remote provider with
`SIQ_PUBLIC_RESEARCH_LOCAL=false`. INTERNAL defaults local; remote use additionally
requires `SIQ_INTERNAL_REMOTE=true` and selection of remote research.
CONFIDENTIAL is local only. SECRET is rejected unless `SIQ_SECRET_LOCAL=true`,
and then remains local only. Flags accept only literal `true` or `false`.

For private workloads remote planning receives a fixed public task description
and opaque repository/path aliases, not operator free text, source bytes or
private names. Only exact supplied aliases bind back to operator task values;
unexpected substitutions remain proposals subject to SIQ. The report workspace
path is also aliased in public remote planning. Source analysis sees the actual
question only on the policy-selected provider. Provider response contracts reject
extra authority/classification fields. Model output cannot configure the router.

Every HTTP attempt records provider/model/locality/operation/task_id,
payload_digest/classification, elapsed_ms and status, with safe error categories.
No request body or API key is in diagnostics. Provider transitions record
from/to/reason/task_id/sensitivity/allowed. Selection is an explicit policy action,
never exception recovery; neither timeout direction triggers a retry or fallback.
Operator switches are rechecked against the current classification and audited.

ME-01–08 and additional DGX/secret/local-failure controls use an actual loopback
HTTP server and assert the received bodies and zero-request cases. These tests
are transport boundary evidence, not proof of production hardware availability,
semantic data classification or resistance to hostile installed Python code.
