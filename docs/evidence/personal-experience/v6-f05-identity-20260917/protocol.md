# OpenShell 任务执行性能协议（本批独立 scope）

本协议在测量前冻结；不得因结果调整。凡需要修改，另立协议版本并保留原失败记录。

- 协议 schema：`openshell-taskexec-perf-protocol/v1`
- 冻结时间（UTC）：2026-09-17T10:10:31Z（本批新候选，测量前）
- 候选：`siq-v6-f01-uuid-bound`（本地 dirty 集成候选，非发行制品）
- 候选二进制 SHA256：`ceddc59c929da6ae449fdcb06f5e4f5915bf2e3ca73dad73457be421fbb194e7`
- 源绑定（本地 dirty 差异清单，非干净发行源）：`6a2705d423321ac7cb7b0a5259070aa0c9dc5e2fbfd7e57027eab77a786ea13f`（测量开始时的源快照；二进制在此之前构建，不能据此单独证明可复现构建）
- 后端：`openshell 0.0.83`，共享 gateway `siq-openshell-dev`（本批不重启），endpoint `https://127.0.0.1:17671`
- 宿主：`Linux spark-1319 6.17.0-1014-nvidia aarch64`；Go `go1.26.5 linux/arm64`
- 专属沙箱：`siq-v6-f05-identity-20260917`（本批所有）
- 证据目录：`docs/evidence/personal-experience/v6-f05-identity-20260917/`

## 0. 与既有性能脚本的边界（为什么另立驱动）

现有 `scripts/personal-experience/openshell-b2b3-perf-protocol.py` 的 `doctor_readback` / `doctor_unreachable` 对照，
以及 `aux_control_plane_restore` 辅助控制面恢复，**不包含真正任务 B3**：它不经由
`POST /v1/openshell/task-executions` 发起过任何真实命令执行，其 `"B3": "not_measured"` 是准确的。

因此本批：

- **不改名、不扩写** `openshell-b2b3-perf-protocol.py`，不声称既有测试已覆盖任务执行；
- 新增**独立驱动** `scripts/personal-experience/openshell-o05v6-taskexec-perf.py`，schema `openshell-taskexec-perf/v1`；
- 新增**独立 scope** `task_execution`，其场景不得与 v2 历史记录合并统计；
- v2 历史报告与 `docs/evidence/personal-experience/openshell-o04-perf-*` 一律不覆盖。

## 1. 冻结项

### 1.1 基线选择

| 场景 | 旧候选基线 | 理由 |
| --- | --- | --- |
| S1 `doctor_readback` | **not_measured** | 基线为本集成树基点 `9b8c09af…`；此轮只对新 UUID 绑定候选进行绝对预算测量，未按相同协议独占重测基点。既有 GLM d06 二进制不是基点，不能冒充它。 |
| S2 `policy_load_roundtrip` | **not_measured** | 同 S1；基点有控制面能力，但本轮未测等价基线，不计算相对比值。 |
| S3 `taskexec_read_only` | **not_comparable** | 集成基点 `9b8c09af…` 没有 `/v1/openshell/task-executions` 路由；不把旧 `policy_apply` 对比成任务执行。GLM d06 中间候选已有该能力，但不属于本协议的 main 基点。 |
| S4 `taskexec_status_read` | **not_comparable** | 集成基点 `9b8c09af…` 没有 `/v1/openshell/task-executions/read` 路由。 |

绝对预算仍然冻结并可判定（见 1.6）；相对预算仅对同候选的不同轮次可比。

### 1.2 场景定义

- **S1 `doctor_readback`**：`GET /v1/openshell/doctor`，经产品守护进程（真实 CLI + 真实 gateway）。沿用 v1 既有预算。
- **S2 `policy_load_roundtrip`**：对专属沙箱执行 `openshell policy set --wait --policy <pristine 内层策略文档>`，
  即**内容不变的同内容重载**，完整走「提交 + `--wait` 加载确认」。运行时机：**全部任务采样之前**，
  因为它推进沙箱 Version 计数；其后必须重新读取执行器侧 revision/digest 再进入 S3，不得沿用旧绑定。
