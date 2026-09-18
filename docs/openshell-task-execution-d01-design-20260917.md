# D01：OpenShell 真实任务执行 — 版本化合同、状态机、崩溃恢复与停止语义

日期：2026-09-17
分支：`glm/local-o05-v6-20260917`
状态：**done**（本文件为 D01 落盘物；配套合同见 `packages/contracts/openshell-task-execution*`）

---

## 0. 本设计的边界前提（先读）

1. **既有 `/v1/openshell/session-executions` 的副作用不变。** 它是 `scope=policy_apply`、`task_executed=false` 的策略应用操作。本设计引入的是**独立操作种类**，调用方必须显式选择新路由并单独批准。旧 v1 请求不得被静默升级为真实命令执行。
2. **任务执行不写策略。** 加载证明有两种来源：本进程观察 `policy set --wait` 成功后的匹配读回，或对已有沙箱进行**新的只读双读回**。执行前均要求 `policy get --full` 的修订与摘要；`Loaded`/`Active` 状态需要有效 `Loaded` 时间标记，v0.0.83 对既有策略返回的 `Effective` 状态没有此标记，必须另由 `sandbox list --output json` 确认唯一目标 UUID、`Ready` 和相同 `current_policy_version`。后者在 v0.0.83 协议中由沙箱报告加载后更新，不能仅由配置文本替代。两种状态都必须读回该沙箱行。证明限本进程使用 5 分钟；spawn 前再次双读回，目标 ID/修订/摘要/加载证据必须匹配。失败、待加载、身份变化、过期或无法解析均拒绝并锁定旧确认，不能靠恢复旧字节自动复活；成功的新策略 `--wait` 可解除锁定，或者同一沙箱 UUID 已报告加载**不同的新修订**时，用新的只读双读回为新批准建立证明。旧批准修订不匹配仍拒绝；未知先前修订与沙箱 UUID 变化不能靠读回解锁。进程重启不会继承旧确认，但可重新取得当前双读回。v6 集成候选现将 UUID 放入签名批准参数，并在预留前重新读回核对；同名新实例不能消费旧批准。不含 UUID 的旧原型批准因此失效，须重新预览并批准。CLI 最终仍按名称执行，UUID 读回与 `exec -n` 之间缺少网关原子事务，跨进程替换的 TOCTOU 边界仍开放；网络 binary 范围也未单独绑定。策略与任务副作用分账。
3. **CLI 能力以实测为准（本批本机 v0.0.83）。** 已确认：`sandbox exec` 存在，带 `-n/--name`、`--workdir`、`--timeout`、`--tty/--no-tty`、`--env`、`<COMMAND>...`；本批使用的 CLI 帮助未提供可绑定单次执行身份的 `stop`/`kill`/`cancel` 命令。SIQ 当前只实现本地 CLI 终止，尚未验证后端单任务停止/查询协议，因此**不承诺远端 `stopped` 状态**。详见 §5。
   - 路径陷阱：`command -v openshell` 解析到 `/home/maoyd/.local/bin/openshell`（0.0.13），该版本**没有** `sandbox exec`。必须使用 `SIQ_AS_OPENSHELL_CLI_BIN` 指向的工具链版本。
4. **不新建第二套权限来源。** 复用 Authority / SEC / Intent / Grant 与 `internal/receipt` 的 hold-execution 预留。预览、管理员登录、模型输出都不产生执行授权。

---

## 1. 状态转移表

状态枚举定义在 `packages/contracts/openshell-task-execution-status.v1.schema.json`（12 个状态）。
**刻意缺席：`stopped`。** 理由见 §5。

