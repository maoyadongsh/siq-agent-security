# Trusted Intent Authority & Action Binding V2 工程报告

- 时间：2026-09-07，Asia/Shanghai
- 仓库：siq-agent-security；分支：main；工作基线：`0caacd3`
- 状态：核心授权与动作关联代码已落盘，本地验证通过；真实平台 V2 归档及远端 CI 待验收。
- 本报告记录开发验证完成时的工作树快照；后续提交与推送状态以 Git 历史为准。未部署。
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
5. Hermes/OpenClaw 提供关联字段的 mock/单元证据；CodeBuddy 按 tool_use_id 跨 hook 进程关联。三者真实平台 V2 关联仍为 **unverified**。
6. OpenClaw 平台原生审批不自动成为本地 hold 管理批准；缺本地批准的 Observe 拒绝。
7. 历史 v1 Receipt 新字段可省略，不重算或重签历史文件；历史记录不凭字段缺省获得新动作授权。

## Performance

命令：`go run ./cmd/perfbaseline -intent -out <report.json>`。
实际记录：[local-20260907.json](evidence/intent-v2/local-20260907.json)。环境 Go 1.26.5 / linux/arm64，单 binding，200 次样本。

| 测量范围 | P50 (ms) | P95 (ms) | P99 (ms) |
| --- | --- | --- | --- |
| 本地 binding + Intent 读取/验签 | 0.112369 | 0.136178 | 0.191122 |
| 结构校验与确定性资源匹配 | 0.000640 | 0.001488 | 0.003152 |

不包含 HTTP、receipt fsync、全链重启恢复、真实工具执行；不作为 SLA。大规模绑定/关联和长期运行另需测量。

## CI / 本地验证

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
- 暂未提供 revoke/任务切换 API，固定绑定不能覆盖。需要该能力时应增加 append-only 管理生命周期和并发撤销测试。
- task_seq/parent_action_id 是当前 Session 的最小行为骨架，未实现跨 Session 任务图或 Delegation DAG。
- **Parameter provenance、behavioral sandbox、multi-agent delegation、real-world effect verification** 均未实现，按本轮要求保留为后续阶段。
- 下一步验收：真实平台 pre/post 稳定 ID 和审批归档；大规模/长运行/强杀恢复压测；远端完整 CI 与独立安全复核。无真实平台证据不得把 capability matrix 的 unverified 改为 evidenced。

## Definition of Done 判断

DoD 1–12、14–16 的核心行为已有实现与本地测试证据。DoD 13 的旧 pre 决策保持兼容；无法唯一关联的旧 post 明确拒绝，真实平台兼容性待归档。DoD 17（全仓远端 CI green）尚未确认，因此本报告不宣称整个 V2 已完成验收。

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
