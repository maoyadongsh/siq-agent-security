# Trusted Intent Authority & Action Binding V2：逐项工程验收

- 核对日期：2026-09-08，Asia/Shanghai。
- 产品代码基线：`2305979dd2d6b3d58390d888756a6ffb45b86a98`；本批只增加兼容性复测、证据及文档。
- 要求来源：用户提供的《SIQ Agent Security — Trusted Intent Authority & Action Binding V2》§0–52，原始基线 `0caacd3bd678051f80efb2737ea26a0c76f96a97`。
- 结论：以下原始工程要求已有对应实现与证据。旧版 optional **授权协议兼容**按原文 T15 判定；缺失身份信息的旧 observation 仍拒绝，不宣称完全保留旧版不安全行为。生产就绪、任意平台版本和独立安全审查不由本验收替代。

## 1. 纠正兼容性验收口径

此前“约 94%”将 DoD 13 扩展成“所有旧 post 均应无缝产生成功 observation”。重新核对原文后，T15 实际要求为：

> `intent_enforcement=optional`；旧平台请求仍可执行原 Grant 逻辑；Receipt：`intent_binding=unbound`。

原文 §24–25 同时明确要求 Observe 证明合法前置 Decision；§31 要求无法可靠关联时诚实标记 `unverified`。因此，本次分别检验授权协议兼容与观察关联能力，而不为通过旧版测试放宽关联规则。该判断依据原始具体测试要求，不以当前实现反向定义完成条件。

| 平台及原始基线 | optional 授权兼容（T15 / DoD 13） | 旧版观察关联 | 当前适配器 / 迁移证据 |
| --- | --- | --- | --- |
| Hermes，`0caacd3` 的未修改插件 | 通过：原生加载、Grant 授权、unbound 回执 | 该版本透传稳定调用 ID，原生 pre/post 通过 | [本轮完整历史基线复测](evidence/intent-v2/legacy-hermes-baseline-20260908.json)：14 条回执，含 bound/optional/required、失联、重启与观察重放 |
| OpenClaw，`0caacd3` 的未修改插件入口 | 通过：实际 before wrapper 和文件工具；无授权拒绝，optional 按 Grant 允许，回执 unbound | 缺调用 ID 和原参数，拒绝，完整旧 post 兼容未达到 | [旧版与升级对照](evidence/intent-v2/legacy-openclaw-upgrade-20260907.json)：7 个旧版场景、4 个升级场景，14 条回执验签 |
| CodeBuddy，完整 `0caacd3` Go 模块构建的 hook | 通过：真实 CLI pre hook、Grant 授权、unbound 回执 | 旧 HTTP Observe 清空参数且不传调用 ID，拒绝 | [旧版与升级对照](evidence/intent-v2/legacy-codebuddy-upgrade-20260907.json)：11 次原生 CLI、22 次本地模型请求，14 条回执验签 |

OpenClaw/CodeBuddy 原始归档的 `passed=false` 保留：其检测对象是**完整旧版观察兼容**，不能被覆盖为通过。`authorization_checks_passed=true` 对应 T15；`upgrade_recovery_passed=true` 证明升级后同一状态/会话的关联观察恢复。完整方法、配置隔离桥接、真实组件与完整 CLI 的差别见 [迁移复测报告](trusted-intent-v2-legacy-upgrade-20260907-235638.md)。本次也不声称覆盖未指定的所有历史版本。

## 2. 原始 17 项 DoD

下列 Go 路径相对于 `apps/agentshield/internal/`；Python 路径相对于 `apps/control-api/app/tests/`。核对包含测试断言和实际实现，不以存在同名文件作为完成证据。

