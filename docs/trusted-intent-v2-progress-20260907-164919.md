# Trusted Intent V2 后续开发进度与验证报告

- 时间：2026-09-07 16:49:19 +0800 Asia/Shanghai。
- 仓库：`siq-agent-security`，本轮基于 `main` / `0f232f4` 开发，报告生成时改动尚未提交或推送；后续提交与 CI 以 Git 历史和对应 SHA 的运行记录为准。
- 范围：用户 V2 文档的资源规范化、可信动作元数据、任务链恢复、约束测试与性能基线补齐。
- 结论：以下工程切片已完成本地验证；真实平台 V2 端到端验收和本轮远端 CI 尚未完成，因此不宣称整个 V2 已关闭。
- 上一轮架构与权限边界：[基础工程报告](trusted-intent-v2-report-20260907-161622.md)。本报告更新其中的后续工作状态，不改写历史验证记录。

## 已完成的开发

| 项目 | 最终行为 | 主要实现与测试 |
| --- | --- | --- |
| Shell 效果保守识别 | Shell 始终包含 `process.exec` 和 `unknown`；可识别的出网线索保留 `network.request`。绑定 Intent 时无法仅凭命令文本宣称效果完整，匹配未列入效果或 unknown 时拒绝 | `runtimeaction/normalize.go`；`TestShellCannotClaimExhaustiveEffects` |
| 统一结构化资源 | 文件绝对路径清理并做目录边界匹配；网络只处理 ASCII DNS/Punycode/IP，拒绝 userinfo、畸形 host；消息收件人区分大小写；多个输入别名必须全部满足约束 | `runtimeaction/resources.go`、`intent/matcher.go`；31 组共享匹配语料 |
| 参数精确比较 | JSON Pointer 转义与数组下标约束；支持 equals/one_of/prefix/suffix/regex。数值 `1` 与 `1.0` 等价，大整数不经 float64；指数按系数/指数比较，避免构造巨大整数 | `intent/json_equal.go`；`TestExactJSONNumbers` |
| 动作与签名元数据 | Envelope/Receipt 增加可选 Principal、resource_refs、provenance_refs，并纳入动作 ID 与签名；资源摘要不增加路径、host、收件人原文 | 三份 schema、`runtimeaction/actionid.go`、`receipt/engine.go`、Web `local/types.ts` |
| 来源引用预留 | 最多 64 个唯一合法 ID；只由可信已签 Intent 传播到 decision/observation，客户端参数中的同名字段不成为来源权威 | `intent/validate.go`；引用边界、篡改、传播测试 |
| 任务边界与并发 | unbound 首次转 bound 时 TaskSeq 从 1 开始且 parent 为空，污点保留；旧观察/旧 hold 审批不会改变新任务动作链；32 个同会话并发决策拥有唯一 ID 和连续顺序 | `receipt/task_boundary_test.go`、`action_state.go` |
| 进程强杀恢复 | 子进程写入决策/观察后被强杀；新 Engine 从签名链恢复，pending 结果补录或已观察重试均保持单条观察证据 | `receipt/crash_recovery_test.go` |
| 历史兼容 | 新字段均 optional；保留扩展前的固定回执，当前 Go 仍验签成功，Python 仍通过 schema | `receipt.pre-resource-refs.sample.json` 及双侧回归 |
| 绑定查找性能 | 既有确定性绑定 ID 直接定位文件；每次重新验签目标绑定与 Intent，检查时效/身份/digest，不创建权限缓存 | `intent/store.go`；目标篡改拒绝、跨身份缺失与管理枚举损坏检测测试 |

`Resource` 是运行时瞬态值，签名回执只增加 `domain + digest`。原有脱敏参数片段策略保持原定义。网络资源摘要对应 host 范围，不代表完整 URL、端口、DNS 解析结果或实际网络目的地；Intent 的路径约束也不等于 OS 层防符号链接隔离。

数值字符串超过 1024 字符时按不匹配处理。网络 prefix/suffix 是规范化后的字符串操作；需要完整域名约束时使用 host，需要子域约束时明确点边界。正则表达式本身不进行路径清理，作用于规范化后的资源值。

## 架构及信任边界

链路仍为：可信管理签发 → 不可变签名 Intent → 固定会话绑定 → 规范化动作 → Grant ∩ Intent ∩ RuntimeState → 签名 decision → 强关联 observation。

- Decision token、inline Intent 和调用参数均不能创建管理权威。
- Principal 和 provenance_refs 来自已解析 Intent；参数里的同名内容不用于赋权。
- 确定性定位省去了无关记录的全目录验签；目标记录每次必验。管理 ListBindings 仍对全目录进行完整性检查。
- bound 粘性状态与累积污点继续从签名回执恢复，不通过过期/LRU 伪装 clean。
- provenance_refs 仅是预留的引用字段；没有实现 Provenance DAG，也没有由引用授予权限。

