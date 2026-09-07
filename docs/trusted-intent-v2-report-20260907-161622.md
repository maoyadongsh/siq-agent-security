# Trusted Intent Authority & Action Binding V2 工程报告

- 时间：2026-09-07，Asia/Shanghai
- 仓库：siq-agent-security；分支：main；工作基线：`0caacd3`
- 当前状态（2026-09-08 00:05）：原始 V2 工程要求已完成逐项核对，见 [最终工程验收](trusted-intent-v2-final-audit-20260908-000506.md)。产品基线 `2305979` 已推送且 28/28 CI 成功；三平台原始 `0caacd3` 适配器满足 T15 的 optional Grant/unbound 授权兼容。旧 OpenClaw/CodeBuddy 无法关联的 post 继续拒绝，升级恢复已有证据。此前约 94% 的估计包含了原文未要求的旧 post 无缝接受条件，现按 T15 与 §25 分别核对；生产/跨平台完整支持不随本专项验收升级。
- 本报告记录开发验证完成时的工作树快照；后续提交与推送状态以 Git 历史为准。未部署。
- 最新核对：[旧适配器兼容、升级恢复与进度口径](trusted-intent-v2-legacy-upgrade-20260907-235638.md)。原始失败记录保留 `passed=false`；升级成功不改写旧版本的完整兼容结论。
- 绑定撤销证据：[原生运行与并发记录](evidence/intent-v2/native-binding-revocation-20260907.json)。撤销保留原绑定和审计记录，撤销前已取得授权快照的动作仍可能完成；此机制不承诺原子取消已开始的副作用。记录中的提交号为测试工作基线，具体受测源码由 `source_sha256` 标识。
- 最新增量（2026-09-07 23:25）：[CodeBuddy 钩子启动失败绕过修复](trusted-intent-v2-codebuddy-bootstrap-fix-20260907-232551.md)。修复前配置/凭据/状态故障会令原生工具执行且无在线回执；修复后初始化失败仍输出结构化 pre/post 结果，完整配置验证失败按 block，有效告警配置保留 allow + pending。未覆盖二进制未启动、进程强杀与宿主超时，redact/hold 仍待原生验证。
- 最新增量（2026-09-07 23:11）：[CodeBuddy 原生 CLI 与隔离配置目录验收](trusted-intent-v2-codebuddy-validation-20260907-231146.md)。真实安装/重装、授前拒绝、可信授权、pre/post 关联、续聊与新会话隔离、强杀/pending 恢复、optional 边界和卸载对照通过；修复安装器忽略 CODEBUDDY_CONFIG_DIR，非法覆盖及跨实例卸载拒绝。固定版本 CLI 证据不扩展到 GUI、真人审批或整体 supported。
- 最新增量（2026-09-07 22:36）：[宿主升级、回退与中断恢复](trusted-intent-v2-checkpoint-upgrade-20260907-223635.md)。新增固定版本 inspect/apply/restore、私有备份、POSIX 锁与原子替换；15 项测试覆盖三个真实 SIGKILL 中断点并接入 CI。完整副本通过升级后的批准/撤销两场景、精确回退及回退后的缺能力拒绝；用户实际安装未操作。
- 最新增量（2026-09-07 22:18）：[宿主能力识别与适配器集成](trusted-intent-v2-approval-integration-20260907-221813.md)。通过原生 context 的协议版本区分可靠检查点，工具参数/event 不能自行声明支持；当前适配器直接用于原版拒绝、配套宿主正常审批、撤销及故障共 18 个场景。旧 v1 候选与原版需按升级边界处理，当前验证入口改为 `validate-openclaw-approval-integration.py`。
- 最新增量（2026-09-07 22:08）：[检查点故障与最终参数验收](trusted-intent-v2-checkpoint-faults-20260907-220834.md)。九个原生场景通过：异常、拒绝、非法返回、超时、取消、最终参数改写及审批后失联均不执行，正常批准仍执行。参数改写由真实 HTTP 返回 `hold_identity_mismatch`；19 条回执恢复验签通过，候选补丁和默认安装均未改动。
- 最新增量（2026-09-07 22:00）：[审批等待期间撤销与候选补丁](trusted-intent-v2-approval-revocation-20260907-220037.md)。原版在 hold-status 已返回 denied 后仍执行，失败归档六条回执验签通过；配套候选新增可等待、可否决的审批后检查点，六个既有审批场景及两个撤销对照均通过。本机安装及默认适配器未更新，候选不是原子执行租约。
- 最新增量（2026-09-07 21:51）：[原生网关重置与提交后验收](trusted-intent-v2-gateway-reset-and-ci-20260907-215104.md)。只读 reset 被拒绝且 Store 不变；管理 reset 归档旧 transcript、创建新会话头，后续模型请求旧工具结果为零，SIQ 绑定、序号和污点仍保留，13 条回执验签通过。源文件指纹与当前提交一致，新 SHA 的 28 个 CI job 全部成功；消息渠道路径及原版空闲重置故障仍未关闭。
- 最新增量（2026-09-07 21:33）：[执行前本地审批门禁修复](trusted-intent-v2-approval-gate-validation-20260907-213332.md) 新增只读、强身份关联的 hold 状态查询；本地批准后才进入平台审批。六个原生场景通过，包括双方批准、两侧拒绝、本地超时、平台取消和 daemon 强杀；12 条回执恢复验签通过。Go race/vet、四目标构建与 117 项 Python 合同测试通过。当前增量未提交，完整平台与独立验收仍未关闭。
- 最新增量（2026-09-07 21:11）：[原生审批执行缺口](trusted-intent-v2-native-approval-gap-20260907-211105.md) 已动态复现：平台允许时，本地未批准或已拒绝的合成工具仍执行，随后 Observe 被拒绝。四场景中两个执行门禁失败，报告 `passed=false`、七条回执验签通过；该缺口尚未修复，完整审批验收不能关闭。
- 最新增量（2026-09-07 20:59）：[提交后验收核对与剩余任务](trusted-intent-v2-acceptance-audit-20260907-205942.md)，按原始 17 项 DoD、工作包和附加要求核对证据。当前代码对应 CI 已成功；平台执行前批准与执行后 Observe 接受需分开验证，目标继续进行中。
- 最新增量（2026-09-07 20:42）：[OpenClaw 重置候选补丁验收](trusted-intent-v2-openclaw-reset-patch-20260907-204200.md)。版本/源码指纹限定的补丁已在独立临时副本通过正常续聊与真实空闲重置：旧历史结果从六条降为零，13 条回执验签及 SIQ 安全状态保留通过。本机原安装未更新，原版失败证据保留，不能据此提升原版平台状态。
- 最新增量（2026-09-07 20:36）：[OpenClaw 空闲重置验收](trusted-intent-v2-openclaw-idle-reset-20260907-203600.md)。真实等待空闲策略生效后，SIQ 绑定、动作链、污点和资源拒绝均保留；但 OpenClaw 2026.5.12 轮换 UUID 后仍复用旧 transcript，六条历史工具结果继续进入模型。整体测试退出码 1，失败证据已归档，原生历史重置不记为通过。
- 最新增量（2026-09-07 20:25）：[逐次审批门槛修复](trusted-intent-v2-approval-gate-fix-20260907-202500.md)。发现并修复 `patch-desired` 会清空 OpenClaw `exec` 审批集合的问题；12 个策略场景与执行引擎负向均证明旧行为并验证修复。Go race/vet、四目标构建及 115 项 Python 合同测试通过；新修复仍待提交与对应 SHA 的 CI。
- 最新增量（2026-09-07 20:16）：[OpenClaw 完整 CLI 会话验收](trusted-intent-v2-openclaw-conversation-20260907-201600.md)。四次原生命令、十次 SSE completion、六次工具调用与八条回执通过；实际 post hook、跨进程续聊、独立新会话拒绝继承已验证。补充 sessionKey 与 transcript UUID、模型历史 ID 规范化的区别；网关审批及 reset 生命周期仍待验收。
- 最新增量（2026-09-07 20:04）：[Hermes 完整会话与远端 CI 验收](trusted-intent-v2-conversation-validation-20260907-200400.md)。原生 Agent 两个会话、三轮对话、九次 SSE completion、六次工具调用及八条回执通过；真实生成会话 ID 与跨轮动作链已验证。`3d1a9b5` 的 28 个远端 CI job 全部成功；平台审批、OpenClaw 完整会话、CodeBuddy 实机及独立复核仍待验收。
- 最新增量（2026-09-07 19:47）：[持续运行、到期边界与旧适配器验收](trusted-intent-v2-soak-and-compatibility-20260907-194732.md)。完成 32 会话、600 秒、六次强杀恢复；修复 24h 到期精度差异，并对新构建补做恢复回归；未修改的旧 Hermes 适配器通过原生兼容性测试。
- 最新增量（2026-09-07 19:25）：[OpenClaw 安装修复与原生工具链验收](trusted-intent-v2-openclaw-validation-20260907-192539.md)。补齐原生加载清单、安装启用和重装卸载归属；真实组件工具链、失联恢复、512 对请求/32 并发验证通过。完整会话/审批、长期运行和独立复核仍待完成。
- 最新增量（2026-09-07 19:10）：[Hermes 原生工具链验收与审批修复](trusted-intent-v2-native-validation-20260907-191006.md)。基线 `60313a4` CI 已成功；原生分发器集成、512 对 HTTP 负载与重启重放通过。本轮新增修复尚未取得新 SHA 的远端 CI，完整平台 V2 验收仍未关闭。以下旧验证数字保留为历史快照。