| # | 状态 | 含义（可由什么证明） | 允许转移至 | 终态 |
|---|---|---|---|---|
| 1 | `denied` | 绑定校验失败，未产生任何外部副作用 | （终态） | ✅ |
| 2 | `reserved` | 已写入持久预留回执；尚**未**发起外部执行 | `policy_unverified`、`running`、`reservation_expired`、`uncertain`、`denied` | |
| 3 | `policy_unverified` | 预留已建立，但策略读回与批准值不符或读不到 | `running`（读回恢复一致且**重验**通过）、`uncertain`、`reconciled_not_occurred` | |
| 4 | `running` | 真实子进程已发起（有 `started_at`） | `succeeded`、`failed`、`output_limited`、`timed_out`、`stop_requested`、`uncertain` | |
| 5 | `succeeded` | 远端退出码 0 且有输出摘要 | （终态） | ✅ |
| 6 | `failed` | 远端退出码非 0 且有输出摘要 | （终态） | ✅ |
| 7 | `output_limited` | 输出超过 `output_limit_bytes` 被截断；**不**等价于任务失败 | （终态） | ✅ |
| 8 | `timed_out` | 有界等待触发；`timeout_bound_that_fired` ∈ {`remote`, `local`} | （终态；远端是否仍在运行**未知**） | ✅ |
| 9 | `stop_requested` | 停止请求已记录；**仅**证明本地 CLI 终止 | `uncertain`、`reconciled_occurred`、`reconciled_not_occurred` | |
| 10 | `uncertain` | 结果不可知（传输中断/落盘失败/响应丢失） | `reconciled_occurred`、`reconciled_not_occurred` | |
| 11 | `reconciled_occurred` | 管理员凭外部证据结案：确实发生过 | （终态） | ✅ |
| 12 | `reconciled_not_occurred` | 管理员凭外部证据结案：确实未发生 | （终态） | ✅ |

### 1.1 转移不变量（每条都有对应负向用例）

- **I1 单向性**：终态无出边。任何"终态 → 其他"的写入必须拒绝。
- **I2 副作用先于状态**：进入 `reserved` 必须先有已落盘的预留回执（`reservation_receipt_id` 必填）。禁止先写内存状态再补回执。
- **I3 未证不发生**：`uncertain` **只能**由管理员对账收敛为 `reconciled_*`，**不得**自动变为 `failed` / `succeeded` / `denied`。反之，`reconciled_not_occurred` 也**不得**自动变回 `denied`（不能把不确定改写成"从未执行"）。
- **I4 无自动重放**：任何状态的恢复路径都只能**读**。`reserved` 在重启后不会被自动推进到 `running`。
- **I5 停止不越权**：`stop_requested` 不承诺 `remote_stop_confirmed=true`（恒为 `false`，见 §5）。
- **I6 分账**：`policy_unverified` 记录策略侧事实，`running`/`succeeded`/`failed` 记录任务侧事实；两者不互相覆盖。
- **I7 超时不等价于失败**：`timed_out` 不得染成 `failed`——远端可能仍在跑。

---

## 2. 错误码 / HTTP 映射

`reason_code` 枚举与 HTTP 状态的映射。原则：**能证明无副作用 → 4xx；不能证明 → 5xx + `uncertain`。**

> **实现修订（D03）**：以下表格已按 `internal/server/openshell_task_exec.go` 与
> `internal/server/openshell_task_track.go` 的实际实现校正。D01 初稿把读写两类
> 路由混在同一张表里，且有几个码在实现中已被更精确的码取代。表中标注
> "未使用"的码是设计意图中保留、但当前实现**不会**发出的，列出以免被误读为已有能力。

#### 2.0.1 执行路由（`POST /v1/openshell/task-executions`）——HTTP 状态即结论

