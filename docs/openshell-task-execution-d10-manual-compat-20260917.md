# OpenShell 真实任务执行 — D10 迁移 / 兼容 / 用户手册 / 协作者复测清单

> **2026-09-17 复核修正（优先于下文历史状态）**：见[修复与验证报告](evidence/personal-experience/o05-v6-review-20260917-071737/report.md)。停止响应应读 `stop` / `status.stop`；历史 `null` 是取错字段，`unsupported/false` 来自 SIQ 当前实现，不能据此断言网关能力。D03、D05、D07 保持 partial，D09 保持 blocked；D10 历史交付完成不代表新候选实机验收通过。本次修改后的候选必须重新跑真实执行、浏览器及性能腿，旧候选证据不能直接继承。原 27 项 SHA256SUMS 已原样存入复核目录，按数据库迁移路径复核 27/27；原目录现用 24 项公开文件清单。历史报告原文保留，其旧路径/清单数量由本修正覆盖。


- 候选：`agentshield-d06-20260917-043146`（linux/arm64 `166e1757bd4aef6bb9adbf995d862be9560aa75a0cdce53d97bef2c5835ffa45`）
- 本批范围：**开发落盘 + 隔离验证**。本文件**不是**发布说明，**不**声称发布就绪。
- 记账口径：本文件只复述有证据支撑的事实；未闭合项在 §6 逐条列出。

---

## 1. 新增程序面与旧程序的读写边界

### 1.1 新增 HTTP 端点（全部挂在既有 daemon 上，无新监听端口）

| 端点 | 方法 | 能力要求 | 作用 |
|---|---|---|---|
| `/v1/openshell/task-executions` | POST | `capDecision` | 发起**一次真实任务执行**（与既有同名策略端点**不同**） |
| `/v1/openshell/task-executions/preview` | POST | `capAdmin` | 只读预览（**不产生**执行授权、**不产生**预留） |
| `/v1/openshell/task-executions/status` | POST | `capDecision` | 读取本会话/本 agent 视角的状态 |
| `/v1/openshell/task-executions/stop` | POST | `capDecision` | 请求停止（见 §4 停止语义） |
| `/v1/openshell/task-executions/reconcile` | POST | `capAdmin` | 管理员凭外部证据结案（**不重放**） |
| `/v1/openshell/task-executions/read` | POST | `capAdmin` | 管理 UI 使用的只读投影 |

### 1.2 与既有 `/v1/openshell/session-executions` 的边界（**不可混淆**）

- 既有端点 `policy_apply` **不执行任务**，`task_executed` 恒为 `false`；其名字里的 "executions" 指"策略执行的会话"，不是"命令执行"。
- 新增端点执行的是**真实沙箱命令**，其状态合同为 `openshell-task-execution-status/v1`，其中 `task_execution_kind` 恒为 `real_sandbox_command`。
- **本批未修改**既有 `policy_apply` 请求的副作用语义；未把任何历史 `policy_apply` 记录升级成真实执行。两类记录在存储中**可区分**（执行记录带 `task_execution_kind` / `argv_digest` / `execution_id`，策略记录没有）。

### 1.3 存储侧读写边界

- 状态由**验签的事件链与独立签名的计划/发起/结果/停止证据共同投影**，不是进程内注册表。证据文件缺签名、签名不符或预留 ID 不符会返回 503 `task_evidence_unverified`，不会从可编辑 JSON 推断成功；成功还需匹配链上的签名 observation。daemon 重启后不自动重放，旧试验性无签名证据保持不可验证。
- 旧程序（不识别新合同的读者）读到新记录时，应按**未知记录类型**跳过，而不是猜成本地进程成功/失败。
- 新写入**不覆盖**历史 `policy_apply` 记录、既有 receipt 链、task activities 与 audit facts。

---

## 2. 旧 API 保持项（**本批未破坏**）

- `openshell-session-policy-apply/v1` 的请求/响应形状与副作用语义未变。
- 既有确认详情、权限（Authority/SEC/Grant/hold 预留）路径未新增第二套权限系统；真实执行复用**同一套**预留。
- 既有契约文件未做破坏性改写：`packages/contracts/openshell-task-execution*.{md,json}` 为**新增** 8 份，原有 openshell 契约 4 份未动。
- 四平台交叉编译产物标识（`agentshield-linux-amd64` / `agentshield-linux-arm64` / `agentshield-darwin-arm64` / `agentshield-windows-amd64.exe`）与既有命名一致。

---