| DoD | 实现与直接证据 | 结论 |
| --- | --- | --- |
| 1 管理/决策分权 | `server/intent_http.go` 使用管理路由；`TestIntentManagementRequiresAdmin` 对 GET/POST 验证原始 decision bearer 返回 403 且 Store 未创建记录；新增撤销路由也覆盖 401/403 | 通过 |
| 2 拒绝 inline authority | `receipt.Engine.Decide` 及 HTTP 输入边界拒绝 inline Intent；`TestDecideRejectsInlineIntentAuthority`、`TestIntentAdminLifecycleAndRuntimeRejection` | 通过 |
| 3 复用签名基础设施 | `intent/store.go` 调用既有 `canon`/`signing`；`TestFixedIntentVector` 与 Python 独立 canonical/digest/Ed25519 验证 | 通过 |
| 4 immutable/versioned | 新建 V2 schema 保留 V1；同 ID 改内容拒绝，相同内容幂等；同目录完整文件排他发布；`TestStoreIntegrityAndImmutability` | 通过 |
| 5 受信绑定 | 管理 POST/GET/list 生命周期；完整平台/session/agent 生成绑定身份；`TestBindingAuthorityAndConcurrency` 的错误身份、task、冲突、16 并发与恢复断言 | 通过 |
| 6 绑定后不降级 | Store 每次验签解析；拒绝回执保留绑定；`TestBoundSessionCannotDowngradeOrSwapIntent`、`TestDowngradeDenialDoesNotEraseRecoveredBinding`；撤销前首个决定与 optional 重启负向 | 通过 |
| 7 tools/effects 分离 | `runtimeaction.Normalize` 与 `intent.Authorize` 分别检查工具、效果；opaque shell 保留 unknown 并拒绝；`TestNormalizeSeparatesToolOperationAndEffect`、`TestShellCannotClaimExhaustiveEffects` | 通过 |
| 8 资源真正授权 | 结构化 domain/operator/value；规范化后逐项匹配；`TestV2ConstraintAuthorization`、共享 matcher 向量、三平台目录越权执行测试 | 通过 |
| 9 受限参数路径 | RFC 6901 路径、数组下标、转义；严格数值 equality、one_of/prefix/suffix/RE2；`TestSharedMatcherVectors`、`TestExactJSONNumbers`、非法指针/表达式测试 | 通过 |
| 10 可信回执字段 | `receipt/engine.go` 从可信状态生成 task/intent/digest/revision/binding/action/reason；`TestV2TrustedStoreGrantIntersectionAndHints` 检查字段及篡改后验签失败 | 通过 |
| 11 Observe 合法前置 | `resolveAction` 验证七类身份、前置动作和 hold 管理批准；`TestObserveRequiresAuthorizedDecision`、`TestObserveHoldRequiresManagementResolution` | 通过 |
| 12 deny 无成功观察 | 同上验证 `observation_action_not_authorized`；原生拒绝场景无工具副作用/成功观察；撤销后的 deny 也不能观察 | 通过 |
| 13 旧 optional 兼容 | 本文第 1 节三平台原始基线证据，按 T15 的 Grant/unbound 语义判断；旧 post 缺信息仍拒绝 | 通过 T15；完整旧 post 兼容不作承诺 |
| 14 required 缺绑定拒绝 | `TestRequiredIntentEnforcementFailsClosedWithoutBinding`、原生未绑定新会话；稳定 `intent_binding_missing` | 通过 |
| 15 原安全逻辑无退化 | Grant/路径/出网/secret/taint/trifecta/审批/历史链完整回归；`TestLethalTrifectaDenied` 等正负向断言仍通过 | 通过 |
| 16 Go race | 产品提交前 `go test -race ./...` 全模块通过；未把远端普通测试说成远端本模块 race | 通过 |
| 17 全仓 CI | `2305979` 的 [CI](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34140323805) 28/28 成功；[原始元数据](evidence/intent-v2/ci-2305979-20260907.json) 精确校验 head SHA。后续文档/测试提交以其 Actions 结果为准 | 产品基线通过 |

## 3. §0–52 与命名工作包/交付物覆盖