| reason_code | HTTP | 语义 | 副作用可证性 |
|---|---|---|---|
| （无；`ok=true` + `task_executed=yes`） | 200 | 记录为远端退出码 0 | 已发生 |
| `execution_refused` | 409 | 预检拒绝；可证未 spawn，故**自动**对账 `not_occurred` | 无 |
| `execution_stopped_before_spawn` | 409 | 停止在子进程启动前到达；未发起命令，**自动**对账 `not_occurred` | 无 |
| `execution_stopped_after_spawn_uncertain` | 502 | spawn 之后才收到本地停止；SIQ 未取得远端停止确认，**不**自动对账 | **未知** |
| `task_failed` | 502 | 非零退出与 CLI 侧失败不可区分；预留保持未决 | **未知** |
| `execution_uncertain` | 502 | 本地边界触发（`timeout`/`output_limit`/`pipe_timeout`） | **未知** |
| `execution_evidence_incomplete` | 503 | 证据/审计落盘失败，**不报成功** | **未知** |
| `task_plan_not_persisted` | 503 | 执行前的计划证据未落盘，未发起外部副作用 | 无 |
| `task_start_not_persisted` | 503 | 发起记录未落盘；当前处理路径尚未调用任务执行器 | 本次未发起任务 |
| `openshell_task_policy_not_loaded` | 409 | 预留前加载确认或读回未通过，批准仍可用；预留后复检失败则按 `execution_refused` 处理 | 本次未发起任务 |
| `openshell_task_backend_unbound` | 503 | 后端指纹为空或 required 后端失联 | 无（**禁止 native 回落**） |
| `openshell_task_denied_binding` | 403 | 参数/目标/策略摘要与批准不符 | 无 |
| `openshell_task_denied_grant` | 403 | Grant 失效/过期/平台主体不符/摘要不符；**策略拒绝也归此码** | 无 |
| `openshell_task_reservation_expired` | 409/410 | 预留已过期 | 无 |
| `invalid_openshell_task_shape` | 400 | 请求结构校验失败 | — |

#### 2.0.2 读路由（`status` / `stop` / `reconcile`）——HTTP 200 + 状态文档

状态码**只**表示"这次读取/记录是否成功"，**不**表示任务成功。判定写在响应体的
`state` 与 `reason_code` 里。此时 200 是常态：一个失败的任务、一个被拒绝的执行、
一个只请求到本地终止的停止，都以 200 返回一份如实的文档。

| reason_code | state | 语义 | 副作用可证性 |
|---|---|---|---|
| `openshell_task_reserved` | `reserved` | 已写持久预留，**无任何发起记录** | 无 |
| `openshell_task_running` | `running` | 本进程正在观测该任务（仅进程内事实） | 已发起，结果未知 |
| `openshell_task_succeeded` | `succeeded` | 本地签名结果为退出码 0，且签名 observation 摘要匹配 | 已发生 |
| `openshell_task_failed` | `failed` | 非零退出或 CLI 侧失败不能区分；预留仍待对账 | 是否发生未知 |
| `openshell_task_output_limited` | `output_limited` | 输出超批准上限；远端可能仍在运行 | **未知** |
| `openshell_task_timeout_local` | `timed_out` | 本地有界观测触发；**不主张**后端 `--timeout` | **未知** |
| `openshell_task_stop_requested_local_only` | `stop_requested` | 仅本地 CLI 终止请求；`remote_stop=unsupported` | **未知** |
| `openshell_task_result_uncertain` | `uncertain` | 记录不足以支撑终态 | **未知** |
| `openshell_task_confirmed_occurred` | `reconciled_occurred` | 管理员凭外部证据结案；**不重放、不改写既有观测** | 已发生 |
| `openshell_task_confirmed_not_occurred` | `reconciled_not_occurred` | 同上，结案为未发生 | 无 |
| `openshell_task_policy_not_loaded` | `policy_unverified` | 已预留后发现加载确认/策略读回不匹配；任务侧未发起 | 无任务副作用；策略侧事实单独留账 |
| `openshell_task_backend_unbound` | `denied` | 后端指纹为空；拒绝执行且不回落 native | 无 |
| `openshell_task_denied_binding` | `denied` | 执行前校验未通过 | 无 |
| `openshell_task_denied_grant` | `denied` | 授权校验未通过 | 无 |
| `openshell_task_reservation_expired` | `denied` | 预留过期；未发起任何执行 | 无 |
| `openshell_chain_unverified` | — | **503**：链验签失败，不据未验证字节报任何状态 | 不可证 |
| `openshell_task_reservation_unknown` | — | **404**：该预留不在链上 | — |
| `openshell_task_reservation_mismatch` | — | **404**：请求身份与签名预留不一致（**不区分**"不存在"与"不属于你"） | — |
| `task_evidence_unreadable` | — | **503**：已有证据不可解析/不可读 | 不可证 |
| `task_evidence_unverified` | — | **503**：计划、发起、结果或停止证据缺签名、签名无效、种类或预留 ID 不符 | 不可证 |
| `task_plan_missing` | — | **503**：停止需要计划证据却缺失，未发出终止 | 无 |
| `invalid_openshell_task_status_shape` / `_stop_shape` / `_reconcile_shape` | — | **400**：结构校验失败 | — |
| `openshell_task_stop_identity_mismatch` | — | **403**：停止命名的任务不属于该预留；**未发出任何终止动作** | 无 |
| `openshell_task_reconcile_identity_mismatch` | — | **403**：对账的身份/摘要与预留不符 | 无 |
| `stop_not_recorded` | — | **503**：停止记录未落盘，因此**未**发出终止 | 无 |
| `stop_not_observable` | — | **409**：本进程未观测到该任务，**未发出任何终止**；本地未运行 ≠ 远端已停止 | 无 |
| `openshell_task_reconcile_conflict` | — | **409**：与既有结案结论相反，**不覆盖** | — |
| `openshell_task_reconcile_invalid` | — | **400**：对账结构本身不合法 | — |