## Architecture

```text
受信管理会话（capAdmin）
  → POST /v1/intents
  → V2 结构/约束/时间窗/证据校验
  → 既有 canon + digest + Ed25519
  → 排他发布不可变 Intent（同时构成签发审计记录）
  → POST /v1/intent-bindings → 固定会话绑定

Adapter 工具事件
  → Grant lookup ∩ Store 解析/验签 Intent ∩ 确定性约束匹配 ∩ Runtime taint/trifecta
  → 服务端 action_id / task_seq / parent_action_id
  → 签名 Decision Receipt
  → Observe 引用合法前置 Decision
  → 身份/动作/审批/结果重放校验
  → 签名 Observation Receipt
```

`internal/intent` 负责 V2 结构、签发、验签、存储、绑定和匹配；receipt 通过 `ResolveStore` 消费已解析合同。
旧 receipt Intent DTO 保留为 v1 兼容桥，HTTP Decision 不接受 inline 授权。

## Trust Boundary

| 主体 | 可以做什么 | 不能凭此获得什么 |
| --- | --- | --- |
| 配对产生的管理会话，capAdmin | 创建/读取 Intent，创建/读取固定绑定 | 不替代恶意同 UID 隔离或真实用户在场证明 |
| Decision token，capDecision | 提交工具决策、提交引用已授权动作的 Observe | Intent 管理 API 均返回 403，不能签发、替换或扩大自身授权 |
| Adapter | 映射身份/工具/参数/结果，暂存服务端返回的关联 ID | 不持有签名密钥、不解释 purpose 作为授权 |
| 运行时客户端 principal/task/intent hint | 仅用于一致性检查 | 不决定 authority |

