> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Constrained Skill plans V4

The application uses `model-task-plan-v2.schema.json`: one, two or three Skills
selected from the closed built-in registry. The historical V1 schema is retained
for old evidence and contract compatibility. The deterministic validator rejects
unknown Skills (`skill_unregistered`), missing or reordered dependencies
(`plan_dependency_invalid`) and duplicates (`plan_skill_duplicate`). There is no
automatic repair, generic shell/HTTP mapping or replanning loop.

Research requires no predecessor; report requires research; delivery requires
report. The catalog includes input/output schema metadata, dependencies, tools
and SIQ security requirements. SKILL.md remains static admitted documentation,
never imported or executed as untrusted Python.

The operator chooses the requested outcome through CLI `--output` or paired
dashboard research-only / research-report / normal scenarios. The model receives
the goal, outcome and registry and proposes actual typed Skill calls. A plan
exceeding the operator outcome is rejected before source preparation; a plan
omitting a requested outcome fails explicitly. Each submitted task records its
selected and completed Skills. UI lists this actual plan rather than the catalog.

Preparation still reads sources through SIQ, obtains model findings and commits
exact report/delivery bytes before execution. Replay still checks every source
path, revision, hash and content against the committed research. Only requested
effects enter the immutable execution Intent; its allowed tools are narrowed to
the selected Skills. Research-only performs no write or contact lookup. Its
application state is `researched`; the existing SIQ effect Completion remains
UNKNOWN with no effect requirements. The application never invents a VERIFIED
effect for an analysis result. Report tasks verify only the file; delivery tasks
verify both file and controlled receiver events.

SP-01–08 cover the closed graph and tool/authority injection. Actual SIQ integration
tests assert one/two/three Skill execution, absence of unrequested tools/effects,
and unchanged revocation, provenance, approval and source-replay denials.
The frozen 23-task control corpus retains the same cases; the command-proposal
case now expects the V2 `skill_unregistered` category instead of V1's generic
`plan_skill_order_invalid`. Historical corpora/evidence hashes are not rewritten.
