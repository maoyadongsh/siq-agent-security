# Contributing

Start with [reproduction](REPRODUCIBILITY.md), the [research guide](docs/research/README.md), or a scoped [community task](docs/research/community-backlog.md). Reproduction failures and denominator corrections are useful contributions. Use synthetic data and preserve unsuccessful attempts. Vulnerabilities go through [SECURITY.md](SECURITY.md).

Open a branch and pull request. Describe the trigger, changed behavior, provenance of added code/data, and commands actually run. Follow the nearest AGENTS.md. Changes to security contracts start with the schema/specification and include a negative test showing the old bypass is rejected. Do not change frozen V5 numbers or replace its evidence; new runs receive new paths and identities.

Usual checks from the repository root:

```bash
python3 scripts/check_research_task_ledger.py
git diff --check
# Go runtime changes:
(cd apps/agentshield && go vet ./... && go test ./...)
# Python application changes (install with uv sync --dev --locked first):
(cd apps/control-api && uv run ruff check app && uv run pytest)
# Web changes:
(cd apps/web && npm ci && npm test -- --run && npm run build)
```

Fixture and contract tests do not require model credentials, GPU access or publisher keys. Use the component-specific tests in AGENTS.md for adapters, schemas and connectors. Live model runs need explicit provider/budget configuration and must never execute in untrusted PR jobs.

New contributions use the applicable existing file license and the [Developer Certificate of Origin 1.1](DCO). Certify only work you have the right to submit by adding your own `Signed-off-by: Name <email>` trailer (`git commit -s`). A sign-off is not copyright transfer or automatic paper authorship. Do not fabricate another contributor's sign-off or retroactively rewrite historical commits. The maintainer reviews sign-offs on new contributions; no external DCO App has been granted access. License or provenance uncertainty should be stated in the PR.

Software attribution, acknowledgments, datasets and paper authorship are separate decisions. Citation is encouraged through CITATION.cff but is not an additional software license restriction.