## 3. 用户手册（个人管理 UI）

### 3.1 一次真实执行的正常路径

1. 在**既有确认详情页**看到 `tool = exec` 且带 `-exec` 预留的确认项 → 面板出现"任务执行"区块（**未新建聊天工作台**）。
2. 点击**预览**：只读，不产生授权、不产生预留。预览显示的是**参数摘要**（默认脱敏）。
3. **批准**该操作后，才会产生预留给执行器；执行器在**写前**与**执行前**各复核一次会话与撤权。
4. 面板按后端事实显示状态；**只有**后端记录的 `succeeded` 才显示"远端退出码 0"。

### 3.2 状态标签与用户应理解的含义

| 状态 | 界面措辞 | 用户应理解 |
|---|---|---|
| `reserved` | 已预留一次执行，尚未启动 | 还没跑 |
| `policy_unverified` | 策略未确认：未发起任务（策略侧事实单独留账） | **没跑**；策略没确认不等于命令没跑，两者分开记账 |
| `denied` | 执行前校验未通过，未产生任务副作用 | 校验拦下了，没跑 |
| `running` | 已启动，结果尚未落盘 | 在跑，还没有结论 |
| `succeeded` | 本地签名结果为 0，且签名观察回执匹配 | 该次命令的成功结果已与回执关联，**不是**界面的猜测 |
| `failed` | 后端已记录非零退出码 N（与本地进程失败无法区分） | 非零；且**无法**区分是远端命令失败还是本地 CLI 进程失败 |
| `output_limited` | 输出超过上限，已截断记录 | 跑完了但输出被截断 |
| `timed_out` | 远端超时 / 本地超时 | 区分是**谁**的超时；本地超时**不代表**远端停了 |
| `stop_requested` | 已请求停止：仅本地 CLI 进程，当前未确认远端停止 | 见 §4 |
| `uncertain` | 执行结果不确定，预留未决，需管理员对账 | **既不能说成功也不能说失败**；找管理员 |
| `reconciled_occurred` / `reconciled_not_occurred` | 管理员凭外部证据结案：确认已发生 / 确认未发生（不重放） | 结论来自**外部证据**，系统**不会**自动重跑 |

### 3.3 用户会遇到的错误与恢复步骤

| 界面结果 | 含义 | 恢复步骤 |
|---|---|---|
| 未登录（401） | 会话失效 | 重新登录；**不要**重复提交执行请求 |
| 非管理员（403） | 当前身份不足 | 换用管理员身份，或放弃 |
| "这不是任务执行"（404，预留不存在/不匹配） | 该确认项不是本控制台可见的任务执行 | **不要**反复刷新；刷新不会让它变成任务 |
| 状态"不确定" | 结果未知 | 联系管理员走 `/reconcile`，凭**外部证据**结案 |
| `task_evidence_unverified`（503） | 本地证据缺签名或绑定不符 | 停止重试执行，保存现场并核对状态/密钥/证据；不得把文件中的成功字段当结果 |
| 提交后网关返回 502 | **发起后结果未知**，不是成功、也**不是**策略阻断 | 按"不确定"处理；**不要**重试到绿 |
| 身份切换 / 手机端 | 由 D05 的浏览器级演练覆盖 | 见 §6 未闭合项 |

---

## 4. 停止语义（**最容易误读的一处**）

- 本批**不承诺**"任意后代进程停止"。当前 SIQ 停止实现仅请求终止本地 CLI，**未接入远端停止确认协议**；以下是 SIQ 写入的字段，不能用来证明 OpenShell CLI v0.0.83 的能力：`remote_stop` 恒为 `unsupported`、`remote_stop_confirmed` 恒为 `false`、`delete_sandbox` 恒为 `false`。
- 因此 `stop` 的诚实结果是 `stop_requested`（`reason_code: openshell_task_stop_requested_local_only`）：**只**停止了本地 CLI 进程。
- **本地 CLI 退出或被 kill，不等于远端任务已停止**；`timed_out` 同理。
- **禁止**用"删除整个沙箱"来冒充停止。
- 用户/协作者注意：看到 `stop_requested` 后，不应假定远端已停；如需确认，走管理员对账。

---

## 5. 安全边界（对用户与协作者的承诺范围）