#### 2.0.3 设计意图保留但**当前实现不发出**的码

| reason_code | 原因 |
|---|---|
| `openshell_task_timeout_remote` | 远端超时与普通非零退出在本地不可区分，因此**永不主张**；本地边界统一记 `openshell_task_timeout_local` |
| `openshell_task_denied_policy` | 执行器的策略拒绝以 `openshell_task_not_authorized` 上报，投影归入 `openshell_task_denied_grant`；执行器与投影的分类口径不同，已在 D10 手册中显式记录 |
| `openshell_task_stopped` | SIQ 未取得远端单任务停止确认，不存在可证的远端“已停止”状态 |
| `denied_policy` / `terminated` 作为 **state** | 同上 |

### 2.1 HTTP 状态专有约定

- **409 Conflict** 仅用于"可证明的冲突"：预检拒绝与 spawn 前停止（可证未发起），以及
  与既有结案相反的重复对账。读路由的 `stop_not_observable` 同样是 409——它证明的是
  **本进程未发出终止**，不是任务已停止。
- **502** 用于"发起后未知"：**不报成功**，状态置 `uncertain`，提供对账入口。
- **503** 用于"依赖不可用"：链验签失败、证据不可读、落盘失败。**绝不降级为本地 native 执行。**
- 证据/审计落盘失败时**不得**返回 200——沿用既有 `execution_evidence_incomplete` 模式。
- **200 不等于成功**：读路由（`status`/`stop`/`reconcile`）只要成功读到/写下状态就返回 200，
  结论在 `state` 字段里。消费方**必须**读 `state`/`reason_code`，不得以 HTTP 码推断任务结果。
- 停止成功（200）同样**不**主张远端已停止：响应恒带
  `remote_stop="unsupported"`、`remote_stop_confirmed=false`，且记录中 `delete_sandbox` 恒为 `false`
  （用删除整个 sandbox 代替停止是明确禁止的）。

---

## 3. 权限矩阵

