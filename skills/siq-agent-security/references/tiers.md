# Enforcement tiers

siq-agent-security reports the highest tier the **current host and platform** can
actually enforce. The console label is the source of truth; do not invent a
higher tier.

| Tier | What it does | Needs |
|---|---|---|
| L0 | Inventory + admit. Cannot block a running tool call. | Any OS |
| L1 | Pre-install gate. Quarantined skills are refused at install. | A platform install hook (OpenClaw `installPolicy`) or the Hermes wrapper `hermes-skills-install` |
| L2 | Every tool call goes through `/v1/decide`; deny is a signed receipt. | OpenClaw `before_tool_call`, Hermes `pre_tool_call`, or CodeBuddy `PreToolUse` |
| L3 | OpenShell network `policy set` + read-back. Filesystem and process stay static. | A running OpenShell gateway that `status` verifies as OpenShell (Linux native, or Docker/WSL2). Optional: L0–L2 still work. siq-agent-security discovers the CLI on PATH or `SIQ_AS_OPENSHELL_ENV_SH`; it does not start the gateway. Without L3 the console must say tool-layer only. |

## Platform matrix (honest)

| Platform | Linux | macOS | Windows |
|---|---|---|---|
| OpenClaw | L0–L3 | L0–L2 (L3 needs Docker) | L0–L2 (L3 needs WSL2) |
| Hermes | L0–L3 | L0–L2 | L0–L2 |
| CodeBuddy / WorkBuddy | L0, L2 | L0, L2 | L0, L2 |
| Trae / TraeWork | L0 only | L0 only | L0 only |

Trae has no tool hook. Say "audit mode, cannot block" and use `siq-agent-security admit`
before any install.

`filesystem` and `process` desired-policy domains cannot become `effective`
through `policy set` (OpenShell `create_generation` is not used). Grants record
`static_domains_unavailable`. Do not tell the user those domains are hot-updated.