- **S3 `taskexec_read_only`**（本批新增 scope）：一条**真实经人工批准**的有界 argv
  （`/bin/sh -c 'printf %s o05v6-perf-<run_id>'`，无网络、无写入），经**生产执行器**
  `POST /v1/openshell/task-executions` 在专属沙箱中真实执行。
  计时区间 = 该 HTTP 请求的往返，即「用户可见总耗时」。
  每样本前的 preview / decide / hold-resolve / 绑定读取全部在**计时区间之外**完成。
  每样本必须通过 `assert_task_executed` 成功形状断言（`ok=true`、`scope=task_execution`、
  `outcome.state=succeeded`、`exit_code=0`、`spawned=true`、`outcome.task_executed=yes`、
  有 observation receipt 与 reservation receipt）。
- **S4 `taskexec_status_read`**：`POST /v1/openshell/task-executions/read`，读取上一条已持久化的执行记录投影。

### 1.3 轮数 / 预热 / 样本量 / 次序

- `ROUNDS = 3`
- `WARMUP = 2`（每轮每场景，**丢弃**，不计入统计）
- `SAMPLES = 15`（每轮每场景，S2 除外）
- `CYCLE_SAMPLES = 5`（每轮，仅 S2）：沿用 `openshell-b2b3-perf-protocol.py` 对昂贵控制面操作使用
  `CYCLE_SAMPLES` 的既有先例，不新设规则。
- **S2 在每轮内最先执行**（若排在其后，其写操作会改变 S3 已绑定的 revision，使场景边界不干净）。
- **S2 与 S3 之间固定插入一个不计时的条件化步骤 `[cond] = await_exec_ready`**：
  轮询 `openshell sandbox exec -n <target> --no-tty -- /bin/echo ready`（单次尝试上限 45 s，
  间隔 5 s，总期限 420 s）直到不再 stall 为止。
  依据：D05 实测记录「`policy update --wait` 之后紧跟一个 1–3 分钟的 `sandbox exec` stall
  （勘察期间复现三次）」，且该 stall 与拒绝无关、不得被读成拒绝。
  若不做条件化就测量 S3，S3 样本会被**环境条件**系统性地污染，而非产品回退；这会让比较失真。
  该步骤的耗时**如实记录**在报告 `environment_conditions.conditioning` 中作参考，
  但**不作为场景样本、不参与任何百分位、不设预算**（它不是被测场景）。
  若条件化在 420 s 内未就绪：按 1.5 失败处理——完整记录并**停止运行**，不重试、不换轮次。
- 每轮次序冻结为：

| 轮 | 次序 |
| --- | --- |
| 1 | S2 → [cond] → S1 → S3 → S4 |
| 2 | S2 → [cond] → S3 → S1 → S4 |
| 3 | S2 → [cond] → S1 → S3 → S4 |

（S2 每轮最先，且每轮都先于该轮的 S3；S1/S3 顺序在轮次间轮转以抵消单调漂移。
轮 1 与轮 3 次序相同是刻意的：轮 2 作为次序对换轮，轮 1/3 作为重复轮，
使「次序」与「轮次」两个因素在 3 轮内不被混淆。）

### 1.4 并发

严格串行：1 个在途请求。测量期间**禁止并行构建、并行回归、其他压测**。
运行前做排他性预检（扫描 `/proc` 中本工作树路径 + `go build`/`go test`/`pytest`/`npm`/`vite`）；
若无法保证独占，记录干扰并**停止该轮**，不挑选好数据。

### 1.5 百分位算法与剔除规则

- 百分位：**nearest-rank on sorted samples**，`ceil(p/100 * n)`；p50/p95/p99 与 max 一并输出。
- 剔除规则：**none**。预热样本按 1.3 的固定规则丢弃，不做任何事后择优。
- 失败处理（冻结）：任一被测量样本出现 refusal、HTTP 非期望码、客户端超时或 CLI stall
  ⇒ 该样本**完整记录为 invalid**（含原始响应/错误与所处轮次），**该轮作废**，并**立即停止整个运行**。
  不重试、不剔除坏样本、不换轮次重跑到绿。失败本身是结果。

### 1.6 冻结预算（p95，毫秒）与预算依据