| 路由 | 方法 | capability | 授权解析 | 说明 |
|---|---|---|---|---|
| `/v1/openshell/task-executions` | POST | `capDecision` | `authorizeDecision`（scope 化运行身份） | 真实执行入口；body 必须带顶层 `platform`/`agent_id`/`session_id`（`decisionTuple` 依赖） |
| `/v1/openshell/task-executions/preview` | POST | `capAdmin` | 全局凭据 | 只读预演，**不产生授权、不预留** |
| `/v1/openshell/task-executions/status` | POST | `capDecision` | `authorizeDecision` | 读持久状态；须带 `action_id` + `decision_receipt_id` + `reservation_receipt_id` |
| `/v1/openshell/task-executions/stop` | POST | `capDecision` | `authorizeDecision` | 须校验**任务归属**（target/session/agent 与预留一致） |
| `/v1/openshell/task-executions/reconcile` | POST | `capAdmin` | 全局凭据 | 管理员对账；只读结案 |
| `/v1/openshell/task-executions/read` | POST | `capAdmin` | 全局凭据 | **D04 补充**：管理控制台读**同一份**投影。与 `/status` 注册的是**同一个 handler**，只有闸门不同（"一条读路径，两道闸门"）；不新增执行/停止/对账能力 |

### 3.1 权限不变量

- **P1** 新路由必须注册进 `isDecisionPath`（`capDecision` 三条），否则 `authorizeDecision` 不生效。
- **P2** 预览/登录/模型输出**不能**生成执行授权：`preview` 返回体里 `execution_constraints_verified` 与 `task_executed` 恒为 `false`（schema `const` 强制）。
- **P3** 审批策略操作（`siq-openshell-policy-apply`）**不**授权任意命令。命令授权来自签名决策的 `matched_grant_id`，且必须逐项核对命令、argv、workdir、网络目标、文件权限。
- **P4** 网络授权列表是**资源描述**，既不是命令授权也不是后端协议。`authorization_urls` 必须由 `network_targets` 严格推导（`https://host:port`），**不得**由调用方自选。
- **P5** 停止/对账同样走后端权限校验，UI 的按钮可见性不构成授权。
- **P6** 不新增权限来源；复用 Authority/SEC/Intent/Grant 与其 required 规则，不绕过。
- **P7 身份核对只依据签名预留，不依据请求自述。** 共享读路径 `matchesRequest` 逐项比对
  `platform` / `session_id` / `agent_id`（对 `target`） / `tool` / `action_id` / `decision_receipt_id`；
  可选的 `task_id` / `runtime_task_id` 若请求提供则必须与预留一致，未提供则不参与比对。
  请求自述的任何身份字段都不构成"这是你的任务"的证据。差别只在**拒绝形态**：
  - `stop` → **403** `openshell_task_stop_identity_mismatch`（调用方对同一预留持有决策凭据）；
  - `status` → **404** `openshell_task_reservation_mismatch`（**故意不区分**"预留不存在"与"预留不属于你"，
    避免把该路由变成预留 id 的存在性探针）；
  - `reconcile` → **403** `openshell_task_reconcile_identity_mismatch`；相反结论 → **409** `..._conflict`。
- **P8 停止的落盘严格先于动作。** 顺序恒为：链校验 → 归属校验 → 读证据 →
  在同一进程内锁定本地句柄并读取观测事实 → **先写停止记录** → 锁内取消该句柄。
  这样完成与停止并发时不会在句柄释放后仍误报已发本地取消。停止记录写失败 ⇒ **503 `stop_not_recorded` 且不发动作**；
  本进程未观测到该任务 ⇒ **409 `stop_not_observable` 且不发动作**。"本地没在跑"**不等于**"远端已停止"。
