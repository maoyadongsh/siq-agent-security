> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Structured ornith generation

The local SGLang service exposes JSON-schema constrained generation through its
Chat Completions API. The [upstream structured-output documentation](https://github.com/sgl-project/sglang/blob/main/docs_new/docs/advanced_features/structured_outputs.mdx)
describes `response_format.type=json_schema`, an explicit schema, temperature and
token limits. The local inspected package reports `0.0.0.dev1+g5f55db35e`; actual
compatibility must also be tested against that running service.

Ornith requests use the new proposal-only schemas in `packages/contracts/`:
`model-task-plan`, `model-research-proposal`, `model-recipient-selection`.
The plan schema constrains three Skill entries and their typed inputs in order;
research constrains findings/summary; recipient selection remains an integer
index, with candidate-range validation performed by the host. Schemas do not
contain authority, approvals, signatures or policy decisions. The runtime reads
these repository-owned schemas; packaging must retain them.

Ornith uses temperature zero with maximum generation budgets of 3072 plan,
4096 research and 1024 recipient tokens. It also sends SGLang's
`chat_template_kwargs.enable_thinking=false`: the actual installed model's
`chat_template.jinja` explicitly supports this switch. This bounds the demo's
generation work by requesting direct proposal output; it is not a model-quality
claim. The preceding schema-only cohort retained a 4096-token research length
failure, so this request profile is evaluated as a separate cohort.
A length stop still fails validation;
the application never treats a truncated response as completed. StepFun retains
the existing JSON-object transport pending the operator's later configuration.
No model service restart/settings change, JSON repair, hidden retry or fixture
fallback is introduced. Strict duplicate-key and typed validation remain in the
host, even if the provider claims to enforce a schema.

Each call records its actual generation profile and schema digest. Timeout
exceptions receive `model_request_timeout`; other transport failures retain
`model_request_failed`. Earlier generic failures are not relabelled retroactively.
Previous benchmark/model failures remain archived separately, and any new cohort
must retain all attempts rather than retrying until it passes.

## Actual validation

- The schema-only profile completed a [live GitHub task](live-source-validation.md),
  but its separate [five-task cohort](evidence/benchmark-20260908/ornith-structured.json)
  completed 4/5. The approval task's research call stopped at exactly 4096 tokens
  (`finish_reason=length`), before execution commitment. Its signatures and
  metrics are [verified separately](evidence/benchmark-20260908/ornith-structured-verification.json).
- The final direct-output profile completed [5/5 new benign attempts](evidence/benchmark-20260908/ornith-direct.json),
  with 15 accepted model calls, including the approval task. The existing verifier
  checked [121 receipts and ten effect envelopes](evidence/benchmark-20260908/ornith-direct-verification.json).
  This small descriptive cohort does not establish general model reliability or
  review quality. Both earlier 4/5 cohorts remain evidence, not discarded retries.
- 69 Secure Agent tests passed; the final direct-output request change also
  passed all 17 provider tests. Eight new JSON Schema tests reject authority
  fields, altered Skill order and invalid recipient indices. Provider claims
  never bypass the strict host parser.
