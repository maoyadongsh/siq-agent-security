# Trusted Intent V2：提交后验收核对与剩余任务

- 核对时间：2026-09-07 20:59，Asia/Shanghai。
- 代码基线：`78e740a01fa9c46cfb256fa2d84c2cf0739bdb2e`，本地 main 与远端 main 一致。
- 结论：该提交的完整 CI 已通过；V2 整体验收仍未关闭。
- 要求来源：用户提供的《Trusted Intent Authority & Action Binding V2》§0–52，及 [工程报告](trusted-intent-v2-report-20260907-161622.md) 已列出的后续验收任务。

## 1. 本轮新增的确定证据

[CI 运行 34124655497](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34124655497) 的 head SHA 精确等于上述提交，状态为 `completed/success`；全部 28 个 job 均为 `completed/success`。原始运行元数据与各步骤结果保存于 [ci-78e740a-20260907.json](evidence/intent-v2/ci-78e740a-20260907.json)。

范围包括 Control API 测试、依赖检查及干净 PostgreSQL 迁移，Web 构建及 OpenClaw hook 回归，Edge/Connector 双 Go 版本矩阵，本地安全模块和安全静态门禁。具体执行步骤以归档及 [CI 配置](../.github/workflows/ci.yml) 为准。该 CI 没有安装三平台原生运行时，不能代替平台审批或实机兼容性验收。

提交前在本机通过 `go test -race ./...`、`go vet ./...`、四目标交叉编译及 115 项 Python 合同测试；本轮没有重跑已通过且未发生代码变化的这些检查。新增 HTTP hold 测试属于该提交，已随 CI 执行。

## 2. 17 项 DoD 核对

表中“已有核心证据”仅说明对应确定性实现及测试已有证据，不把它扩展为三平台全部路径验收。具体负向行为另见工程报告的 Security Invariants 表。

| DoD | 要求 | 当前证据与结论 |
| --- | --- | --- |
| 1 | Decision token 不能签发或修改 Authority | `server/intent_http_test.go` 的 `TestIntentManagementRequiresAdmin` 直接使用原始 bearer 验证管理接口 403，拒绝后 Store 为空；已有核心证据 |
| 2 | inline Intent 不成为授权源 | 同文件 HTTP 400 与 `receipt/intent_test.go` 的 inline 拒绝；已有核心证据 |
| 3 | 复用 canonical/signing | `intent/vector_test.go` 与 Python `test_go_intent_canonical_digest_and_signature_vector`；已有跨语言固定向量证据 |
| 4 | Intent 不可变、有版本身份 | `TestStoreIntegrityAndImmutability` 验证相同内容重试、同 ID 内容冲突、digest/signature 篡改；已有核心证据 |
| 5 | 受信管理绑定 Session | 管理 HTTP 生命周期及 `TestBindingAuthorityAndConcurrency`；已有核心证据 |
| 6 | bound 不降级 | Intent swap/downgrade 测试、恢复后拒绝与原生多轮会话归档；已有核心证据，平台任意 reset 路径未全部覆盖 |
| 7 | tools/effects 分离 | `runtimeaction/normalize_test.go`、`intent/matcher_vectors_test.go`；未知 shell 副作用明确拒绝 |
| 8 | 资源参与授权 | `TestV2ConstraintAuthorization`、共享匹配向量与原生目录越权场景；已有核心证据 |
| 9 | 受限参数路径 | JSON Pointer/数组/转义及非法表达式回归、共享合同向量；已有核心证据 |
| 10 | Receipt 绑定授权与动作字段 | `TestV2TrustedStoreGrantIntersectionAndHints`、动作固定向量和签名回执；已有核心证据 |
| 11 | Observe 引用合法 Decision | `TestObserveRequiresAuthorizedDecision`、幂等/恢复测试；已有核心证据，不能据此证明平台一定在执行前等待本地批准 |
| 12 | deny 不产生成功 observation | 同上及实际平台资源/工具拒绝后无 observation 的归档；已有核心证据 |
| 13 | 旧 Adapter optional 兼容 | **未完全满足**：未修改的历史 Hermes 已有原生证据；旧 OpenClaw post 缺 ID/参数时无法安全关联；CodeBuddy 缺原生运行时证据 |
| 14 | required 缺 Intent 拒绝 | `TestRequiredIntentEnforcementFailsClosedWithoutBinding` 与原生新未绑定会话拒绝；已有核心证据 |
| 15 | Grant/taint/trifecta 不退化 | 当前 CI、完整本地 race 回归以及原生污点持续性测试；已有回归证据 |
| 16 | Go race 通过 | 当前代码的本地全模块 race 已通过；远端 Edge/Connector matrix 执行 race。不能把本地模块远端普通测试描述为远端 race |
| 17 | 全仓 CI green | **已满足此 SHA**：28/28 job 成功，见本报告归档；后续代码提交需单独验收 |

以上测试路径均相对于 `apps/agentshield/internal/`，Python 测试位于 `apps/control-api/app/tests/test_intent_v2_contracts.py`。测试源与 CI 是可复核入口；平台版本、合成模型限制和样本数量以各原生验收报告为准。

## 3. 原始工作包与附加要求覆盖边界