- **P9 管理台读路径 = 同一 handler，另一道闸门（D04 决策记录）。**
  **问题**：D04 要求管理台能读出"我批准的那个任务后来怎么样了"。但管理台只持管理员会话，
  **从不持决策凭据**；而 `auth`（`internal/server/authz.go:214`）的规则是
  `need := capAdmin; if len(caps) == 1 { need = caps[0] }` —— **变参形式无法表达"决策或管理员"**，
  给 `/status` 传两个 capability 反而会把 `need` 落回 `capAdmin`，**把决策凭据挡在门外**，与意图相反。
  **备选与取舍**：
  1. 加宽 `/status` 接受两种凭据 —— 被否，见上（且会让两条路由的语义纠缠在一处）；
  2. 管理台改用决策凭据 —— 被否，等于把执行授权发给浏览器；
  3. **新增 `/v1/openshell/task-executions/read`，`capAdmin`，注册同一个 `openshellTaskStatus`** —— **采用**。
  **为什么这不违反 §4.1**（不创造执行授权）：
  - 它**不产生**任何执行授权：handler 是纯读投影，`openshellTaskStatus` 内**没有**任何指向
    `ExecTask` / `ReserveHoldExecution` / `StopLocalTask` / engine 的分支；
  - 它**不扩大**管理员的既有能力：管理员会话本来就能读整条签名链（`/v1/receipts`），
    本来就能给这些预留结案（`/reconcile`）；`/read` 只加了**解释层**；
  - 它**不降低**脱敏：同一 handler ⇒ 同一投影 ⇒ 输出仍是摘要（`raw_stored=false` / `raw_opt_in=false`），
    凭据更宽带来的是**可达性**，不是**细节**（已由测试断言）。
  **两条路由不会漂移**：注册的是同一个函数，不存在"两份对同一执行给出不同说法"的可能；
  测试用 `reflect.DeepEqual` 把这句话钉成事实（成功态与失败态各一次）。
  **`/read` 故意不进 `isDecisionPath`**（P1 只约束 `capDecision` 三条）：它走 `capAdmin` 分支，
  靠 `validAdminSession` 校验。凭据矩阵已由测试固定：管理员 200 / 决策凭据 403
  （`decision credential cannot call admin endpoints`）/ 无 401 / 未知 401；
  同时断言 `/status` 对管理员会话仍为 **401** —— 加读路径**没有**反向打开决策路由。
  **读不产生副作用**（测试固定）：读前后链长度不变；读不新增停止证据文件；
  把 stop / reconcile 形状的 body 投给 `/read` 一律 **400**（严格解码器 `DisallowUnknownFields`
  先拒未知字段），且链长度仍不变。

---

## 4. 崩溃点表

任务书 §8 的六个注入点，逐条给出：崩溃时机、重启后**可证**的事实、**唯一允许**的恢复动作、以及与旧 policy_apply 路径的叠加影响。

| # | 崩溃点 | 崩溃时已落盘 | 重启后可证 | 允许的恢复动作 | 禁止 |
|---|---|---|---|---|---|
| C1 | 预留后未发起 | 预留回执（签名） | `reserved`；**无任务副作用** | 只读投影为 `reserved`；超期则 `reservation_expired` | 自动发起任务；自动推进到 `running` |
| C2 | 策略提交后未确认 | 策略操作回执；任务预留回执 | 策略侧**可能已生效**；任务侧**未发起** | 分别记两本账；读回校验后由新决策重新批准 | 把"任务未启动"推成"整次操作无副作用" |
| C3 | 加载完成但任务未发起 | 同 C2 + 加载确认 | 策略已加载；任务未发起 | 同 C2 | 复用旧批准直接发起（须重验撤权/会话） |
| C4 | 后端已接受任务但响应丢失 | 预留回执；**无**结果回执 | **不可知** → `uncertain` | 只读对账（管理员证据） | 自动重试；报成功；报失败 |
| C5 | 任务结束但结果未落盘 | 预留回执；无结果回执 | **不可知** → `uncertain` | 同上 | 自动重放；把 `uncertain` 改写成 `denied` |
| C6 | 停止已发出但无法读回 | 停止请求记录 | 本地 CLI 已终止；**远端未知** | 保持 `stop_requested` → `uncertain`；管理员对账 | 报 `stopped`；删除 sandbox 冒充停止 |

### 4.1 恢复的通用规则

- **R1 启动重建只依据验签链。** 沿用 `receipt.restoreActionState()` 的既有模式：启动时**验签**遍历回执链重建只读投影。进程内 registry（`osExecBindings` 等）**不得**作为跨重启事实源。
- **R2 默认只读。** 恢复动作只有"读 + 展现 + 等管理员对账"。
- **R3 缺失密钥不重建身份。** 历史签名密钥缺失时，不得自动生成新身份。
- **R4 预留一次性。** 对账结案后旧批准不可重新消费；再次运行必须重新取得有效权限与**新**预留。
- **R5 外部策略漂移下拒绝自动回滚。**

