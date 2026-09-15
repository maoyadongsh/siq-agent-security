# OpenShell O04 当前能力与性能（2026-09-15）

结论：O04 的能力事实分离（A/B）、诊断六态（C）与原生路径组件性能基线（D，含 `rss_bytes_after` 语义修复和冻结测量协议）均已在组件级完成并通过正负向验证，结论为 `fixed_at_component_level`。全部证据为组件级（测试替身 / 真实子进程 fixture），没有真实网关：B2（同 OpenShell 环境服务级 HTTP 基线）与 B3（新集成端到端）因缺真实后端保持 blocked；B1−B0 相对对照因禁止在活动工作树 reset 生成对照而 `not_measured`。验证快照绑定工作树 `kimi/personal-v4-r01-20260914`、HEAD `6e34f3ad82033b0b5ffe49cd82bc042c84414429` 加当时未提交修改；未提交、未推送、未合并、未发布。

## O04-A/B 能力事实分离（已完成）

- Go 与 Python 均不再把能力事实折叠为单个 `supported`/`connected` 布尔。合同（[openshell-policy-safety.v2.md](../../../../packages/contracts/openshell-policy-safety.v2.md) O04 节）定义六类事实：`client_expressible` / `documented`（带观测日期与实例范围）/ `configured` / `handshake_verified` / `readback_verified` / `enforcement_reserved`；`enforcement_verified` 保留、任何 CLI 路径不得产出。
- `gateway info` 成功 ≠ 后端在线：它只是本地配置打印。握手必须由 `status` 完成且输出结构性匹配 `Server Status` 标题 + `Gateway:` 名称行；rc=0 但空输出/无关服务 fail-closed（`identity_unconfirmed`）。
- `cli_version`（`--version`/info 文本）与 `gateway_version`（仅握手输出声明时）分离；CLI 版本不提升任何能力级别，只产出描述性 `schema_version`（网关版本未知时 `unknown-policy-v1`）。
- 版本/网关名缓存绑定 endpoint 指纹 + 观测时间，跨 endpoint 或过期即失效；`max_filesystem_paths` 恒为合同默认值并报告为未实测。历史"实测"布尔保留为兼容字段，语义为历史文档视图。
- `status`/`doctor` 做结构校验；HTTP 与 CLI 路径同语义；正负向测试（伪网关、空输出、OpenClaw/Hermes 特征、旧文档不可提升能力）两语言齐备。

## O04-C 诊断六态（已完成）

`Diagnose` 输出六态，每态附人类可执行下一步：`unconfigured` / `configured_unreachable` / `identity_unconfirmed` / `handshake_verified` / `policy_readable` / `behavior_verified`，另含 `evidence_expired`。doctor 与 HTTP probe/doctor 端点输出同一状态，不泄露完整 URL、令牌或原始 CLI 错误。

## O04-D 性能基线（本轮新增）

### `rss_bytes_after` 语义修复

历史值取 Go `runtime.MemStats.Sys`（≈23.2MB），不是 OS RSS。现改为读 `/proc/self/status` 的 `VmRSS`（实测 ≈13.3MB）：`rss_source="os_vm_rss"`，读取失败时 `rss_source="unavailable"` 且值为 0（表示未测，不得伪造为零）。JSON 键名保留，`scripts/check_perf_baseline_harness.py` 门禁仍通过；新增 `go_memstats_sys_bytes` 仅作 Go 运行时观察，不得与 RSS 预算比较。

### 冻结测量协议与场景 A–E 结果

协议在任何测量之前冻结（轮数、交错顺序、预热、样本量、nearest-rank 百分位、零剔除规则、绝对预算），见 [o04-perf 证据](../openshell-o04-perf-20260915-062001/protocol.md)。每场景独立进程运行 3 轮，A/B 按 [A,B,B,A]/[B,A,A,B]/[A,B,B,A] 交错；测量不与全量测试并行。 pooled 结果（合并 3 轮）：

| 场景 | 指标 | n | p50 | p95 | p99 | max | 冻结预算 | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A 原生未启用 OpenShell | decide_allow_ms | 1200 | 6.72 | 7.82 | 10.07 | 13.00 | p95≤25 | 通过 |
| A 零后端调用 | diagnose_unconfigured_ms | 1200 | 0.02 | 0.02 | 0.04 | 0.24 | p95≤25 | 通过 |
| B 授权允许 | decide_allow_auth_ms | 1200 | 7.01 | 8.36 | 11.80 | 23.56 | p95≤25 | 通过 |
| B 吊销拒绝 | decide_deny_revoked_ms | 1200 | 7.24 | 8.53 | 11.49 | 13.53 | p95≤25 | 通过 |
| C 诊断首次探测 | probe_cold_ms | 3 | 3.37 | 3.47 | 3.47 | 3.47 | p95≤200 | 通过 |
| C 重复探测 | probe_repeat_ms | 600 | 3.05 | 3.95 | 4.21 | 4.44 | p95≤50 | 通过 |
| D 失联/超时失败返回 | timeout_fail_ms | 180 | 300.74 | 301.00 | 301.21 | 301.41 | p95≤300, max≤500 | **p95 未达**（+1.0ms），max 通过 |
| E O01/O02 读-写-回滚周期 | apply_rollback_cycle_ms | 600 | 0.40 | 0.58 | 1.02 | 1.55 | p95≤100 | 通过 |

- 场景 A 断言整轮 CLI 子进程调用次数为 0（未启用 OpenShell 零后端调用/零进程）；C 每次探测固定 2 次子进程（`gateway info`+`status`），D 每样本 1 次且受 `ProbeTimeout` 有界。
- **D 未达分析（未放宽门槛、未剔除样本）**：失败返回时间的代码设计上界 = `ProbeTimeout`(100ms) + O03 冻结的 `WaitDelay`(200ms 管道边界) —— bash fixture fork 出的挂起子进程在 bash 被终止后仍持有继承的管道句柄，管道边界按设计收尾。实测 p95 301.0ms、max 301.4ms，确定性且远低于 500ms max 预算；冻结的 p95=300ms 预算未给进程开销留余量。该未达如实记录于预算评估，未调整预算使其通过。
- 组件级微基准不冠名端到端性能；不通过缓存已撤销授权或省去最终参数校验提速（场景 B 的吊销拒绝、场景 E 的 expected-revision 绑定与授权回滚回调均在被测路径内）。

### not_measured（缺项如实登记）

B1−B0 p95 相对增幅（≤10% 预算冻结但对照不可测）、B2/B3、主机端到端、后端进程计数（仅场景 A 断言零调用）、每场景 CPU/RSS、磁盘写入字节、网络请求数、误拒率。

## 验证结果

命令与结果见 [checks.json](checks.json)：Go `gofmt`/`go vet`/`go test ./...`/`go test -race`（openshell+server）全过；4 目标 `CGO_ENABLED=0` 交叉构建摘要见 [cross-builds.json](cross-builds.json)（不代表 Windows/macOS 实机通过）；Python `uv run pytest` 841 项全过、`ruff check app` 干净；`git diff --check` 干净；perfbaseline 诚实性门禁通过。

## 限制与状态边界

- 本批全部为组件级证据（A/B/E 进程内 fixture + 真实本地加解密/状态文件；C/D 真实子进程 fixture CLI）。没有真实 OpenShell 网关参与，不据此宣称服务级或端到端性能。
- O04 性能结论不能替代 O01–O06 任一功能行；42 项旧测试通过不把 O05/O06 标完成。
- 提交/合并/发布按用户授权另行执行。
