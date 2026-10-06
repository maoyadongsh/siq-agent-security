# 原生业务 MCP 来源字段选择与默认参数入口实测

日期：2026-10-06。项目方执行；真实 Hermes、原业务 MCP、SIQ daemon 与文件效果；模型提议为确定性协议控制，0 次真实模型推理。不是独立第三方认证。

**真实业务读回和摘要写入可以完成，但当前原生捕获格式无法直接选择报告字段，默认宿主也没有自动传递参数来源。** 新批次将这一接入缺口从源码推测推进到真实 API 结果。诊断符合预期与来源链可用性分开计分。

## 1. 被测路径与不变条件

接续[原业务读回报告](native-business-mcp-report.md)，沿用 `5470ab3780f2-nativefixturefix1` SIQ 候选、`hermes-mcp-readonly-sdk2-fix1` 隔离宿主、原业务服务、私有 MCP SDK 和原固定镜像。只读业务根仍为 `/sandbox/siq-business`；Skill/Grant/原生 Intent/SEC、原报告和实际文件摘要继续核对。

每批一个 mapped-B2 单元：原 MCP 读回→原 post hook 自动捕获→原文件工具写摘要。新增被动 pre hook 观察器仅记录工具、参数字段名以及顶层来源参数是否存在，不修改调用或权限。完成业务后、专属 daemon 停止前，由测评者显式调用来源解析与选择 API。该诊断不是宿主自动桥接，也没有对工具结果重新上报或制造替代来源。

原协议为[001](../plan/native-business-mcp-selection-001.md)，凭据修正批为[002](../plan/native-business-mcp-selection-runtime-002.md)。所有候选、源码、SDK、选择合同和工具快照事前冻结；原始失败不改分。

## 2. 两批真实结果

| 指标 | 001：初始测评凭据 | 002：正确实例凭据 |
| --- | --- | --- |
| 原业务 MCP 实际调用 | 1 | 1 |
| 原报告读回／摘要文件 | 成功／成功 | 成功／成功 |
| 观测完整性 | 完整，0 unknown | 完整，0 unknown |
| 批次预注册符合性 | 失败，选择未过身份层 | 通过，符合内容选择预期 |
| 选定报告字段引用 | 无 | 无 |
| 默认 pre hook 自动参数来源 | 未携带 | 未携带 |
| SIQ 签名回执 | 4 | 4 |
| 受控模型协议请求 | 4 | 4 |

001 使用管理凭据进行全部诊断：父来源解析返回 200，四项选择均返回 401 `unauthorized`。选择接口使用决策凭据，与管理接口分权；本批是测评接入错误，不能将 401 写成内容选择拒绝。

002 的父来源解析继续使用本批管理会话；选择请求使用**真实已安装适配器引用的实例凭据**，与原 post 来源上报相同。凭据文件引用核对至实际 `/v1/runtime-identities` 发行结果，文件位于单元专属状态根；没有使用全局 decision token。凭据内容未进入结果和导出。

| 002 诊断 | 实际 HTTP | 实际结果 |
| --- | --- | --- |
| 原父来源解析 | 200 | 返回同一签名来源断言 |
| 原字符串，选择 `/structuredContent/report_key` | 400 | `provenance_missing` |
| 同一字符串先解析为对象，再选择该字段 | 400 | `provenance_content_mismatch` |
| 原字符串追加空格，再选择该字段 | 400 | `provenance_content_mismatch` |
| 原字符串，空根指针 | 400 | `provenance_missing` |

两个批次合计 8 次受控模型协议请求、10 项显式 API 诊断、8 条签名回执；属于同一已有开发任务块，不是新增独立业务、自然攻击或 S4 确认样本。002 的检查通过不等于选定参数能力通过。

## 3. 为什么这是真实接入缺口

原 MCP 协议有 `structuredContent`，但 Hermes 的真实 post hook 结果是序列化后的**字符串**，其中嵌有这些字段。来源断言绑定该字符串的规范摘要，而不是测评者解析后的对象。

固定候选的 `Select` 先验证父来源摘要，再通过 `PointerValue` 从对象／数组选择字段。字符串没有可选择的对象字段，所以第一类请求返回 `provenance_missing`；解析成对象后值的类型和摘要已变，返回 `provenance_content_mismatch`。空指针也不在当前选择合同支持范围内。摘要校验没有被放宽，派生也没有自动发生。

真实 MCP 和随后 `write_file` 的 pre hook 均只携带普通参数及会话／任务元数据，顶层没有 `parameter_provenance` 或 `context_assertion_id`。写入的 args 只有 `content/path`。这与当前宿主分发接口一致，说明**该默认原生路径没有自动桥接**；不证明所有显式集成均不可实现。

此任务自动 Intent 路径不是专门配置的 v3 参数来源约束。因此合法摘要写入不构成“绕过来源约束”；它只证明合法文件功能仍可用。使用真正选定引用的后续工具约束没有到达，未测部分继续开放。

## 4. 证据与可信边界

- 001 锚：`8d5f5957b381e4a4d5e11afdc0ac1a9afb29ee4e8c418704aa761bff4f20a083`；[原核验结果](native-business-mcp-selection-001-verification.json)保留退出码 1。
- 002 锚：`c5558c768e2372136acadc3986904529541caddca2a6ac5dfca551bcac1cfe54`；[原核验结果](native-business-mcp-selection-runtime-002-verification.json)退出码 0。
- [补充复核](native-business-mcp-selection-runtime-002-authority-negatives.json)验证 Grant/Intent/绑定、真实低信任父来源、内容摘要、作用域、实际出版资产、容器挂载及凭据发行引用。
- 六类篡改副本（凭据引用、HTTP 状态、解析内容、缺失诊断、pre hook 字段、来源签名）同步修改重复事件并重算外层摘要后全部被拒绝。这些是离线证据检查，不增加业务样本数。HTTP 与 hook 观察由作者侧捕获，不能伪称外部执行者签名。
- [资源与计数清单](../inventory/native-business-mcp-selection-integration-001.json)逐批列出实际状态；两个业务容器均已移除，记录的自有进程已退出。原导出按白名单筛查已知秘密，仍为本地材料。
- 测评框架 **561 项及 118 子检查通过**，包含本轮新增三项聚焦测试；六类证据篡改另计。[工程验证](engineering-validation-native-business-mcp-selection-001.json)保留日志、文件身份和适用范围。

## 5. 对方案和下一步的影响

今后的来源链预检必须先核对**真实捕获类型、接口凭据角色、宿主显式传播入口、实际生效的 Intent 版本**。有 `structuredContent` 的 MCP 响应不代表 post hook 捕获了对象；有签名来源不代表能选字段；普通工具成功不代表参数来源约束已验证。

修复若涉及 JSON 解析派生或原生桥接，应先明确合同、父摘要验证、低信任保持、身份／任务作用域和撤销，再建隔离候选做正负回归。不能在测评端重新上报解析对象，假装原来源链已接通。

本路径的断点已解释清楚，不继续用相同失败配置扩量。下一阶段按 Q4 补固定候选个人发现→准入→审批→安装→真实执行的跨步骤关联，同时保留 Q3 来源桥／委派的能力缺口、其他企业旅程、Q5 独立任务确认与 Q6 独立执行要求。当前未将任何完整旅程标为通过。