---

## 5. 停止语义与能力缺口（**必须显式记录的限制**）

**已实测的事实（v0.0.83 `--help`，只读）：**

- `openshell sandbox` 子命令仅：`create, get, list, delete, exec, connect, upload, download, ssh-config, provider`。**无 `stop` / `kill` / `cancel`。**
- `openshell sandbox exec [OPTIONS] <COMMAND>...`，**无 detach / background**。`--timeout <SECONDS>` 为后端侧超时（`0` = 无超时，默认 0）。
- `--env <KEY=VALUE>` 可重复 —— **客户端可选凭据注入向量，本实现不使用**。

**据此的保守设计：**

1. 状态机**不含** `stopped`；`stop.remote_stop` 恒为 `unsupported`，`remote_stop_confirmed` 恒为 `false`（schema `const` 强制，无法误报）。
2. `/stop` 只承诺**本地 CLI 终止**，且必须先校验任务归属（target/session/agent/预留一致）；错误目标必须拒绝（403，见 P7）。停止记录**先落盘再发动作**（见 P8）：记录写不下就不发动作（503 `stop_not_recorded`），本进程没观测到就不发动作（409 `stop_not_observable`）。
2.1 停止路由的**成功响应**也只报告"请求已记录"：`local_cli_termination` 取 `requested`/`not_running`（当下事实），`remote_stop`/`remote_stop_confirmed` 恒为常量。**D03 未新增任何远端停止能力**，该腿保持 `partial`。
3. `openshell-task-execution-stop.v1.schema.json` 含 `delete_sandbox: {"const": false}`，使"删沙箱冒充停止"在**协议层不可能**表达。
4. 超时主界为**后端 `--timeout`**，本地有界 runner 为兜底；记录哪个界触发（`timeout_bound_that_fired`）。**两者都不证明远端任务已停止。**
5. E08 的远端确认腿在本机不可得 → 该项保持 `partial`/`blocked`，**不得**宣布 O05 整体完成。

---

## 6. 兼容说明

| 面 | 旧行为（必须保留） | 新行为 |
|---|---|---|
| `/v1/openshell/session-executions` | 只应用策略；响应含 `scope: "policy_apply"`, `task_executed: false` | **完全不变** |
| 操作种类标识 | `command = "siq-openshell-policy-apply"` | `command = "siq-openshell-task-exec"` |
| 批准语义 | 批准策略操作 | **不**继承；执行须独立批准 |
| 预留 | `hold-execution-reserve/v1` | **复用同一套**（唯一预留），不建第二套 |
| 回执链 | `decision` / `hold_reservation` / `observation` / `hold_reconciliation` | 追加任务执行事件与结果投影；**同一验签链** |
| 前端 | OpenShell 诊断 + 确认页 | 新增组件**嵌入**既有确认/任务活动页；不新建聊天工作台 |
| 未配置 OpenShell | native 平台管理能力正常 | **不变**；required 任务明确拒绝，不静默切换 |

**C1–C6 对 policy_apply 路径的影响：** 无。旧路径不涉及任务发起，其崩溃点在既有设计内已处理（CAS 冲突可证无写入并自动对账 `not_occurred`）。新路径产生的 `uncertain` **不**回写旧路径的状态。

---

## 7. 威胁边界

### 7.1 明确不承诺的能力

- ❌ **跨进程原子 CAS**（Go 侧与后端之间无该原语）。并发窗口见 §7.2。
- ❌ **任意后代进程停止**（远端进程树不可枚举）。
- ❌ **exactly-once**（最多"不重复发起"，且仅在可证的崩溃点上）。
- ❌ **远端任务停止确认**（CLI 无此能力，§5）。

### 7.2 并发与竞态的可检测边界

