# Admission decision table (short)

Disposition is by **category**, not by severity. Full table: `docs/agentshield-dev-spec-v1.md` §3.6.4.

## Quarantine (do not install, do not grant)

- User deception (`adm-user-deception`)
- Hidden instructions (HTML comments with instruction verbs, zero-width / BiDi, homoglyphs)
- Prompt injection in `SKILL.md` body or `scripts/` (quoted examples and `references/` / `evals/` are info)
- Credential path **and** an outbound sink in the same file (`adm-credential-path`, `threat-cred-*` + egress)
- Integrity: missing `SKILL.md`, symlink escape, over-limit, `skill.manifest.json` hash mismatch

## Declare → `admit_with_conditions` (hand to grant)

- `allowed-tools`
- Outbound hosts in scripts (localhost is info)
- Package install (`pip`/`npm`/`brew`/…)
- Writes outside the skill dir
- `curl | sh` install steps (`threat-download-exec-*`) — capability, not isolation
- Lone credential read without egress → `credential.read` declared fact (still not allow)

## Info only

- Documentation zones: `references/`, `evals/`, `assets/`
- Frontmatter `name` vs directory mismatch
- Quoted / fenced examples of injection phrases
- Official-style mentions of dotenv files in docs

## Verdict

```
quarantine if any finding.disposition == quarantine
else admit_with_conditions if any declare
else admit
```

The model does not choose the verdict. `siq-agent-security admit` does.