| 原始章节 | 对应产物与验收入口 | 尚需明确的边界 |
| --- | --- | --- |
| §2–4、10–16：Authority、Store、签发、证据、绑定 | `internal/intent`、`internal/server/intent_http.go`、`internal/state/intent_authority.go`；V2 schema 和 Store/API 负向测试 | 本地签名身份不是恶意同 UID 进程隔离；external reference 不是对外部内容真实性的背书 |
| §5–9、20：规范化、匹配、reason code | `internal/runtimeaction`、`internal/intent/matcher.go`、共享 matcher 向量 | shell 的分类提示不构成完整副作用清单，不能为了让 exec 进入 hold 而删除 unknown 拒绝 |
| §17–19、21–28：固定绑定、模式、回执、观察与最小动作链 | `internal/receipt`、历史签名向量、task boundary/expiry/hold/recovery 测试 | 动作链以 Session 为范围；observe 证明关联接收，不是对外部真实效果的独立认证 |
| §29–31：薄适配器与兼容性 | 三平台 adapter、内嵌安装资产、安装测试、Hermes/OpenClaw 原生报告 | DoD 13 尚未完整通过，不能把缺标识旧 post 的拒绝写成无缝兼容 |
| §32：T1–T16 | 工程报告 Security Invariants 表及上述测试入口 | T3 的省略 hint 仍由服务端读取原绑定；不能要求客户端每次重传 Intent。T9 的 opaque shell 可返回更严格的 `runtime_effect_unknown` |
| §33–34：Schema/固定向量 | Go 合同样例与 Python schema/canonical/digest/Ed25519 测试 | 结构校验与密码验签分别验证，不能用 schema 格式正确代替验签 |
| §35–39：后续阶段与确定性授权约束 | 签名 provenance_refs 元数据、结构化 matcher、稳定 reason_code | 未实现参数传播图、behavioral sandbox、delegation DAG；这些是原文明确排除的下一阶段 |
| §40–42：性能、容量、并发 | perf baseline、大规模 lookup、HTTP 并发、600 秒持续负载、强杀及容量回归 | 不预填 SLA；未验证所有断电/文件系统故障。revoke/任务切换 API 未提供，其并发验收也未完成 |
| §43–45：威胁、矩阵、文档诚实性 | `docs/threat-model.md` T23–T26、能力矩阵与本报告 | 综合平台状态继续 unverified，不提升同 UID 隔离等级 |
| §46–48：结构与授权公式 | 独立 intent/runtimeaction 包、receipt 授权交集及拒绝回执 | audit/warn 计算 would-deny，不宣称这些模式阻断执行 |
| §49–52：DoD、提交、报告、后续阶段 | 当前 Git 历史、17 项核对、工程报告及时间戳增量 | 全部验收完成前不关闭目标或提前引入 provenance graph |

§15 将 revoke 作为“如需要解除”的扩展，§42 又列出 revoke/decide 并发测试。当前固定绑定方案未实现解除，不能将该并发项填为已通过；应在引入解除生命周期时同时交付 append-only 撤销和并发拒绝证据。该缺口与缺少 CodeBuddy 实机属于不同事项。

## 4. 下一步可执行任务与验收条件

### A. 平台审批到本地批准的执行顺序

最高优先验证 OpenClaw 原生网关审批：在隔离网关、临时 SIQ 状态和合成工具副作用文件中，分别测试平台允许但本地未批准、本地拒绝、双方允许、等待期间取消/超时与重启。

验收必须同时检查工具是否实际执行和签名回执；仅证明 `/v1/observe` 拒绝不够。本轮源码检查显示，适配器 hold 返回 `requireApproval`，平台包装器在平台 `allow-once/allow-always` 后可继续执行；平台 `onResolution` 回调是异步触发且不等待完成。因此不能仅追加一个异步回调调用本地批准接口就宣称完成衔接，也不能把管理 token 放入适配器。该检查指出需要动态验证的执行顺序，尚不是原生网关复现报告。

验收成功后才可更新对应平台审批能力；Hermes 的本地控制台处理也需要独立的实际调用链证明。

### B. OpenClaw 原版重置与候选补丁

保留 [原版失败](trusted-intent-v2-openclaw-idle-reset-20260907-203600.md) 和 [临时补丁副本成功](trusted-intent-v2-openclaw-reset-patch-20260907-204200.md) 两套证据。下一步验证原生网关手动 reset/消息渠道；只有目标安装或目标版本实际采用修复并通过复测，才能宣称该环境问题已解决。不得把补丁副本的通过归给本机原安装。

### C. 旧适配器兼容与 CodeBuddy 实机

确认可用的 CodeBuddy 安装路径、版本和隔离测试入口；当前 `command -v codebuddy` 未找到。获取环境后，执行安装、准入、授权、越权拒绝、断连、跨 hook 进程 ID 关联及 optional/required 场景，归档版本和源码指纹。

旧 OpenClaw 缺少稳定 ID/相同参数的 post 无法唯一证明动作来源。完成兼容性需要可验证的运行时关联桥接或明确的升级迁移路径，不能猜测关联。历史 Hermes 的通过保留为该版本的证据，不能外推到所有旧版本。

### D. 独立复核与故障验收

安排独立审查者按原始 T1–T16、签名恢复、管理员/决策分权和上述平台实际执行边界复核。当前开发者自己的检查不能标为独立审查。故障演练应另行确定目标文件系统与故障模型；已完成的强杀/600 秒负载继续作为有限范围证据。

## 5. 本轮状态

上一轮属于进展：提交并推送实际修复和验收产物。本轮关闭了 `78e740a` 对应 CI 待确认项，新增原始 CI 归档并梳理验收依赖。没有修改生产代码、实际平台安装或能力矩阵的支持等级；上述剩余任务未完成，目标保持进行中。