- **同 target 权限扩大**：任务运行中，**本进程**不得对同一 target 执行扩大权限的策略操作。进入执行前以预留 + 读前重验锁定；发现策略修订在预留后变化 → 拒绝启动（`policy_unverified`）。
- **跨进程**：无全局原子能力。**检测条件**：执行前与启动前的两次读回（revision+digest）不一致即拒绝。**不宣称**已消除该窗口，只宣称"可检测 + 失败关闭"。
- **重复请求**：靠**持久预留**（非内存去重）保证最多一个进入执行；第二个请求得到冲突响应，不新增执行次数。

### 7.3 输入侧威胁

| 威胁 | 处置 |
|---|---|
| 选项注入（argv 被当 CLI 选项读） | 固定 CLI 操作；argv 数组传递；始终插入 `--` 终止符 |
| 宿主 shell 拼接 | **禁止**；不把调用方字符串拼进宿主 shell |
| 沙箱内解释器 | 解释器与脚本本身必须纳入授权、摘要与受限权限 |
| 空/畸形 argv[0]、控制字符、`..`、相对 workdir、argv[0]=`openshell` | 拒绝 |
| `--env` 凭据注入 | **不使用**；固定最小环境 |
| 客户端自选 target 归属 | 不扩展任意 target 映射；沿用可信约束。异名映射须先有持久可验证绑定 + 拒绝用例 |
| 输出泄密 | 默认只存脱敏摘要；原文按任务**显式 opt-in**（`raw_stored ⇒ raw_opt_in` 由 schema 强制）；`store_raw_output` 恒 `false` |
| 授权期 vs 保留期混淆 | 两者分开记录，不复用同一时钟/字段 |

### 7.4 停止/对账侧威胁

| 威胁 | 处置 |
|---|---|
| 用 PID 或 sandbox 名冒充归属 | 停止必须绑定操作身份（预留 + 决策 + target/session/agent） |
| 删沙箱冒充停止 | 协议层 `delete_sandbox: const false` |
| 把"本地 CLI 退出"当"远端已停" | 状态恒 `stop_requested`/`uncertain`，永不 `stopped` |
| 对账洗白不确定 | 对账只做只读结案，绑定 reservation/hash/当前管理员身份，保留原始记录；有证据才结案 |
| 对账后重放 | 旧批准不可重新消费，须新预留 |

### 7.5 后端失联

required 后端断连 → 503 `openshell_backend_unbound`，**禁止** native 回落；本机合成文件与远端接收计数共同证明无绕行。

---

## 8. 交付物清单（D01）

| 文件 | 作用 |
|---|---|
| `packages/contracts/openshell-task-execution.v1.md` | 版本化合同正文 |
| `packages/contracts/openshell-task-execution-request.v1.schema.json` | 执行请求 |
| `packages/contracts/openshell-task-execution-status.v1.schema.json` | 持久状态（12 状态 + reason_code + stop/output + allOf 不变量） |
| `packages/contracts/openshell-task-execution-status-request.v1.schema.json` | 状态查询请求 |
| `packages/contracts/openshell-task-execution-stop.v1.schema.json` | 停止请求 |
| `packages/contracts/openshell-task-execution-reconcile.v1.schema.json` | 管理员对账 |
| `packages/contracts/openshell-task-execution-preview.v1.schema.json` | 只读预演（恒非授权） |
| `apps/control-api/app/tests/test_schema_contracts.py` | 新增合同测试（正向 + 逐必填负向 + 边界负向） |
| 本文件 | 六项设计落盘物 |

---

## 9. 未决 / 需后继阶段确认

- `timed_out` 之后远端是否仍在运行，**当前无手段可证**。若未来 CLI 提供 sandbox 内 `ps`/`kill`，可在**已有授权范围内**新增只读探测；在具备前维持 `uncertain`。
- 执行身份（`openshell` 侧是否有可读的任务身份）**未获得**；若后端提供执行回执 ID，应绑定进状态并进入签名链。当前以预留回执 ID 作为任务身份锚点（`osx-` 前缀证据 ID 沿用既有模式）。