- 预览、模型输出、管理员登录**都不创造**执行授权；批准一个策略操作**不授权**任意命令。
- 执行参数按**字段 + 最终参数摘要**严格绑定；参数一变即需**重新确认**。
- 复用**既有唯一预留**，**无**第二套权限、**无**仅内存去重、**无**重启自动重放。
- `policy set` 提交/读回**不等于**已加载；加载确认**不等于**通用行为保护。
- 真网阻断只由**明确 HTTP 403 + 独立接收端零到达**证明；未知/网络错误/超时**不算**阻断。
- 参数与输出**默认只存脱敏摘要**；原始文本需**任务级显式 opt-in**；授权期限与保留期限**分开**。
- **未证能力不承诺**：跨进程原子 CAS、任意后代进程停止、exactly-once。

---

## 6. 未闭合项与对协作者的提示（**不得当作已完成**）

| 项 | 状态 | 说明 |
|---|---|---|
| 远端停止确认（`E08h`） | `blocked` | 本批 SIQ 仅停止本地 CLI，未验证后端对单次任务的停止/查询能力；见 §4 |
| 性能相对结论 | `not_comparable` | 缺 rc.6 基线，**不给任何"提速"结论** |
| UI 浏览器级验收 | `not_run` | `ui_acceptance = "not_run"`；401/断连/守护进程重启/移动端/焦点顺序**未在真实浏览器验证** |
| Linux WorkBuddy 宿主 | `blocked` | 本机无真实运行时；**目录存在不等于支持**；`~/.codebuddy` 只是相邻家族安装 |
| 真实公网源（ADR-0051） | `blocked` | 本机 DNS 把 github 三域名解析到非公网段，三条腿 0 ms/0 B 被拒 |
| Windows / macOS 实机 | `external_manual` | 归 sunbo / Luke，本批**未访问、未改写**其工作树 |
| 宿主原生采集 | 未证明 | 各腿 `not_measured` 均含 `native host capture` |
| 授权路径可出网 | 未证明 | 未主张主机级防火墙隔离 |

### 6.1 sunbo / Luke 需要针对**新候选**重测的项目

> 仅列出与新候选（`166e1757…ffa45`）**相关**、必须在各自平台实机重跑的项目。**不代做、不预填结论**，空格由协作者自己跑出来。

1. **Windows / macOS 候选二进制**：`d54208fe…`（linux/amd64）、`17147a38…`（darwin/arm64）、`4b81c5dc…`（windows/amd64）——这三个只是**交叉编译产物摘要**，**不是**平台验收通过。
2. **平台矩阵格**：按 `platform_acceptance.py` 的 8 项检查（`discovery` / `normal_execution` / `pre_execution_denial` / `service_unavailable_denial` / `approval_resume` / `final_parameter_recheck` / `skill_attribution` / `install_interception`）重跑；**workbuddy 格要求 `method == "native_desktop"`**。
3. **D05 浏览器级验收**：401、身份切换、陈旧响应、移动端布局、键盘焦点顺序。
4. **原生采集**：host-native capture 目前**无任何一腿**证明。
5. **桌面通知视觉**：headless 环境**不能**判通过。
6. **旧矩阵留存**：旧矩阵不得改写；新候选建**新**矩阵（见 §7）。

---

## 7. 同候选证据索引（D10）

候选 `166e1757…ffa45` 上、**本批**产生且可追溯到该候选的证据：

| 证据 | 路径 | 与候选的关系 |
|---|---|---|
| D05 验收矩阵 | `docs/evidence/personal-experience/local-o05-v6-20260917-041812/d05-acceptance-matrix.json` | `candidate_sha256` = `166e1757…ffa45`；`226 pass / 0 fail / 234` |
| D06 性能报告 | `docs/evidence/personal-experience/local-o05-v6-20260917-043146/perf-20260917-043358/report.json` | 同候选 + 测量前冻结协议 |
| D07 原生采集/副作用 | `…/local-o05-v6-20260917-043146/d07-20260916-204918/` | B04 导出/到期、B05 失联、Hermes 缺口、r02、r07 |
| D08 服务级网关 | `…/local-o05-v6-20260917-043146/d08-20260916-210508/` | 33/33；失败轮 `…-210248/`、`…-210331/` 原文保留 |
| D09 预检 | `…/local-o05-v6-20260917-043146/d09-20260916-211159/` | 两腿 `blocked`；自测 r2 失败原文保留 |
| 候选清单 | `…/local-o05-v6-20260917-043146/candidate-manifest.json` | 四平台摘要 + git 状态 |

**注意**：`d02-private/`、`d05-private/`、`d06-private/`、`d07-private/`、`d08-private/`、`d09-private/` 为私有原文（0700/0600），**不**列为公开上传对象。
