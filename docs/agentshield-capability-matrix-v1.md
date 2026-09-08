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

2026-09-07 20:04 新增 [Hermes 完整会话与 CI 证据](trusted-intent-v2-conversation-validation-20260907-200400.md)：原生 Agent 生成会话 ID，实际 SSE 模型协议驱动 pre/post；两个会话、三轮对话、六次工具调用及八条回执通过。已覆盖跨轮固定绑定、动作链和新会话不继承权限；模型与管理操作者为合成测试，平台审批和其他平台完整会话仍未完成，综合列保持 `unverified`。`3d1a9b5` 的完整远端 CI 28 个 job 全部成功，本轮新增测试脚本的本地证据单独归档。

2026-09-07 20:16 新增 [OpenClaw 完整 CLI 会话证据](trusted-intent-v2-openclaw-conversation-20260907-201600.md)：真实 `agent --local` 四轮命令、十次 SSE completion、六次工具调用及八条回执通过；实际 post hook、跨进程续聊和新 explicit 会话隔离已验证。该路径不含网关审批与同 key reset，综合列仍为 `unverified`。

2026-09-07 20:36 新增 [OpenClaw 空闲重置失败证据](trusted-intent-v2-openclaw-idle-reset-20260907-203600.md)：同 key 的 SIQ 绑定、动作链和污点保持，原生 UUID 轮换后却继续使用旧 transcript。报告 `passed=false`、`siq_invariants_passed=true`，进程退出码 1；不得把这份归档作为完整重置通过证据，综合状态继续 `unverified`。

2026-09-07 20:42 新增 [OpenClaw 临时补丁副本证据](trusted-intent-v2-openclaw-reset-patch-20260907-204200.md)：指纹限定补丁通过相同空闲重置测试，并保留正常续聊及 SIQ 安全状态。本机原版未更新；不能把该副本的 `passed=true` 归于原版或视作上游已修复，综合状态不升级。

2026-09-07 21:11 新增 [原生审批执行失败证据](trusted-intent-v2-native-approval-gap-20260907-211105.md)：实际网关/审批 WebSocket/前置包装器下，平台允许但本地未批准或已拒绝时，合成执行器仍被调用。Observe 拒绝发生于执行之后；两个门禁场景失败，综合 `unverified` 保持，不能宣称本地 hold 已在平台执行前强制生效。

2026-09-07 21:33 新增 [执行前审批修复证据](trusted-intent-v2-approval-gate-validation-20260907-213332.md)：当前工作树先等待本地批准，再进入平台审批；六个原生夹具场景及十二条回执恢复验签通过。21:11 原失败归档保留；真人流程、平台等待期间授权变化与综合平台验收仍未完成，不升级综合状态。

2026-09-07 21:51 新增 [原生网关重置与新 SHA CI 证据](trusted-intent-v2-gateway-reset-and-ci-20260907-215104.md)：原生 `sessions.reset` 拒绝只读调用；管理调用归档旧内容并重建活动会话，随后本地 CLI 模型请求无旧工具结果，SIQ 安全状态保留，13 条回执验签通过。`87fd1ce` 的 28 个 CI job 均成功。手动 RPC 成功不覆盖渠道 reset 或原版空闲重置故障，综合状态继续 `unverified`。

2026-09-07 22:00 新增 [平台等待期间撤销验收](trusted-intent-v2-approval-revocation-20260907-220037.md)：原版在 Grant 已撤销、hold-status 明确 denied 后仍执行，原版报告 `passed=false`。配套宿主/适配器候选在临时副本通过八个场景，撤销后执行和 observation 均为零；默认组合未更新，不能提升其支持等级，也不能把检查点外推为原子执行租约。

2026-09-07 22:08 新增 [候选检查点故障证据](trusted-intent-v2-checkpoint-faults-20260907-220834.md)：九个原生场景通过，包含真实参数摘要拒绝与审批后 daemon 失联，19 条回执恢复验签通过。仅正常对照执行；默认安装未采纳配套候选，综合状态仍为 `unverified`。

2026-09-07 22:18 新增 [宿主能力识别与当前适配器集成](trusted-intent-v2-approval-integration-20260907-221813.md)：源码及内嵌资产已提供审批后检查；缺能力宿主明确阻断 hold，配套 v2 宿主正常审批、撤销及故障均通过，原生合计 18 场景。真实安装未更新，配套宿主非官方能力，旧版本不记为无缝兼容，综合等级不升级。

2026-09-07 22:36 新增 [宿主升级/回退证据](trusted-intent-v2-checkpoint-upgrade-20260907-223635.md)：固定指纹工具通过 15 项恢复/拒绝测试，完整副本经真实 CLI 升级后验证批准与撤销，经回退后验证新进程缺能力拒绝。仅验证 POSIX 文件级操作和新进程，未升级实际安装或证明真实会话迁移，综合状态不变。