## 本轮验证

| 检查 | 结果 |
| --- | --- |
| Go `gofmt` / `go vet ./...` / `go test ./...` | 通过 |
| Go `go test -race ./...` | 通过，含新增并发、任务切换边界、强杀恢复 |
| 四目标交叉编译 | linux/amd64、linux/arm64、darwin/arm64、windows/amd64 通过 |
| Control API `uv run ruff check app` | 通过 |
| 完整 Python `uv run pytest -q -o addopts=''` | 501 passed；现有 Starlette 测试依赖弃用警告 1 条 |
| 聚焦 Python schema/固定向量测试 | 115 passed，包含 31 组 Go 共用语料的 schema 校验 |
| Web `npm test` / `npm run build` | 11 passed；TypeScript 类型检查和 Vite 构建通过 |
| 静态门禁 | Actions SHA、Docker digest/locked uv、Web headers、能力诚实性、威胁模型、性能骨架检查均通过 |
| `git diff --check` | 通过 |

Python 对共用语料做合同形状检查，授权匹配结论由 Go 测试验证；这不等于另有 Python 授权引擎实现。Intent 的 canonical/digest/Ed25519 固定向量继续由 Python 独立验证。

上一批提交 `0f232f4` 的远端 [CI run 34100490300](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34100490300) 已确认成功。报告生成时本轮改动尚未推送，不能把上一批 CI 结果计为本轮 CI。

## 性能实测

Go 1.26.5 / linux/arm64，本地临时合成状态，每档 200 样本，单位 ms；排除初始化、HTTP、回执 fsync 和实际工具执行，不预填 SLA。

| 绑定数 | 查找 P50 | 查找 P95 | 查找 P99 | 缺失查找 P99 | 原始数据 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 0.2109 | 0.2380 | 0.4937 | 0.0095 | [JSON](evidence/intent-v2/local-20260907-164553-direct-bindings-1.json) |
| 128 | 0.1160 | 0.2320 | 0.2981 | 0.0141 | [JSON](evidence/intent-v2/local-20260907-164553-direct-bindings-128.json) |
| 1024 | 0.2187 | 0.2385 | 0.3299 | 0.0154 | [JSON](evidence/intent-v2/local-20260907-164553-direct-bindings-1024.json) |
| 4096 | 0.2194 | 0.2396 | 0.3003 | 0.0124 | [JSON](evidence/intent-v2/local-20260907-164553-direct-bindings-4096.json) |

优化前，128 个绑定的查找 P99 为 13.2904 ms，1024 个为 102.8788 ms；采用相同规模和样本数的直接读取后分别为 0.2981 ms、0.3299 ms。不同时间的本地测量存在负载波动，以上用于呈现去除线性目录扫描的效果。优化前原始记录见 `docs/evidence/intent-v2/local-20260907-164340-bindings-*.json`。

复测：

```bash
cd apps/agentshield
go run ./cmd/perfbaseline -intent -intent-bindings 1024 -intent-samples 200 -out /tmp/intent-perf.json
```

## 剩余任务和验收状态

| 后续任务 | 当前状态与下一步 |
| --- | --- |
| 真平台 V2 pre/post、hold、失联归档 | Hermes/OpenClaw 本机有 CLI 入口，但本轮未在真实运行时采集完整 V2 链路；CodeBuddy 命令当前不可用。继续用隔离测试实例验证真实 tool_call_id 与 action/receipt 关联，保留版本和回执证据；能力矩阵保持 unverified |
| 长期运行与端到端负载 | 已完成 4096 个绑定本地查找、32 并发与两个进程强杀恢复场景；尚未覆盖长期 daemon、HTTP/签名落盘整体负载、平台重启期间重放风暴 |
| 本轮远端 CI | 按 contracts/runtime/tests/docs 拆分提交并推送后检查新 SHA 的完整 CI；报告生成时尚未提交 |
| 独立安全复核 | 复核 authority、动作关联、恢复与兼容性；当前为开发者自检与自动测试证据 |
| 可选撤销生命周期 | 原始需求允许按需实现 revoke；当前仍为不可变固定绑定，无解绑/原会话换任务接口。追加式撤销以及撤销与 Decide 并发测试尚未实现，不能写成已具备 |
| 后续阶段能力 | Provenance DAG、强 OS 沙箱、完整文件内容语义分析及 Agent 间委派不属于本轮，仍未实现 |

项目原 DEV01–DEV18 中的真实 PG、IdP、发布、跨系统治理与实机安全验收不能由本报告代替。生产信任处置、独立复核和平台能力宣称仍按原发布门槛执行。