| 原始章节 | 已核对的产物和行为 |
| --- | --- |
| §0 基线 | main 包含指定 `0caacd3`；当前提交 `2305979` 已推送。Admission/Grant/签名链/OpenShell/适配器未删除，完整现有测试随 CI 执行 |
| §1 最终数据流 | 管理签发→不可变 Intent→绑定→动作规范化→授权交集→签名决定→关联观察；见主工程报告 Architecture |
| §2 inline 自授权 | HTTP 与 Engine 两层拒绝；runtime 请求没有隐式 Issue 路径 |
| §3 工作包 A | 独立 `internal/intent/{types,validate,store,matcher,binding}.go`；receipt 的 `ResolveStore` 只消费解析结果 |
| §4 工作包 B | `packages/contracts/intent-contract.v2.schema.json`；原 V1 保留；principal/agent/authority、时间、资源与参数均结构化 |
| §5 工具/动作/效果 | tool、operation、effects 独立字段和验证；curl 线索不会代替完整效果证明 |
| §6 效果词表 | `runtimeaction/normalize.go` 的十个冻结效果与 unknown；未知效果不被猜测成允许 |
| §7 ActionEnvelope | `runtime-action-envelope.schema.json`、独立 runtimeaction 包、固定向量；服务端生成 action_id，不采用调用者自报 ID |
| §8 资源约束 | equals/one_of/prefix/suffix/host/cidr/regex 的结构与匹配；路径边界、host 规范化、1024 字节 RE2 限额及非法表达式拒绝 |
| §9 参数约束 | 受限 JSON Pointer 而非 JSONPath；Host 使用固定 ASCII/Punycode 输入约定，路径要求显式绝对语义；共享向量及大整数比较回归 |
| §10 工作包 C | 状态目录 intents/intent-bindings；追加式签名记录；复用 canonical、digest、Ed25519，不引入另一签名体系 |
| §11 管理 API | POST/list/GET `/v1/intents` 全部在 capAdmin 路由；decision token 403 |
| §12 创建主体 | 管理会话签发；runtime 只请求决定；签名记录同时构成不可变签发审计事实 |
| §13 Evidence IDs | 本地记录存在性与 ID 一致性；显式 `external:https://...` 引用格式验证；`ev-made-up` 被拒绝。外部引用不是内容真实性认证 |
| §14 工作包 D | Binding 绑定平台/session/agent、task/intent/digest/revision、时间与签名；原记录不能重绑覆盖 |
| §15 Binding API | POST/list/GET 和新增 revoke/readback；撤销为独立签名 sidecar，不改原绑定；严格期望 digest，重复撤销幂等 |
| §16 服务端解析 | `IntentLookup`→`ResolveStore`，每次从受信状态解析；client intent/task/principal 仅校验，不可选择替代 authority |
| §17 降级 | 省略 hint 仍解析原绑定；binding 消失/变更、撤销不回到 Grant-only；污点与已绑定安全状态不清空 |
| §18 optional/required | optional 无绑定沿用 Grant 并显式 unbound；required 缺绑定 deny；三平台原生与 Go/HTTP 测试 |
| §19 审计模式 | intent_enforcement 与 enforcement_mode 独立；warn/audit 仍计算拒绝，签名 advisory_action 与 reason_code，不伪称阻断 |
| §20 工作包 E | `reason_code` 进入 API/回执，区分 Grant、Intent、unknown、taint/trifecta；业务负向主要按代码断言 |
| §21 工作包 F | task/intent/digest/revision/binding/reason/action 纳入签名字节；元数据篡改验签失败 |
| §22 Receipt 兼容 | 采用可选字段方案；`TestReceiptBeforeOptionalMetadataStillVerifies`、固定历史样例与 Python schema 验证；不重签历史文件 |
| §23 digest 回链 | 回执保存标识/digest/revision，不内嵌完整 Intent；管理 GET 读取原不可变授权 |
| §24 工作包 G | Observe 带 action/decision_receipt/tool_call 标识；旧请求只能在可靠唯一匹配时关联 |
| §25 观察规则 | 平台/session/agent/tool/call/action 一致；allow/redact 或经本地管理批准的 hold；deny 不接受 |
| §26 幂等 | 同动作相同结果返回已有回执；冲突返回结构化错误；12 并发及重启重放无重复 observation |
| §27 最小行为链 | 服务端 task_seq 与 parent_action_id，批准/拒绝及任务边界处理；32 同会话并发、晚到结果和重启测试 |
| §28 Receipt 可解释性 | principal、任务、authority/grant、operation/effects、资源摘要、reason/facts/rules 和关联观察；无可信 principal 的 unbound 不伪造身份 |
| §29 工作包 H | 三平台薄事件映射；不持签名密钥、不执行 Intent 解释或授权判定 |
| §30 OpenClaw | 当前 pre/post action/receipt 关联；2048 项、300 秒 TTL、重复 ID 冲突拒绝；安装资产与源码一致性回归 |
| §31 Hermes/CodeBuddy | Hermes 同类有界关联；CodeBuddy 跨 hook 进程传递 tool_use_id，由 daemon 关联；缺 ID 时不宣称可靠效果证据 |
| §32 工作包 I | T1–T16 映射见下一节；核心安全负向及原生运行证据已核对 |
| §33 Schema tests | 三类合同的有效/缺字段/未知字段/非法时间、签名/摘要篡改、操作符、JSON Pointer 测试；schema 验证形状，Go 校验 RE2/时间窗/证据，密码验签单独检查，不把格式验证当作授权 |
| §34 固定向量 | Go canonical bytes/digest/signature 样例，Python 独立验签；新增 Binding revocation 固定向量同样跨语言验证 |
| §35 Provenance 预留 | 仅有界签名 provenance_refs；未建立参数传播图，符合本轮排除范围 |
| §36 不开发行为沙箱 | 保留既有 OpenShell，不新增 shadow execution/sandbox orchestration/effect replay |
| §37 不开发委派 DAG | 仅 principal/agent/task/revision；没有将预留元数据宣称成委派系统 |
| §38 无 LLM authority | Issue/Authorize 热路径无模型调用；purpose 仅解释；结构化约束确定性匹配 |
| §39 稳定理由代码 | Intent Violation、CorrelationError 与 runtime reason 分类；重点 negative 测试断言代码 |
| §40 性能 | 本地直接定位文件与验签，无远程 lookup；1/128/1024/4096 绑定分档及 HTTP P50/P95/P99、600 秒有界负载记录；无虚构 SLA |
| §41 容量 | Store 各类4096、action 8192/24h、适配器2048/300秒；过期不清除 bound/tainted 状态；满额拒绝及 TTL 边界测试 |
| §42 并发 | binding/同会话动作/重复 call ID/并行 Observe/race；签名撤销与 Decide 有确定 snapshot 顺序、原生70回执和撤销返回后32次请求全拒绝 |
| §43 威胁模型 | `docs/threat-model.md` T23–T26 的威胁→控制→负向→残余风险；补齐已实现撤销与旧观察兼容边界 |
| §44 能力矩阵 | schema/issuance/binding/enforcement/correlation 分列；平台证据有版本/范围，综合 unverified 不因本专项完工自动升级 |
| §45 诚实边界 | desktop-same-uid 明确不提供恶意同 UID 强隔离；管理分权不替代系统权限边界 |
| §46 代码组织 | intent/runtimeaction/receipt/state/server 分层；具体文件名按原文允许的仓库结构调整 |
| §47 授权流程 | Engine 从受信绑定取得合同，与 Grant 和运行时状态相交；动作/回执在执行前生成，Observe 在后关联 |
| §48 授权公式 | block 下必须 GrantAllows ∧ IntentAllows ∧ RuntimeStateAllows；required 缺 Intent 不退回 Grant；warn/audit 按 §19 保留 would-deny |
| §49 DoD | 本文第 2 节逐项核对，兼容范围按原始 T15 明确解释 |
| §50 提交策略 | Git 历史已拆分 contracts 与实现，例如 `99b6233` / `2305979`；未合并成单个巨大变更 |
| §51 工程报告 | 主报告包含 Architecture、Trust Boundary、Changed Files、Security Invariants/Negative Tests、Compatibility、Performance、CI、Residual Risks；当前状态更新而历史报告保留 |
| §52 下一阶段 | 参数 provenance、完整行为图、真实效果证明、行为沙箱、委派和更广对抗 fuzzing 留待新阶段，不在本轮宣称实现 |

