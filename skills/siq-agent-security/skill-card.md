# Skill Card — siq-agent-security

## Description

Admits unknown skills and signs each tool-call receipt.

Admission verdict: **self** (regenerate with `siq-agent-security admit skills/siq-agent-security`).

## Owner

SIQ Agent Security

## License/Terms of Use

Apache-2.0

## Use Case

Install a local gate on OpenClaw, Hermes, CodeBuddy, or Trae so that untrusted
Agent Skills are admitted, least-privilege granted, and every tool call gets a
signed receipt.

## Deployment Geography for Use

Local workstation. Decision API binds 127.0.0.1 only.

### Requirements / Dependencies

Requires API Key or External Credential: No

Declared capabilities (expected after admit):

- `tool` `tool.invoke` → `terminal`
- `tool` `tool.invoke` → `read_file`

## Known Risks and Mitigations

Risk: the model might try to approve a grant.

Mitigation: `grant approve` requires `--approve-as`; SKILL.md forbids the model
from running it.

Risk: Trae cannot block tool calls.

Mitigation: console shows L0 / audit-only; admit before install.

Risk: OpenShell filesystem/process policy is not hot-updated.

Mitigation: grants mark those domains `static_domains_unavailable`.

## References

- `docs/agentshield-dev-spec-v1.md`
- `docs/adr/0011-portable-skill-form.md`

## Skill Output

JSON admission / grant / receipt documents plus a Skill Card. All signed by the
local Ed25519 identity in the state directory.

## Skill Version

0.2.0

## Ethical Considerations

This skill never executes candidate skill code. Findings store redacted excerpts
only. The model is not an authority for safety decisions.

---
本卡描述 siq-agent-security Skill 自身，不构成对第三方 Skill 的签名、批准或发布。
