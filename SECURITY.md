# Security policy

Report a suspected vulnerability privately through [GitHub private vulnerability reporting](https://github.com/maoyadongsh/siq-agent-security/security/advisories/new). This repository's entry is enabled; [readback](docs/research/evidence/private-reporting-readback.json). The repository owner, [@maoyadongsh](https://github.com/maoyadongsh), is the current maintainer and recipient. Do not put unpatched exploits, tokens, private keys or raw service state in public Issues.

The current development branch receives fixes on a best-effort basis. Older v0.1/v0.2 downloads and the frozen V5 competition snapshot are historical artifacts, with no promised backport window. There is currently no staffed response SLA or production support commitment.

Include the affected commit/version, component, threat boundary, expected and actual behavior, and a minimal sanitized reproduction with synthetic data. Explicitly distinguish same-UID access, model output, authorization decisions and independently observed effects. Do not attach private signing seeds, provider configuration or complete state directories. A maintainer may request further material through the private advisory.

The maintainer triages scope, preserves the private report, reproduces in a disposable environment, prepares a fix with a negative regression test, and coordinates a disclosure date with the reporter. Confirmed exposed credentials must be revoked or replaced; deleting a file does not revoke them. See [response process](docs/research/security-response-process.md) and [historical key review](docs/research/history-review.md).

The runtime is not an OS sandbox against processes running as the same user. Controlled receiver evidence is not universal proof of external SaaS delivery. These limits remain part of the [threat model](docs/threat-model.md).
