# OPT-08 B2：原生会话与精确工具调用绑定

日期：2026-10-07。状态：B2 存储组件通过；在线引擎、受管 enrollment 门禁与真实宿主集成尚待完成。

## 本批交付

按 [ADR-056](../adr/0056-native-skill-invocation-authority.md) 新增 `native-skill-managed-session/v1`、`native-skill-call/v1` 两份合同、Go `NativeCallStore`、产品签发的三份固定合成样例与独立 Python 验签。状态分别写入 `native-skill-sessions`、`native-skill-calls`，只新建，不改写 v1/v2 历史上下文。

会话固定实际实例、会话、Agent baseline 摘要与运行制品摘要。工具调用固定原生任务、工具调用 ID、最终工具名和最终参数摘要，绑定会话精确签名，以及以下两者之一：

- 已验证 v2 Skill 上下文的精确签名，含所有祖先限制。
- 宿主明确证明没有 Skill 的 `no_skill=true`。

验证时完全依据已登记的实际调用；请求中的 context/no_skill 声明不能选择或降级授权。宿主事实回调每次重查加载/任务/调用边界；它必须由后续真实集成实现，当前测试注入的回调只验证组件协议。未知、缺失或混杂归属不能作为“无 Skill”。有 Skill 时祖先上下文的运行制品也必须与登记会话一致。

调用 ID 不包含工具名和参数，因此重复使用一个原生调用 ID 修改工具、参数或上下文会产生冲突，不能签出第二条授权。会话最长 24 小时，调用最长五分钟，并受当前 host/session/context 租约收紧；重复请求仅返回原有效文档，不延长期限。原始参数不落盘，摘要之前拒绝循环/非 JSON 对象和超过 1 MiB 的 JSON 参数。

## 验证矩阵

| 范围 | 实测结果 |
| --- | --- |
| 正向 | 有 Skill 与明确无 Skill 均能登记、签发、重新打开存储后验证；Agent baseline 一致 |
| 精确调用 | 工具名、参数、调用 ID、platform、instance、agent、session、task 任一变化均不能使用原调用记录 |
| 禁止降级 | 缺少调用或会话直接拒绝；模型自称无 Skill 不能覆盖宿主的 Skill 事实；未知归属不能签发 |
| 幂等 | 重复调用及会话返回原始签名与期限；相同原生 ID 改写工具/参数/上下文拒绝，即使新的宿主事实已被登记 |
| 活体边界 | 宿主会话/调用失败、baseline 漂移、Skill 撤销、安装内容变化、任务结束、租约到期与记录丢失均拒绝 |
| 并发 | 16 个相同调用并发仅一次审计/发布；不同调用同时绑定，分别保留各自父链 |
| 容量 | 会话 1024 条、调用 16384 条最后空位通过，超额拒绝；已满时原文幂等仍可用 |
| 审计与文件 | 会话或调用审计失败不发布；重复字段、别名、额外 JSON 文档和未知字段拒绝；底层共享 B1 私密对象读取器 |
| 隐私与制品 | 调用文件不含参数原文及合成标记；来自其他运行制品的上下文不能绑定 |
| 跨语言 | Python 独立复算确定性 ID、参数摘要、会话引用并验证 Go 签名；每个关键绑定字段篡改均使验签失败 |

## 验证结果

- `go test -race ./internal/skillcontext`：通过，包含既有 SEC 和 B1/B2 用例。
- `go vet ./...` 与 `go test ./...`：通过，44 个有测试包、10 个无测试包。
- `test_native_skill_call_contract.py`、`test_native_skill_context_v2_contract.py`、`test_schema_contracts.py`：320 项通过，1 条既有依赖弃用警告；定向 Ruff 通过。
- 四目标构建通过：linux/amd64、linux/arm64、darwin/arm64、windows/amd64。不是相应平台原生业务验收。

日志在忽略目录 `var/optimization-20261007/opt08-call-{race,vet,go-all,contracts}.log`，构建产物同目录。新增样例完全使用公开合成测试种子和数据，不含业务凭据。没有修改兄弟业务仓库，也没有启动模型或替换日常业务服务。

## 后续门禁

本批调用记录不授予工具执行权，不替代 hold reservation/observation，不保证副作用 exactly-once。C 阶段需要由可信 enrollment/运行身份配置确定哪些请求必须通过调用验证；不能根据本次请求字段或“记录是否存在”来决定是否启用保护。之后实现精确 Agent baseline 与所有 Skill 祖先的权限交集，并复验 hold 重试。D/E 的固定业务镜像宿主接入与真实效果验收仍是未完成项。