2026-09-07 23:11 新增 [CodeBuddy 原生 CLI 与隔离配置验收](trusted-intent-v2-codebuddy-validation-20260907-231146.md)：Linux 上腾讯 `@tencent-ai/codebuddy-code@2.146.0` 的真实安装/重装/卸载、8 次 CLI 会话调用、19 次 SSE、11 次工具调用与 13 条回执通过。当前适配器 pre/post 关联、资源拒绝、续聊/新会话、强杀/pending 恢复、optional 边界取得限定版本证据；配置覆盖已覆盖 CLI 与管理 API。GUI、hold/redact、历史适配器制品及其他 OS 未因此完成，综合状态仍为 `unverified`，代码仍为 experimental。

2026-09-07 23:25 新增 [CodeBuddy 初始化故障原生复现与修复](trusted-intent-v2-codebuddy-bootstrap-fix-20260907-232551.md)：修复前退出码 1 导致非阻断执行；修复后 10 个场景、七条 pending 幂等提升与 11 条回执验证通过。正常 CLI 全链回归另有 13 条回执。该证据仅覆盖钩子可启动并输出 JSON 的初始化故障，不覆盖二进制缺失/强杀/宿主超时；综合状态不提升。

2026-09-07 23:56 新增 [旧版兼容与升级恢复证据](trusted-intent-v2-legacy-upgrade-20260907-235638.md)：旧 OpenClaw/CodeBuddy 执行授权通过，但无 ID/参数的 post 没有产生关联观察，报告 `passed=false`。保留同一状态升级到当前适配器后，重复读取和重启恢复的关联观察通过，两平台各 14 条回执验签成功。此结果证明指定版本的迁移路径，不将旧版完整兼容或综合支持状态提升为通过。

2026-09-08，[最终工程验收](trusted-intent-v2-final-audit-20260908-000506.md) 按原文 T15 核对三平台原始基线 optional Grant/unbound 兼容；旧 post 完整兼容与平台综合支持仍保留独立限制。新增 [Hermes 原始基线复测](evidence/intent-v2/legacy-hermes-baseline-20260908.json) 与 `2305979` 的 28/28 CI 证据，未变更平台支持等级。

## Provenance-Bound Effect V1 组件覆盖（2026-09-08）

以下状态只表示当前开发分支组件，不更改上文平台综合支持等级，也不继承旧版native测试来证明新增V3采集能力。

| 能力 | 已实现/验证边界 | 尚未证明 |
| --- | --- | --- |
| Authority Hard Gate | 无效必需Authority三模式拒绝、普通策略advisory兼容，本地Go回归 | 当前分支全仓远端CI及全部native回归 |
| Trusted Context | admin签名workspace与请求绑定，Grant/Intent不被扩大 | 外部attestor部署、恶意同UID隔离 |
| Parameter Provenance / Intent V3 | issuer/图签名、scope/期限/撤销、最低父trust、参数摘要和默认高影响约束；实际MCP组件流程 | 各平台自动捕获/传播完整来源，模型隐式推理lineage |
| 文件效果与Completion | 实际前后快照、签名材料、要求摘要/历史动作；host_independent/partial | OS级独立观察、所有写路径强制经过observer、完整业务语义 |
| 网络效果 | 受控loopback服务器接收事件、重定向最终端点与签名要求核对 | 公网provider审计、全平台每跳拦截、签名网络无效果证明 |
| Pending恢复 | admin显式接管、原deadline、历史撤销、并发/容量/篡改；两次真实Linux SIGKILL重启 | 断电及文件系统故障矩阵、原生自动调度、状态目录回滚隔离 |
| Benchmark | 20对组件场景，公共回执/效果离线签名验证，显式D0–D5分母 | D0/D1、完整独立效果覆盖、全局Intent撤销等完整场景语义及原生强制执行 |
| 性能 | 八阶段各100个暖态顺序样本与P50/P95/P99，原始数据及源码摘要 | 生产SLA、冷启动/饱和并发、全攻击与深图性能矩阵 |
| CI与治理 | PR/nightly工作流、恢复/性能报告步骤、CODEOWNERS源码规则 | 新工作流远端执行结果；CODEOWNERS不能单独证明main保护已强制 |

复现入口与限制见[benchmark说明](../benchmarks/runtime-security/README.md)、[威胁T27–T35](threat-model.md)和[开发台账](provenance-bound-effect-v1-progress.md)。未修改GitHub Ruleset；main protection仍需发布前独立核验，不把源码审阅路由当作仓库管理设置已启用的证据。