## Changed Files

| 文件/目录 | 变更 |
| --- | --- |
| `packages/contracts/intent-contract.v2.schema.json` | V2 结构、工具/effect、资源与参数约束 |
| `packages/contracts/runtime-action-envelope.schema.json` | 动作信封及 tool_call_id |
| `packages/contracts/receipt.schema.json` | 可选 intent/action/record_type/关联/序号扩展，保留历史签名读取 |
| `apps/agentshield/internal/intent/{types,validate,matcher,store,binding}.go` | 独立授权实现，不可变签名 Store，固定绑定 |
| `apps/agentshield/internal/intent/{store_test,vector_test}.go` | 篡改、并发、过期、匹配与固定向量 |
| `apps/agentshield/internal/runtimeaction/` | 规范化动作、服务端 ID 和跨字段区分回归 |
| `apps/agentshield/internal/receipt/{engine,intent,action_state,chain}.go` | 授权交集、签名拒绝、Observe 强关联、重放与恢复 |
| `apps/agentshield/internal/receipt/{intent_test,action_state_test,receipt_test}.go` | 授权负向、行为序号、重启与并发观测 |
| `apps/agentshield/internal/server/{server,intent_http}.go` 及测试 | 管理 API、分权、结构化错误与观察冲突 HTTP 409 |
| `apps/agentshield/internal/state/{state,intent_authority}.go` | 状态目录与 intent_enforcement 配置 |
| `apps/agentshield/cmd/agentshield/main.go` | daemon 配置/Store 接线，CodeBuddy HTTP 字段 |
| `apps/agentshield/internal/adapters/adapters.go` | CodeBuddy tool_use_id 透传 |
| `adapters/runtime/hermes-agentshield/`、`openclaw-agentshield/` | pre/post 关联缓存，2048 项、300 秒 TTL、冲突拒绝 |
| `apps/agentshield/internal/adapterinstall/assets/{hermes,openclaw}/` | 与适配器源码同步的内嵌安装资产 |
| `apps/agentshield/testdata/contracts/` | V2 合同、动作、receipt、固定签名向量 |
| `apps/control-api/app/tests/test_intent_v2_contracts.py` | Go 产物的独立 Python Schema/digest/Ed25519 验证 |
| `apps/agentshield/internal/perfbaseline/intent.go`、`cmd/perfbaseline/main.go` | `-intent` 本地性能测量入口 |
| `scripts/test-openclaw-adapter.cjs`、`.github/workflows/ci.yml` | 隔离的 OpenClaw mock hook 回归并接入 Web CI job |
| 开发规格、优化计划、合同 README、威胁模型、能力矩阵、适配器 README | 同步完成范围和未验收边界 |

