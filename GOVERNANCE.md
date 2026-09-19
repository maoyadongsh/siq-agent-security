# Governance

How decisions, reviews and research releases are maintained.

[简体中文首页](README.md) · [English home](README.en.md) · [Research guide](research/README.md)

---

## Maintainer and decision records

SIQ Agent Security is a research project maintained by [@maoyadongsh](https://github.com/maoyadongsh). There is one current maintainer, not an independent review board. CODEOWNERS identifies that account. Decisions and their evidence are recorded in PRs or research documents.

## Reviews and merge policy

Contributions enter through PRs with applicable CI and source/license review. Main requires current checks, resolved conversations and code-owner review. As checked on 2026-09-19, 31 required checks and one approving code-owner review are configured; future changes must be checked against the actual branch settings. Administrators retain bypass because there is no second maintainer; any owner-only merge must record that exception and passed checks. This is not independent approval. No collaborator is automatically granted privileges.

## Research integrity

New research protocols identify hypotheses, task units, exclusions, model budgets and analysis before confirmatory runs. Historical runs remain retrospective. Correct errors with versioned errata; retain failed attempts, original denominators and frozen identities. Changes to contracts or threat boundaries follow the repository ADR process.

## Release requirements

Release publication requires identifiable source, passing checks, provenance and license review, credential disposition, artifact checksums and accurate signing status. Never label an unsigned archive as publisher-authenticated. The V5 freeze is a historical competition snapshot; a research version has its own identity. The published client [0.3.0](docs/evidence/releases/0.3.0/README.md) is separate from `research-v0.1.0-rc.1` in CITATION.cff. Changes to main or Skill source do not update existing signed assets; new client releases require a new source/artifact identity and signing. Use the [packaging guide](docs/signed-release-packaging.md) and [verification/readback tools](scripts/release/README.md). Native source smoke checks, release installation and complete host acceptance are separate scopes.

## Maintainer access and conflicts

Sustained contributors may request maintainership through a public governance proposal describing scope and review history. The owner decides current access, records conflicts, and can remove access for inactivity or misconduct with an explanation. Declare financial, institutional or evaluation conflicts; obtain an independent reviewer when available. No current independent appeal body is claimed.

## Attribution and community responsibility

Software contributors retain attribution. Paper authorship requires actual scholarly contribution and consent; commit counts or tool-generated commits do not establish authorship. No CLA or copyright assignment is required. Conduct concerns and appeals follow CODE_OF_CONDUCT.md. Support and response capacity are best-effort until a maintainer explicitly commits otherwise.
