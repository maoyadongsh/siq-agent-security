# OPT-08 C1：原生调用的权限交集与 v3 回执

日期：2026-10-07。状态：C1 组件通过；C2 审批重试、兼容与消费者适配，以及 D/E 真实业务接入尚未完成。

## 实现与边界

引擎新增可信 `NativeCalls` 查询接口，区分原生调用上下文必需与旧会话路径。必需状态必须由可信 enrollment/宿主策略决定，不由请求中的 Skill、context 或 no_skill 声明决定。查询出错或必需却缺少上下文时，block、warn、audit_only 均产生 authority deny。该接口尚未接入 `serve` 的生产启动路径；受管 enrollment 门禁仍须在真实集成阶段落实。

通过 `NativeCallStore.VerifyNativeForEngine` 将 B1/B2 的签名、租约、安装、会话、任务、加载及父链实时验证接到决策组件。原 Intent 继续选择精确 Agent baseline；引擎不使用 Skill Grant 替换该选择，也不查询“最新 baseline”。策略计算依次取 baseline 与全部叶到根 Skill Grant 的交集：任一 deny 优先，其次 hold，全部允许才 allow。每个 Skill 使用自己的归属校验，避免把叶 Skill 的身份错误套在另一个父 Skill 上。

原生调用已绑定最终参数，引擎不在此路径静默脱敏改写参数后继续使用原调用证明。需要修改参数时须由可信宿主建立新的调用 ID 和绑定。参数预算在宿主查询和规范化计算之前检查，过深参数不会进入调用摘要递归。

## 新回执合同

新增独立 `receipt.v3.schema.json`，schema_version 为 `runtime-receipt/v3`。`native_invocation` 记录原生调用 ID/签名、会话登记 ID/签名、参数绑定、精确 Agent authority，以及全部上下文的签名和授权摘要。Skill 归属等级是 `controlled_invocation`；明确无 Skill 的调用保留 baseline 证明，不生成虚假的 Skill 归属。

v1/v2 schema、历史文件和签名字节保持。回执读取、签名链与新字段通过组件回归，但旧二进制、发行回退、导出和 UI 的完整版本支持仍需 C2 核验，不能据此启用日常产品路径。当前明确拒绝原生调用的旧单 Grant 审批重试，避免把已有 hold 实现误当作新权限链支持；这是一项未完成门禁，不是最终产品行为。

## 测试与证据

| 范围 | 验证内容 |
| --- | --- |
| 精确交集 | baseline、叶 Skill、父 Skill 任一显式工具拒绝均有效；任一文件资源范围缩小均拒绝；资源 deny 不被其他层 hold 覆盖；baseline 的审批要求保留 |
| 必需上下文 | 三种模式下缺失/不可读 authority 均 hard deny；明确无 Skill 使用原 baseline；旧未受管路径保持原回执格式 |
| 身份与完整性 | Intent 选错 Grant、缺少 Intent、伪造 Skill 声明、缺父链、错误调用/上下文签名形状、授权摘要和跨 Agent 结果均拒绝 |
| 快照保护 | 可信回调后续修改返回对象不能改变已生成回执或破坏原签名链 |
| 审批过渡 | C1 不允许原生权限链走旧单 Grant resume；完整重试支持留待 C2 |
| 参数预算 | 超过深度预算的参数在原生宿主查询之前拒绝，不进入递归 canonicalization |
| 存储→引擎联测 | 使用真实签名 Store、双 Grant、会话和调用记录，经桥接器进入真实 Engine；有/无 Skill 正向允许，后续缺少有效调用则拒绝 |
| 跨语言回执 | Go 集成测试实际生成两份固定合成回执；Python 独立验证 schema、调用绑定、回执哈希和 Ed25519 签名；修改授权链后即使重算 hash 也不能伪造签名 |

此处“真实 Engine/Store”指产品组件，原生宿主事实仍由受控测试回调提供。没有运行 Hermes 业务任务、调用模型或证明文件/网络外部效果；该范围由后续 D/E 与 OPT-10 验收。

## 运行结果

- Go 全量 `go vet ./...`、`go test ./...` 通过：44 个有测试包、10 个无测试包。
- `go test -race ./internal/receipt ./internal/skillcontext` 通过；补入最终参数门禁后另行复跑全部 `TestNativeEngine*` race，通过。
- Python 三份 native 合同测试与既有 `test_schema_contracts.py` 共 332 项通过，1 条既有 Starlette 弃用警告；定向 Ruff 通过。
- 四目标构建通过：linux/amd64、linux/arm64、darwin/arm64、windows/amd64。未作为相应 OS 原生运行证明。
- 日志：`var/optimization-20261007/opt08-engine-{vet,go-all,race,final-guard-race,contracts}.log`；产物同目录，不提交运行日志与二进制。

## 下一步

C2 完成原调用与重试调用的完整权限链复验、唯一执行预留和执行前重查，更新状态 reader/writer 与回退预检，并同步 UI/导出等消费者。随后落实受管 enrollment 必需路径，接入固定 Hermes 镜像的可信加载和最终工具调用门禁，最后执行实际业务效果验收。
