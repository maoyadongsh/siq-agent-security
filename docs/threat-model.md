# 威胁模型（Phase 0 基线）

> 对应设计文档 v0.2 §21 修订版。每条威胁必须可回链到控制与负向测试。

## 信任假设（摘要）

- Agent 内容、Prompt、技能与扫描到的配置均为不可信输入；
- Collector 有限只读、不可全信：上传证据必须签名、身份可即时吊销；
- Edge 是控制面下发任务的执行者，**部署回执可信度以 Edge 完整性为上限**（残余风险，ADR-002）；
- 执行后端（OpenShell）是运行时限制是否生效的权威来源；
- SIQ IAM 是人员/服务身份权威来源（SIQ 部署形态，ADR-010）。

## 威胁 × 控制 × 验证矩阵

| # | 威胁 | 主要控制 | 负向测试/验证 |
| --- | --- | --- | --- |
| T1 | 恶意配置经 Prompt Injection 操纵模型 | 扫描内容为不可信数据；结构化输入输出；模型无写权限；规则+人工复核 | Phase 1 模型评测集（设计文档 §32） |
| T2 | Collector 越界读取 | validate_scope 拒绝空/根/通配；文件与字节上限；本地审计 | connectors/hermes 单测（scope 校验/符号链接逃逸/.env 拒绝） |
| T3 | Secret 泄露到中心或模型 | Edge 侧脱敏 siq.redaction.v1；.env 永不读取；审计摘要只存哈希 | `test_audit_summary_contains_no_secret_content` |
| T4 | 伪造 Agent 或 Evidence | Edge 设备身份 + 注册码一次性；证据签名；稳定来源定位 | `test_enrollment_code_single_use`、`test_wrong_secret_rejected` |
| T5 | 中心任务重放或篡改 | 注册码/secret 哈希；任务 TTL；**任务签名验证 = Phase 0 后续项（TODO）** | 待任务签名落地后补 |
| T6 | Edge 被攻陷后横向移动 | 独立设备身份；最小 Connector 凭据；无中心数据库凭据 | `test_heartbeat_and_revocation`（吊销即时） |
| T7 | 跨租户访问 | 身份派生 tenant；先定位后权限（404 语义）；负向测试 | `test_tenant_isolation.py` 全组 |
| T8 | 权限混淆代理 | 用户/Agent/Edge/Connector/执行后端身份分离；delegated_user 维度 | Phase 2 委托令牌链路测试（依赖 D6） |
| T9 | 未审批策略下发 | 状态机 + SoD + 幂等键 + revision 并发控制 | `test_deployment_requires_approval`、`test_segregation_of_duties` |
| T10 | 带外策略降级 | 有效策略回读、摘要比对、漂移告警 | Phase 3（OpenShell Adapter 交付后） |
| T11 | OpenShell 故障后回退 Host | 默认禁止无隔离回退；已审计回退策略进漂移监控 | Phase 3 故障演练 |
| T12 | 恶意插件或供应链 | 受限子进程、无凭据注入、超时/限额、孤儿证据拒绝 | `test_orphan_evidence_rejected`；Connector 负向语料（设计文档 §32） |
| T13 | 审计被修改 | 审计与状态同事务；追加式语义；导出 | `test_confirm_writes_audit_and_outbox_same_transaction` |
| T14 | 模型幻觉造成误管控 | 模型不产生 effective；证据引用；人工确认 | 设计文档 §31.1 评测集 |
| T15 | 风险接受长期遗忘 | Owner/原因/到期必填；到期重开（worker，Phase 2） | accept-risk 校验（expiry_in_past 422） |
| T16 | 恶意 Agent 本体滥用写权限 | 行为规则（Phase 2）；最小权限；能力令牌 | Phase 2 规则引擎 |
| T17 | 控制面账号接管 | MFA、step-up（Phase 4+）；生产强制 OIDC RS256 | 生产配置门禁（config.py fail-closed） |
| T18 | Agent 间混淆代理/委托链放大 | act chain 追踪；每跳最小 scope | Phase 2+ |
| T19 | 扫描风暴 DoS | 租户级并发/配额（Phase 2）；Connector 限额 | 协议层限额（8MB/60s） |
| T20 | MCP Tool Server 失陷 | 独立身份、工具内容不可信 | Phase 4+ |
| T21 | 时钟偏移 | NTP 要求；任务过期宽容窗口与防重放解耦 | 部署文档要求（待补 runbook） |
| T22 | Agent 绕 Hub 直连模型网关 | agent×model 组合事实 → unknown + 告警（ADR-004） | Phase 2 Resolver 测试 |

## 当前已实现的防线（代码级）

1. 租户隔离（T7）：全部 21 测试中 5 项跨租户负向；
2. Edge 注册与吊销（T4/T6）：注册码单次 + 哈希 + 在线校验；
3. 审计/Outbox 同事务（T13）；
4. SoD + 幂等 + 未批准不可部署（T9）；
5. 策略静态校验与 secret 引用约束（T3 控制面侧）。

## 显式 TODO（不隐藏风险）

| 项 | 风险等级 | 计划 |
| --- | --- | --- |
| Edge 任务签名验证 | 高 | Phase 0 收尾（ADR-002 已记录） |
| Edge 签名密钥持久化（当前每次运行临时生成） | 中 | Phase 1 换控制面签发密钥链 |
| 部署回执独立验证组件评估 | 中 | Phase 4 |
| 租户级扫描配额/并发 | 中 | Phase 2 |
| 风险接受到期自动重开 worker | 低 | Phase 2（services/worker） |
