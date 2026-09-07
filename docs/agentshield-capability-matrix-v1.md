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

## Trusted Intent V2 独立证据项（2026-09-07）

此表将源码/本地测试与真实平台归档分开，既有 L2 证据不自动证明 V2 关联。

| 能力 | 核心实现 | Hermes 真平台 V2 | OpenClaw 真平台 V2 | CodeBuddy 真平台 V2 | 证据 |
| --- | --- | --- | --- | --- | --- |
| IntentContract schema | evidenced | n/a | n/a | n/a | Go 固定向量 + `test_intent_v2_contracts.py` |
| Trusted Intent Issuance | evidenced | n/a | n/a | n/a | `intent_http_test.go` 管理权与 Decision token 403 |
| Session Intent Binding | evidenced | unverified | unverified | unverified | `intent/store_test.go` 并发唯一、过期、重启 |
| Intent Runtime Enforcement | evidenced | unverified | unverified | unverified | `receipt/intent_test.go` 交集、省略、替换、主体伪造 |
| Decision/Observe Correlation | evidenced | unverified | unverified | unverified | `receipt/action_state_test.go`；Hermes 13 项单测；OpenClaw mock hook 测试 |

CodeBuddy 有 tool_use_id 时由服务端按身份和 ID 定位；无稳定 ID 时只允许参数一致且唯一的候选，歧义拒绝。
本轮未声称 effect 实际发生已验证。单绑定性能记录：[local-20260907.json](evidence/intent-v2/local-20260907.json)。

### V2 补齐增量（20260907-164919）

核心资源规范化、可信 Principal / resource_refs / provenance_refs、任务边界恢复、同会话并发和进程强杀恢复已有本地证据，见 [trusted-intent-v2-progress-20260907-164919.md](trusted-intent-v2-progress-20260907-164919.md)。绑定查找已改为确定性 ID 直接读取，实测覆盖 1 / 128 / 1024 / 4096 个绑定。新增字段预留不代表 Provenance DAG；这些核心证据不提升任一真实平台 V2 列。

2026-09-07 19:10 新增 [Hermes 原生工具分发器集成证据](trusted-intent-v2-native-validation-20260907-191006.md)：实际插件加载、pre/post、合成文件读写、HTTP 签名回执、失联阻断和重启恢复通过。调用标识由测试提供，未驱动完整 LLM 会话或 hold/审批；该证据不等于全部平台 V2 验收，因此上表综合状态保持 `unverified`。

2026-09-07 19:25 新增 [OpenClaw 安装与原生工具链证据](trusted-intent-v2-openclaw-validation-20260907-192539.md)：Go 安装输出通过真实加载器验证，原生 before wrapper / Pi 文件工具 / after relay 连接实际 HTTP 通过。清单、插件加载注册和重装卸载修复已有回归；完整会话和审批未验收，综合状态不升级。

2026-09-07 19:47 新增 [持续运行与旧 Hermes 兼容证据](trusted-intent-v2-soak-and-compatibility-20260907-194732.md)：32 会话/600 秒/六次强杀恢复，24h 边界回归，以及未修改的历史 Hermes 适配器通过。持续 HTTP 负载不是完整平台会话，历史源代码测试不是发布制品验收，平台综合状态保持 `unverified`。

上一批 `0f232f4` 的远端 CI 已通过；本轮远端 CI 需按对应新 SHA 单独验证，结果以 GitHub Actions 运行记录为准。
