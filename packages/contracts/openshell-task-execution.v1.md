# Experimental OpenShell real task execution v1

Status: unreleased prototype; executes a command inside an existing sandbox under a separate operation kind.

- L02/O05 真实任务执行与 `siq-openshell-policy-apply`（scope=policy_apply, task_executed=false）是**两个不同操作种类**。旧路由语义不变，不静默升级：任何真实命令执行必须显式走本合同的独立路由与独立批准，调用方必须显式选择。
- 唯一动机是补齐 L02/O05 缺口：在既有 hold 预留、Grant、Authority、SEC 之上执行受批准的命令，并诚实区分「政策副作用」与「任务副作用」。
- 输入必须与已批准 hold 的 params 全量绑定为规范对象：固定 `command=siq-openshell-task-exec`，顶层包含 target、argv、workdir、timeout_seconds、output_limit_bytes、policy_revision、policy_digest、authorization_urls；`openshell_task` 对象包含 target、grant_id、grant_digest、endpoint_fingerprint、**sandbox_id（当前唯一 Ready 实例的 UUID）**。顶层 `authorization_urls` 必须严格等于 `network_targets` 按顺序生成的 `https://host:port` 描述，只供既有 exec 资源解析器检查全部声明目标，不发送 HTTP 请求，不声明后端协议。不能由调用者另选 URL。预览可提供当前 UUID 供构造批准参数，但预览本身不证明策略加载或授权；提交前与启动前均从网关重新读取 UUID，与签名批准的 UUID 不一致时拒绝。此次未发布 v1 原型的收紧会使不含 `sandbox_id` 的旧批准失效，应重新预览并批准，不能沿用旧批准。
- **网络授权列表是资源描述，既不是命令授权也不是后端协议。** 声明目标只用于核对「是否落在当前有效 Grant 的资源范围内」；命令、参数、工作目录、超时与输出上限必须分别校验。声明的目标不是对沙箱实际行为的证明。
- 不允许把任意已批准 exec 的参数用于另一个操作。此 command 仅作协议标记，从不交给 shell。
- 以签名决策的 matched_grant_id 选择唯一 Grant，重新验签、状态、有效期、platform/subject，匹配 permission digest；禁止合并同 target 的其他 Grant。目标必须等于当前 agent/Grant subject；尚无可信异名映射时拒绝，不猜测绑定。
- **任务执行不写策略。** 执行前必须以新的只读双读回确认 `policy get --full` 的 revision/digest 和已加载状态，以及同一 CLI 端点 `sandbox list` 的唯一沙箱 UUID、`Ready` 和相同 `current_policy_version`；或复核本进程成功 `policy set --wait` 后取得的相同事实。v0.0.83 对既有策略返回 `Status: Effective` 且无 `Loaded` 时间戳，此时仅在另一读回确认沙箱已报告加载相同版本后接受；对 `Loaded`/`Active` 状态仍要求有效时间戳。读回/身份/确认期限不符均拒绝，不自动下发、不自动修复。策略下发是另一条操作线，副作用单独记录。批准参数现绑定沙箱 UUID，重启后同名新实例不能消费旧批准；CLI 仍以名称执行，最终 UUID 读回与 `exec -n <name>` 之间缺网关原子性，故不宣称已解决跨进程 TOCTOU。
- 命令以 argv 数组传递，不经主机 shell 拼接。总是插入 `--` 参数终止符，因此 argv 元素不可能被解释为 CLI 选项。拒绝空 argv[0]、控制字符、`..`、相对 workdir、以 `openshell` 为 argv[0]。**不接受调用方自选的凭据或环境变量**（不使用 `--env`），执行环境为固定最小环境。
- 沙箱远端超时用 `--timeout`（后端侧生效）作为主界，本机有界运行器（有界输出 + 硬上限）作为兜底。两者任一触发都必须如实标注是哪一侧触发，且**都不证明远端任务已停止**。
- 预留后、真正发起 exec 前重新验证 Grant/批准参数及会话授权；该检查只是本进程检查，不宣称与网关跨进程原子事务。
- 执行后证据或审计/observation 失败不能返回 ok=true。已发生的副作用不得伪称取消，保留 reservation 和未知状态，不自动重试，不自动重放。
- v6 本地计划、发起、结果与停止证据在写入前由 daemon 密钥按独立域签名；读取时必须验签、核对预留 ID 与记录种类。缺签名/错签名/错预留按 `task_evidence_unverified` 拒绝投影，不能把可编辑 JSON 的 `succeeded` 当作事实。`succeeded` 还要求链上的签名 observation 与**同一结果文档**摘要匹配；仅有本地成功文件但 observation 缺失时显示 `uncertain`。旧试验性无签名证据不自动升级或重放。
- 停止语义：当前 CLI（0.0.83）**没有** sandbox 级 stop/kill/cancel 子命令，`sandbox exec` 也没有后台/分离选项。因此本合同**不承诺「已停止」状态**：只能请求终止本进程启动的 CLI、读回后端事实、进入 `stop_requested`/`uncertain` 并交管理员对账。**删除整个 sandbox 永远不能替代停止任务。**
- 参数与输出默认只存脱敏摘要（argv 只存 digest 与规范化预览，输出只存 digest/长度/退出码）；按任务显式选择才保存原文，原文与授权期限分离保存，键丢失时不自动重建新身份。
- Routes: POST `/v1/openshell/task-executions` (capDecision); `/preview` (capAdmin); `/status` (capDecision); `/stop` (capDecision); `/reconcile` (capAdmin). Existing strict JSON and credential separation apply. No new runtime Authority or grant source is introduced. Preview is advisory and cannot authorize an execution. Reservation uncertainty persists on storage/transport failures.


## 2026-09-17 v6 复核修正

停止响应的事实位于 stop 对象；409 stop_not_observable 响应中位于 status.stop。缺字段、类型不符或与本版 unsupported/false 合同冲突必须判为验收失败，不能自动记 blocked。该常量来自 SIQ 当前实现，不是网关 capability 读回；不能由 null 推断后端能力或承诺仅升级网关即可关闭验收。

ExecTask 在本进程同目标策略锁内读取政策、复核授权并执行，运行结束前同目标 apply/rollback 不得更改策略。后端读取可能阻塞，故其后、spawn 前再复核当前授权。锁等待后必须重读政策与授权；此约束不声明跨进程原子性，也不证明未知远端任务已经结束。

D08 数据库/种子/控制台日志必须在 d08-private 内创建，目录 0700、文件 0600；原始运行材料即使脱敏或仅有哈希也不作为公开数据库提交。

停止及人工对账必须在副作用前持久化请求审计；失败返回 503，不发出停止或对账。已签名对账后完成审计失败返回非成功并明确 reconciled=true，不撤销已记录事实，不邀请重放。