## Security Invariants 与负向测试

| 不变量 | 实现/证据 |
| --- | --- |
| Decision client 不能制造 authority | `TestIntentManagementRequiresAdmin`：所有 Intent/Binding 管理端点对 Decision token 返回 403 |
| Inline Intent 不成为授权 | `TestDecideRejectsInlineIntentAuthority`；HTTP 测试返回 400 |
| required 缺 binding 不退回 Grant-only | `TestRequiredIntentEnforcementFailsClosedWithoutBinding`：deny + intent_binding_missing |
| audit_only 仍计算真实拒绝 | `TestRequiredIntentAuditProducesSignedWouldDeny`：allow + advisory_action=deny + 稳定 reason_code |
| bound 不通过省略、换 Intent/Task 降级 | `TestBoundSessionCannotDowngradeOrSwapIntent`、`TestV2TrustedStoreGrantIntersectionAndHints` |
| 拒绝回执不能抹掉原绑定，重启仍保持 | `TestDowngradeDenialDoesNotEraseRecoveredBinding` |
| Intent 不可变、可验签 | `TestStoreIntegrityAndImmutability`；相同内容重试幂等、同 ID 替换拒绝、digest/signature 篡改拒绝 |
| Binding 只从 Store 读 authority | `TestBindingAuthorityAndConcurrency`：错误 agent/task 拒绝，16 个并发相同绑定只形成一份记录，过期绑定重启后仍拒绝 |
| Grant ∩ Intent 为交集 | `TestV2TrustedStoreGrantIntersectionAndHints`：Grant 拒绝工具仍拒绝，Grant 允许但参数不满足也拒绝 |
| Tool 与 Effect 分离 | `TestV2ConstraintAuthorization`：Bash/curl 不能仅凭 process.exec 授权；unknown effect 失败关闭 |
| 资源约束执行 | company-a 允许；company-b、company-a-evil、路径清理逃逸、相对路径拒绝 |
| 参数约束执行 | RFC 6901 嵌套对象、数组、~0/~1 转义；缺路径/非法操作符/非法 RE2 拒绝 |
| 无决策、deny、未批准 hold 不产生成功观察 | `TestObserveRequiresAuthorizedDecision`、`TestObserveHoldRequiresManagementResolution` |
| Observe 身份与动作强绑定 | platform/session/agent/tool/tool_call_id/action_id/decision_receipt_id 任一不一致均拒绝 |
| 结果幂等与并发安全 | `TestObserveIdempotencyConcurrencyAndRecovery`：12 个并发相同结果仅一条 observation；冲突拒绝，重启重试复用原签名回执 |
| 容量不通过清掉安全状态恢复 clean | `TestActionCapacityAndAmbiguousLegacyObserveFailClosed`；最多 8192 动作关联，24h 窗口，超限拒绝；bound/tainted 会话不随动作缓存过期清理 |
| 不同动作身份不会收敛为同一空摘要 | 修复 canon 不接受 []string 而错误被忽略的旧问题；`TestActionIDDifferentiatesEverySecurityField` |
| 既有安全行为不退化 | 完整 receipt/server/race 测试保留 Grant、taint、lethal trifecta 和历史回执验证 |