| 场景 | 冻结预算 p95 | max 上限 | 依据（**测量前**冻结） |
| --- | --- | --- | --- |
| S1 `doctor_readback` | 15000 | 30000 | 沿用 v1 既有预算，不放宽。 |
| S2 `policy_load_roundtrip` | 60000 | 60000 | 沿用既有 `aux_control_plane_restore`（60000 ms）预算：同一类操作（真实 gateway 上的 CLI 策略写 + 加载确认）。D05 实测同内容重载往返 2.1–10.1 s（`policy set --wait` 恢复 9218 ms / fallback 8219 ms；loosen 10143/6171/2165 ms；tighten 8177 ms），全部落在 60 s 内且余量充足。 |
| S3 `taskexec_read_only` | 2000 | 15000 | D05 实测 20 条**成功**执行腿（经生产执行器真实执行）耗时 318–415 ms（E01 403/363/357/320；canary 400/396/354/331；E06 370；拒绝后同一批准仍执行 415/360/353/319）。短只读命令的用户可见目标为亚秒级；取观测最大值的约 4.8 倍作为 p95 预算，max 上限沿用已保留的 15000 ms 上限。 |
| S4 `taskexec_status_read` | 1500 | 15000 | 本地已持久化记录的投影读取（唯一 I/O 是状态存储读）。用户等待目标：列表/详情刷新应在 1.5 s 内可见。 |

测量后**不得放宽**以上预算。

### 1.7 不可得指标（null + 原因）

- 每阶段写次数（fsync 次数、签名次数）：产品未暴露分阶段计数器；为测量而加计数器会改变被测候选本身 ⇒ `null`，原因如实写明。
- 其他由 `null + reason` 按可观测能力填写。

可观测并**必须**填写的：客户端/API 墙钟、S3 的远端执行阶段（取自产品自身返回的 `outcome.started_at`/`finished_at`）、
记录结果阶段（由墙钟 − 远端得到的**派生**值，明确标注 `derived`，不得当作独立测量）、
守护进程 RSS（`/proc/<pid>/status` 的 `VmRSS`/`VmHWM`）、客户端 CPU（`resource.getrusage` 的 user+sys）、
请求/样本计数。

### 1.8 收尾不变量（R2）

运行结束后必须证明：**整段性能旅程没有改动沙箱策略内容**。判定用 `policy get --full` 的 `Hash:` 相等，
而非 revision 相等——S2 的被测量操作是按字节重载 pristine 文档，`policy set` 会在内容不变时也推进 revision。
`base.revision → after.revision` 的差值如实记入步骤 `K90d`，不隐藏、不当作失败。
hash 不等即收尾失败（报告保留前后哈希，以及该轮的完整样本）。

每样本另存 `wall_ms_independent`（驱动侧 `perf_counter`）与产品自报 `duration_ms` 并列；
两者应只相差调用返回后的本地工作量，差值显著更大须在报告中说明。

## 2. 证据分级

| 场景 | 级别 |
| --- | --- |
| S1 `doctor_readback` | `integration_real_gateway_control_plane`（真实 CLI + 真实 gateway，经产品守护进程） |
| S2 `policy_load_roundtrip` | `integration_real_gateway_policy_write`（真实 gateway 策略写 + `--wait` 加载确认） |
| S3 `taskexec_read_only` | `integration_real_gateway_real_sandbox_real_execution`（真实批准、真实生产执行器、真实沙箱内真实进程） |
| S4 `taskexec_status_read` | `integration_real_daemon_state_projection` |

全部为集成级证据：真实 gateway、真实专属沙箱、真实生产执行器。**无浏览器 UI 端到端**
（UI 端到端属 D04/D05 的 Playwright 证据，不在本协议范围）；**无 Windows/macOS 实机**；
**无主机端到端用户旅程**。测量期间不运行全量测试或构建负载。

## 3. 环境条件（如实记录，不因此调整预算）

- `sandbox exec` 在该环境中存在间歇性 stall（§14.6），本地 `--timeout` 不能约束它。
  按 1.5 的失败规则处理：完整记录、作废该轮、停止运行，**不**重试。
- 共享 gateway 由其他协作者共同使用；本批不重启、不修改其配置。

## 4. 冻结修订记录

