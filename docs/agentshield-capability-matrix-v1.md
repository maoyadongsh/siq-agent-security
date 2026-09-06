# AgentShield 能力证据矩阵 v1（DEV18-C）

- 日期：2026-09-06
- 计划：[DEV18](development-plan-20260906-022735.md#dev18)
- 代码矩阵源：[`apps/agentshield/internal/skillmanifest/matrix.go`](../apps/agentshield/internal/skillmanifest/matrix.go) `DefaultMatrix()`
- 配套声明：[agentshield-capability-profiles-v1.md](agentshield-capability-profiles-v1.md)
- **本文件是证据索引，不是生产验收。** 跳过测试不得计通过；`supported` 行禁止出现。

## 证明强度（列含义）

| 列 | 含义 | 可宣称条件 |
| --- | --- | --- |
| build | 制品可编译 | CI/`go build` 绿即可，**不算**平台能力 |
| L0 | 盘点 / 审计 | 有归档的 admit/scan 或只读探测 |
| L1 | 安装门禁 | 有安装前拦截或包装安装证据 |
| L2 | 运行时决策 / 回执 | 有 hook/plugin deny + receipt/verify 归档 |
| L3_readback | OpenShell 配置读回 | `verify` ≤ `readback_verified`；**≠ 网络强制** |
| L3_enforce | 真实出网阻断 | DNS/IP/重定向/IPv6/失联/替代路径正负测齐全 |

状态词：`evidenced`（有仓内归档）、`unverified`（未测或缺证）、`n/a`（平台无该能力路径）。

## OS × 平台矩阵

| platform | OS | build | L0 | L1 | L2 | L3_readback | L3_enforce | 代码 status | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hermes | linux | evidenced | evidenced | evidenced | evidenced | unverified | unverified | experimental | [hermes-linux-2026-09-05](evidence/agentshield/hermes-linux-2026-09-05/)；OpenShell 未配置 |
| hermes | darwin | evidenced | unverified | unverified | unverified | unverified | unverified | experimental | 无归档 |
| hermes | windows | evidenced | unverified | unverified | unverified | unverified | unverified | experimental | 无归档 |
| openclaw | linux | evidenced | evidenced | evidenced | evidenced | unverified | unverified | experimental | [openclaw-linux-2026-09-05](evidence/agentshield/openclaw-linux-2026-09-05/) |
| openclaw | darwin | evidenced | unverified | unverified | unverified | unverified | unverified | experimental | 无归档 |
| openclaw | windows | evidenced | unverified | unverified | unverified | unverified | unverified | experimental | 无归档 |
| codebuddy | linux | evidenced | evidenced | evidenced | evidenced | n/a | n/a | experimental | [codebuddy-linux-2026-09-05](evidence/agentshield/codebuddy-linux-2026-09-05/)；无 L3 档 |
| codebuddy | darwin | evidenced | unverified | unverified | unverified | n/a | n/a | experimental | hook 落地，无 E2E |
| codebuddy | windows | evidenced | unverified | unverified | unverified | n/a | n/a | experimental | hook 落地，无 E2E |
| trae | * | evidenced | n/a→audit | n/a | n/a | n/a | n/a | audit_only | 无 tool hook，不能阻断 |
| claude_code | * | evidenced | unverified | unverified | unverified | n/a | n/a | experimental | 本轮不做 |
| codex | * | evidenced | unverified | unverified | unverified | n/a | n/a | experimental | 本轮不做 |

OpenShell 隔离探测归档（非 hermes 产品 L3 宣称）：[openshell-siq-research-engine-2026-09-05](evidence/agentshield/openshell-siq-research-engine-2026-09-05/) — 仅说明旁路环境可 probe；**不得**把该目录记成某平台 `L3_enforce`。

## 诚实约束（机器可检查）

1. `DefaultMatrix()` / 已签 `skill-manifest.json`：**零行 `supported`**。
2. 本表任一 `L3_enforce` 在取得隔离正负测归档前必须为 `unverified`。
3. 不得把 `L3_readback` / `readback_verified` 写成“网络已强制”或 `enforcement_verified`。
4. Trae 只能 `audit_only` + L0。

## 与发布清单

发版前仍按 [agentshield-release-checklist-v1.md](agentshield-release-checklist-v1.md)：矩阵与二进制哈希一致，且不得为发版把行抬成 `supported`。