签名 Intent/Binding 文件本身作为不可变授权审计事实，由管理 GET 接口回链；未另外引入先激活后补写的审计步骤。

## Compatibility 与操作方式

1. 默认 `intent_enforcement=optional`；无绑定沿用 Grant 授权，但新决策回执显式 `intent_binding=unbound`。
2. 在 `<state>/config.json` 设置 `intent_enforcement=required` 后重启 daemon 生效；该维度与 audit_only/warn/block 独立。
3. 管理会话调用 `POST /v1/intents`，body 使用 V2 样例结构（digest/signature 由服务端重算），再提交绑定：

```json
{"platform":"hermes","session_id":"实际会话 ID","agent_id":"实际 Agent ID","intent_id":"已签发 Intent ID"}
```

4. 新 Observe 可同时传 action_id/decision_receipt_id；旧适配器保留 pre 决策兼容。post 有稳定 tool_call_id 时服务器可唯一解析；无 ID 时必须传相同参数且唯一，否则拒绝。
5. 当前三平台适配器已具备原生关联证据，具体版本、调用入口和限制见最终验收与各平台报告；综合平台状态仍为 **unverified**，不把固定版本测试推广为所有宿主路径。旧 OpenClaw/CodeBuddy post 缺字段时拒绝，升级后恢复关联。
6. OpenClaw 平台审批不自动成为本地 hold 管理批准。当前适配器先等待本地批准；缺受信审批后检查点的宿主在 block 下拒绝 hold，配套宿主在执行前再查当前授权。检查点不提供副作用原子取消。
7. 历史 v1 Receipt 新字段可省略，不重算或重签历史文件；历史记录不凭字段缺省获得新动作授权。

## Performance

命令：`go run ./cmd/perfbaseline -intent -out <report.json>`。
实际记录：[local-20260907.json](evidence/intent-v2/local-20260907.json)。环境 Go 1.26.5 / linux/arm64，单 binding，200 次样本。

| 测量范围 | P50 (ms) | P95 (ms) | P99 (ms) |
| --- | --- | --- | --- |
| 本地 binding + Intent 读取/验签 | 0.112369 | 0.136178 | 0.191122 |
| 结构校验与确定性资源匹配 | 0.000640 | 0.001488 | 0.003152 |

上述早期微基准不包含 HTTP、receipt fsync、全链重启恢复或真实工具执行，不作为 SLA。后续已补齐 1/128/1024/4096 绑定、HTTP 并发、600 秒负载与强杀恢复，见 [分档基准](trusted-intent-v2-progress-20260907-164919.md) 和 [持续运行记录](trusted-intent-v2-soak-and-compatibility-20260907-194732.md)；不同构建的时长不合并。

## CI / 本地验证

当前产品基线 `2305979` 的 [完整 CI](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34140323805) 已确认 28/28 成功；提交前 Go 全模块 race/vet、四目标构建、Python 120 项合同测试及相关 Ruff 通过。以下表格是初次开发时的历史快照，不能用于推翻后续准确 SHA 的 CI 结论。