## 4. T1–T16 负向测试与实际证据

| 原始测试 | 直接证据 |
| --- | --- |
| T1 inline 注入 | `TestDecideRejectsInlineIntentAuthority`、HTTP inline 400 |
| T2 required 无绑定 | `TestRequiredIntentEnforcementFailsClosedWithoutBinding`、三个原生平台新会话拒绝 |
| T3 bound 降级 | `TestBoundSessionCannotDowngradeOrSwapIntent`、拒绝回执重启恢复 |
| T4 选择其他 Intent | 上述测试与 `TestV2TrustedStoreGrantIntersectionAndHints` 的 intent hint/task hint 子项 |
| T5 篡改 | `TestStoreIntegrityAndImmutability` 的 digest/signature 子项；固定向量独立验签 |
| T6 到期 | `TestBindingAuthorityAndConcurrency` 的已签过期绑定；`TestIntentContractRejectsExpiredOrDifferentAgent` |
| T7 Grant 允许、Intent 拒绝 | `TestV2TrustedStoreGrantIntersectionAndHints` 参数子项、原生 company-b/prefix-collision/Write 拒绝 |
| T8 Intent 允许、Grant 拒绝 | 同测试 grant denies 子项返回 `grant_scope_violation` |
| T9 工具/效果分离 | `TestV2ConstraintAuthorization` 的 Bash/curl；`TestShellCannotClaimExhaustiveEffects` 明确 unknown 拒绝 |
| T10 资源约束 | 同上目录允许与 company-b/company-a-evil/相对路径/逃逸拒绝；共享向量和真实文件工具 |
| T11 principal 冒充 | `TestV2TrustedStoreGrantIntersectionAndHints` 返回 `intent_principal_mismatch`，签名元数据不能由 params provenance 覆盖 |
| T12 无 Decide 的 Observe | `TestObserveRequiresAuthorizedDecision` 返回 `observation_decision_missing` |
| T13 deny 的 Observe | 同测试返回 `observation_action_not_authorized`；revoked deny 亦拒绝 |
| T14 冲突 Observe | `TestObserveIdempotencyConcurrencyAndRecovery` 返回 `observation_conflict`；重复相同结果恢复后仍相同回执 |
| T15 旧 optional | 本文第1节三个原始基线运行，决策采用 Grant，回执 unbound；此项不允许把无法关联的 post 伪造为有效观察 |
| T16 原 trifecta | `TestLethalTrifectaDenied`、`TestTaintedEgressDenied` 与完整 receipt 回归 |

## 5. 复核命令与剩余边界

已执行的产品检查：`apps/agentshield` 内 `go test -race ./...`、`go vet ./...`、gofmt 检查及四目标构建；Control API 的 `test_intent_v2_contracts.py` 和 `test_schema_contracts.py` 合计120项；相关 Ruff。全仓 CI 覆盖 Control API、Web、Edge/Connector 双 Go 版本、本地二进制、安全静态检查。新兼容脚本 Ruff 与原生运行、归档源码指纹和文档链接已单独检查。

当前工程验收不消除下列已知限制：同 UID 读写状态/私钥；无 OS 原子 effect cancellation；撤销前已取授权快照的动作可完成；无参数传播图、委派 DAG、行为沙箱或真实外部效果独立验证；旧无身份 post 无法安全恢复来源；固定版本原生测试不覆盖所有 GUI、消息渠道、真人审批、操作系统和故障模型。OpenClaw 原版空闲重置及配套宿主补丁的结果继续分别归档，不能将临时副本成功归于用户实际安装。

独立安全复核与生产部署验收是后续发布工作。它们不能被开发自检冒充，也不应把本轮原文明确排除的未来系统无限加入工程任务，导致工程验收永远无法收束。