| 序 | 时间（UTC） | 修订 | 是否已产生测量数据 |
| --- | --- | --- | --- |
| — | 2026-09-16T20:35:00Z | 初次冻结（schema `openshell-taskexec-perf-protocol/v1`） | 否 |
| R1 | 2026-09-16T20:52:00Z | 1.3：在 S2 与 S3 之间插入不计时条件化步骤 `[cond]`，并把每轮次序改为 `S2 → [cond] → {S1,S3 轮转} → S4` | **否**（修订发生在任何样本采集之前） |
| R2 | 2026-09-16T21:10:00Z | 1.8：收尾不变量由「沙箱策略 revision 未变」改为「沙箱策略**内容**未变」（hash 相等），并记录 revision 差值 | **否**（修订发生在任何样本采集之前） |
| R3 | 2026-09-17T09:21:05Z | 本批在测量前绑定新候选/专属目标、将 S1/S2 基点相对值改为 `not_measured`、S3/S4 明确比较基点；S1–S4 绝对预算、样本、轮次、失败规则不变 | **否**（本批尚无样本） |

R1 属**测量前**的冻结订正（初版把 S3 紧排在 `policy set --wait` 之后，会系统性引入 §3 记载的
`sandbox exec` stall），不是测后放宽：预算（1.6）与失败规则（1.5）在 R1 中**未被改动**。

R2 同样属**测量前**的冻结订正，且**不涉及任何冻结参数**（轮次、样本数、次序、并发、百分位、
预算、失败规则一律不变）。它订正的是一条收尾断言与一份陈旧的实现假设之间的冲突：

- 继承自 D02 旅程驱动的收尾断言是 `after.revision == base.revision`，其**本意**是「整段旅程没有
  改动沙箱策略」。在 D02 中它成立，因为那段旅程只写策略、不改内容以外的 revision。
- 本协议的 S2 的**被测量操作本身**就是「按字节重载 pristine 文档」。`policy set` 即使在内容完全
  相同时也会推进 revision，因此该断言在本协议下必然失败——而它失败所报告的「策略被改动」是**假**的。
- R2 把该断言改写为 **hash 相等**（内容未变），并把 `base.revision → after.revision` 的差值如实
  记入 `K90d`。这是**加强**而非放宽：内容比对是「策略未被改动」的直接证据，revision 相等只是它在
  「没有同内容重写」这一额外前提下才成立的代理量。若旅程真的改了策略内容，hash 不等仍然会让收尾
  失败，且失败信息给出前后哈希。

同时（同一时点，纯测量侧加强，非参数变更）测量样本额外记录 `wall_ms_independent`：由驱动自身
`time.perf_counter` 在调用外测得，与产品自报的 `duration_ms` 并列保存。两者之差只应等于调用返回后
驱动本地的工作量（S3 中即执行器断言与摘要证明）；差值显著更大即说明产品自报计时未覆盖其声称的
工作，属于**应当被看见**的结果，而不是被平滑掉的噪声。
本文件在 R1 定稿后的 SHA256 **不写在本文件内**（自指会改变自身哈希，使该值永远不可核验）。
本次复测在命令行以 `--expected-protocol-sha256` 绑定本文件测前 SHA256，并与同目录 `SHA256SUMS` 一致：驱动在运行前重算本文件 sha256，与测前输入不符即**拒绝运行**。原批次不提供该参数时仍使用其历史冻结常量。

本批 R3 协议承继旧协议的测试工作量及绝对预算，但不继承旧候选的性能结论。任务执行的旧候选 GLM d06 存在于另一工作树；它不是本批 main 基点，未按本协议侧测，因此不报告相对改善。

## 5. R4 本次复测冻结说明

2026-09-17T10:10:31Z 在新候选 `ceddc59c929da6ae449fdcb06f5e4f5915bf2e3ca73dad73457be421fbb194e7` 上复用 §1.3–1.8 全部轮数、预热、样本、次序、失败规则和绝对预算。F01 新增批准参数中的沙箱 UUID，只增加执行前只读身份读回；因此旧 r4 性能数字不能替代本候选。目标为本批独占新沙箱，旧 D05 目标不共用。此协议与目标、候选摘要在测量前写定；未测 main 基点相对数，S3/S4 仍不可比。