| 命令与范围 | 结果 |
| --- | --- |
| `apps/agentshield`: `go vet ./...`、`go test ./...`、`go test -race ./...` | 通过 |
| linux/amd64、linux/arm64、darwin/arm64、windows/amd64 `go build ./cmd/agentshield` | 通过，制品仅在临时目录 |
| Control API：`uv run pytest -q -o addopts=''` | 458 通过；1 个既有依赖弃用警告 |
| Hermes：`uv run --project apps/control-api pytest -q -o addopts='' adapters/runtime/hermes-agentshield/tests/test_adapter.py` | 13 通过 |
| `node scripts/test-openclaw-adapter.cjs` | hook 映射/关联/重复冲突/断连拒绝通过；无真实平台或凭据 |
| Ruff：新增 Python 合同测试与 Hermes 适配器 | 通过 |
| Web：`npm run build`、`npm test -- --reporter=dot` | 构建通过；11 项测试通过 |
| `gofmt -l apps/agentshield`、`git diff --check`、`python3 scripts/check_ci_action_pins.py` | 通过 |
| 远端 CI、最低 Go 版本、govulncheck/npm audit、其他未改动 Go 模块 | 本轮未据此宣称通过；不是全仓 CI green 结论 |

## Residual Risks 与后续任务

- **desktop-same-uid**：恶意同 UID 进程可能调用 CLI、读取密钥或重写状态。协议分权不等同 managed-linux 隔离。
- 资源匹配支持明确的文件/URL host/recipient 字段；未知资源与 opaque shell 资源拒绝。静态 effect 分类不证明 shell 程序全部真实副作用；网络 ASCII host（Unicode host 需预先转 Punycode），符号链接由已有文件安全层负责。
- 签名恢复遇到损坏/不完整链失败关闭，需要诊断恢复；未宣称覆盖所有断电/文件系统故障。动作窗口外重试拒绝。
- 已提供 append-only 签名绑定撤销 API，含并发、幂等、重启与 optional 不降级测试；同一会话不能重写原绑定换任务。撤销前已取得授权快照的动作仍可能完成，不承诺取消已开始的副作用。
- task_seq/parent_action_id 是当前 Session 的最小行为骨架，未实现跨 Session 任务图或 Delegation DAG。
- **Parameter provenance、behavioral sandbox、multi-agent delegation、real-world effect verification** 均未实现，按本轮要求保留为后续阶段。
- 后续发布验收：独立安全复核、真人审批/消息渠道、跨 OS 实机和目标部署故障模型。已有原生 pre/post、受控审批、负载、强杀恢复及 CI 证据的准确范围见最终工程验收；这些范围外的能力继续保持 unverified。

## Definition of Done 判断

按原文 §49 的 17 项 DoD 与 T1–T16，核心工程行为、三平台原始基线的 optional 授权兼容及产品基线 CI 已具备证据，逐项见 [最终工程验收](trusted-intent-v2-final-audit-20260908-000506.md)。T15 要求旧请求继续执行 Grant 逻辑并记录 unbound；它不授权接受缺失关联信息的旧 post。后者继续按 §25 拒绝，原始失败归档不改写。本次结论限于 V2 工程范围，后续新提交的 CI 以其实际运行结果为准。

### 当前验收状态（2026-09-07 19:10 增量）

- DoD 17 的历史未确认状态已有新证据：`60313a4` 的完整远端 CI 成功；本轮未提交修复仍需对应新 SHA 验证。
- DoD 13 新增 Hermes 原生加载器/工具分发器的 pre/post、required/optional、失联与重启证据，但没有覆盖完整 LLM 会话或全部三平台，不能判定全部兼容性验收完成。
- 实际 API 集成发现审批错误被遮蔽，已修复并通过正负向回归、Go race/vet 和四目标构建。
- 性能从 binding 微基准扩展到 HTTP、签名落盘和并发重放；当前为 512 对请求的有限负载，长期运行与独立安全复核仍待完成。
- 当前实现、命令、测量、可信边界与后续任务统一见上述增量报告；此目标仍处于开发验收中。

### OpenClaw 增量（2026-09-07 19:25）

真实加载器发现并复现了插件缺清单的问题，已补齐清单和安装器的运行时注册。安装器实际输出通过原生加载器验证，原生前置执行包装器、Pi 文件工具和后置 relay 通过 V2 合成调用验收；重装卸载残留也已修复。详情、原始数据和复测命令见上述 OpenClaw 报告。该证据不覆盖完整网关/LLM 会话或平台审批，V2 总体验收继续保持进行中。

### 持续运行与兼容性增量（2026-09-07 19:47）

32 个独立 Intent/session 在 600 秒内经历六次真实 daemon 强杀，1,441 个动作及其唯一 observation 共 2,882 条回执验签通过。测试期间另发现内存与恢复路径的 24h 到期精度差异，已统一按签名 issued_at 计算；新构建通过边界正负测试、60 秒两次强杀和旧版 Hermes 原生兼容回归。两种构建的持续时长分别归档，不混计。受控时钟测试同时证明晚到观察不续期、动作过期不清除绑定/污点。

DoD 13 新增实际历史 Hermes 代码证据；其他旧平台的缺标识 post 仍不能靠猜测关联。完整 Agent 会话/审批、CodeBuddy 实机、更多系统故障与独立复核仍待验收；当前代码尚未获得新 SHA 的远端 CI，因此目标继续保持进行中。

### 完整会话与 CI 增量（2026-09-07 20:04）

`3d1a9b5` 的完整远端 CI 已成功，解决上一段的新 SHA CI 待验收项。新增 Hermes 原生 `AIAgent.run_conversation` 集成，使用本地合成模型的实际 SSE 协议驱动工具解析与执行；跨两轮对话的固定授权、递增序号、父动作和结果返回模型均通过，新建未绑定会话拒绝继承权限。此测试补足直接调用工具分发器无法证明的会话路径，但仍不覆盖真人审批、其他两平台完整会话及独立复核。详细范围、命令与原始证据见本节顶部最新报告；目标继续保持进行中。

### OpenClaw 完整 CLI 会话增量（2026-09-07 20:16）

从真实 `openclaw.mjs agent --local` 入口运行，插件加载、模型 SSE 解析、文件工具和后置钩子由平台自行执行。初始会话由平台创建，管理端按原生 sessionKey 绑定；两个独立 CLI 进程续聊保持 transcript UUID 和授权动作链，显式新会话没有继承旧权限。模型历史 ID 规范化与真实 pre/post ID 分别验证。详见最新报告；完整 CLI 路径已补证，网关审批、同 key reset、CodeBuddy 与独立复核仍未完成。

### 逐次审批修复增量（2026-09-07 20:25）

继续检查 hold 流程时发现策略编辑会抹掉由 process/resource/credential 事实派生的 OpenClaw exec 审批门槛。现已按补丁后事实重新派生，保留逐次审批及凭据 deny；负向测试实际复现旧实现把 hold 降为 allow。修复通过核心门禁，但不会修改历史已签名策略，也不代表平台网关审批联动已完成。详见最新报告，目标仍在验收中。

### 原生空闲重置增量（2026-09-07 20:36）

在当前工作树构建上重新通过 OpenClaw 完整 CLI 基础场景，并用真实空闲等待测试 UUID 轮换。SIQ 相同 key 的签名绑定、序号 6→7→8、父动作和 PII 污点均保持；13 条回执验签通过。原生平台却保留旧 sessionFile 与六条历史工具结果，故整体重置测试明确失败。详细复现、源码定位和适用范围见最新报告；该失败未被重命名为平台成功，也未修改第三方安装包。

### 原生重置候选补丁（2026-09-07 20:42）

已制作 OpenClaw 2026.5.12 指纹限定补丁，修复 CLI 先更新 UUID 后继续复用旧 sessionFile 的问题。独立文件副本复测退出码 0：普通续聊保留历史，真实空闲重置切换文件并清除模型请求中的旧工具历史，SIQ 固定绑定、污点与动作链仍保留。补丁和复测运行器已落盘，未更新本机原安装或发送上游 PR，原版与补丁副本证据分开归档。
