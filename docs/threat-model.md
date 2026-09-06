# 威胁模型（可运行基线）

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
| T3 | Secret 泄露到中心或模型 | Edge 侧脱敏 siq.redaction.v1；.env 永不读取；策略只接受 Secret 引用；持久化错误只存类型+哈希 | `test_audit_summary_contains_no_secret_content`、`test_provider_failure_persistence_contains_only_error_reference` |
| T4 | 伪造 Agent 或 Evidence | Edge 设备身份 + 注册码一次性；Evidence/批次 Ed25519 签名；任务绑定 | `test_tampered_or_unbound_evidence_batch_is_rejected`、`test_enrollment_code_single_use` |
| T5 | 中心任务重放或篡改 | Ed25519 任务签名（信封含环境绑定）+ Edge fail-closed 验签；任务 TTL；上传结果摘要幂等 | `test_signing.py` + Go `signature_test.go`/`evidence_test.go` 跨语言夹具 |
| T6 | Edge 被攻陷后横向移动 | 独立设备身份；最小 Connector 凭据；无中心数据库凭据 | `test_heartbeat_and_revocation`（吊销即时） |
| T7 | 跨租户访问 | 身份派生 tenant；先定位后权限（404 语义）；负向测试 | `test_tenant_isolation.py` 全组 |
| T8 | 权限混淆代理 | 用户/Agent/Edge/Connector/执行后端身份分离；delegated_user 维度 | Phase 2 委托令牌链路测试（依赖 D6） |
| T9 | 未审批策略下发 | 状态机 + SoD（break_glass 不豁免）+ break_glass 独立权限点 `change:break_glass` + 幂等键 + revision 并发控制 | `test_deployment_requires_approval`、`test_segregation_of_duties`、`test_break_glass_requires_dedicated_permission`、`test_break_glass_sod_applies_same_person_rejected` |
| T10 | 带外策略降级 | 有效策略回读、revision 比对、漂移 Finding；OpenShell 同步按环境+已生效 target 绑定 | `test_drift_revision_mismatch_creates_high_finding`、`test_sync_openshell_writes_effective_facts` |
| T11 | OpenShell 故障后回退 Host | 默认禁止无隔离回退；已审计回退策略进漂移监控 | Phase 3 故障演练 |
| T12 | 恶意插件或供应链 | 受限子进程、无凭据注入、超时/限额、孤儿证据拒绝 | `test_orphan_evidence_rejected`；Connector 负向语料（设计文档 §32） |
| T13 | 审计被修改 | 审计与状态同事务；追加式语义；导出 | `test_confirm_writes_audit_and_outbox_same_transaction` |
| T14 | 模型幻觉造成误管控 | 模型不产生 effective；证据引用；人工确认 | 设计文档 §31.1 评测集 |
| T15 | 风险接受长期遗忘 | Owner/原因/到期必填；到期自动回到 open 并发送 reopened 事件 | `test_worker_once_reaps_expired_risk_acceptance` |
| T16 | 恶意 Agent 本体滥用写权限 | 行为规则（Phase 2）；最小权限；能力令牌 | Phase 2 规则引擎 |
| T17 | 控制面账号接管 | MFA、step-up（Phase 4+）；生产强制 OIDC RS256 | 生产配置门禁（config.py fail-closed） |
| T18 | Agent 间混淆代理/委托链放大 | act chain 追踪；每跳最小 scope | Phase 2+ |
| T19 | 扫描风暴 DoS | 租户 pending 任务配额；Connector 8MiB/60s；上传体 8MiB 流式上限 | `test_scan_quota_per_tenant`、`test_edge_batch_declared_over_size_limit_is_rejected_before_parsing` |
| T20 | MCP Tool Server 失陷 | 独立身份、工具内容不可信 | Phase 4+ |
| T21 | 时钟偏移 | NTP 要求；任务过期宽容窗口与防重放解耦 | 部署文档要求（待补 runbook） |
| T22 | Agent 绕 Hub 直连模型网关 | agent×model 组合事实 → unknown + 告警（ADR-004） | Phase 2 Resolver 测试 |

## 当前已实现的防线（代码级）

1. 租户/环境隔离与对象 404 语义（T7）；
2. Edge 注册、吊销、任务验签、Evidence/批次验签与重放拒绝（T4–T6）；
3. 审计/Outbox 同事务，敏感错误仅存指纹（T3/T13）；
4. SoD + 幂等 + 未批准不可部署 + Break-glass 到期复核（T9/T15）；
5. 生产 PostgreSQL/OIDC/签名密钥/CORS 启动门禁，远程 Edge/OpenShell 强制 TLS。

## 显式 TODO（不隐藏风险）

| 项 | 风险等级 | 计划 |
| --- | --- | --- |
| 部署回执独立验证/远程证明 | 中 | 当前 Edge publish_policy 明确不支持且永不转 effective；Phase 4 评估 |
| Edge mTLS/设备证书自动轮换 | 中 | 当前已强制远程 HTTPS + Bearer 即时吊销 + Ed25519；后续增加 mTLS |
| Connector OS 级强隔离 | 中 | 当前为官方名单+子进程超时/输出限额；后续引入低权限用户/容器或 seccomp |
| 本地桌面同 UID 自批 | 高（产品边界） | 当前 profile=`desktop-same-uid`；`managed-linux` 未实现。详见 [agentshield-capability-profiles-v1.md](agentshield-capability-profiles-v1.md) |
| 浏览器 DNS rebinding 真机链 | 中 | Host 允许列表已落地；S2b 真机条件未测 |

本地单文件门禁的主体/档位/读回与强制分离，以能力 profile 文档为准，不以本表企业控制面条目替代。

<a id="local-product-threats"></a>
## 本地产品威胁（AgentShield / desktop-same-uid）— DEV18-B / M-T1

本表补齐控制面矩阵未覆盖的本地 daemon / CLI / 静态站边界。交付 profile 以 [agentshield-capability-profiles-v1.md](agentshield-capability-profiles-v1.md) 为准；下列“验证”仅指仓库内已有聚焦测试或工程控制，**不等于**真机对抗，也**不**表示 `managed-linux` 已验收。

| # | 威胁 / 攻击者 | 资产与入口 | 主要控制（已实现或声明） | 验证 / 证据 | 残余 |
| --- | --- | --- | --- | --- | --- |
| L1 | 远程网页经 DNS rebinding / 恶意 Origin 调 loopback 管理 API | 管理会话、批准、导出 | Host 允许列表；ui-config 无 secret；非法 Origin / `Sec-Fetch-Site: cross-site` 写拒绝；一次性配对码换管理会话 | `internal/server/authz_test.go`（DEV02-A） | **S2b 真机链未测** |
| L2 | 同 UID Agent 读 `<state>/token` 或 CLI 自批 | grant / 模式 / 卸载 | 决策 token ≠ 管理；HTTP 管理需配对会话；高影响 approve 绑定 challenge（digest/scope/revision/nonce/单次） | DEV02-A/B 测试；能力 profile §2 | **同 UID 下 CLI `--approve-as` 仍可写 Store**；非人类证明 |
| L3 | 同机其他 UID 读状态目录 | token、回执、grant | 状态目录 0700、token 0600 | 声明于能力 profile；**跨用户 ACL 未实测** | 非 managed-linux |
| L4 | 恶意 Skill / 配置内容注入扫描或终端 | 准入结论、导出、终端渲染 | 内容不可信；特殊文件/有界读/枚举预算；打开后 Stat+SameFile；终端 ESC/CSI/OSC 转义；导出脱敏 | DEV05-A/B/C、DEV15-B/C | 同 UID 扫描→执行 TOCTOU 窗口未宣称清零 |
| L5 | 篡改或伪造 Skill 发行物 / 下载替换 | 将执行的二进制与清单 | 发行根验签；content_hash；私有 staging 后再哈希；下载 opt-in + HTTPS + sha256/字节 pin | DEV04-A—E | 真实 GitHub Release 端到端、执行前同 UID 改写 OS 隔离未宣称 |
| L6 | 并发写者 / 崩溃半写破坏 grant 或回执链 | Store、receipt NDJSON | Link 排他单写者；grant CAS；hold；链尾半行拒绝；`CommitGrant` 失败不伪成功 | DEV03-A—D | 崩溃级跨文件原子性未宣称 |
| L7 | 把 OpenShell / 配置读回当作网络已强制 | 对外能力承诺、L3 表述 | 能力档位分离；`verify` 最高 `readback_verified`；矩阵零行 `supported`；跳过≠通过 | 能力 profile §3；规格 §3.8.1 | DNS/IP/重定向/IPv6/失联/替代路径 **enforcement_verified** 缺证 |
| L8 | 会话容量耗尽后 LRU 清污点再“干净”决策 | session 污点、decide | MaxSessions；满则拒绝；禁止 LRU 清污点；仅无污点/无 trifecta 可空闲过期 | DEV16-A/E | 持久化过期状态/跨进程未宣称 |
| L9 | 投影缓存坏文件伪装空集成功 | assets/permissions/findings/export | revision/health；坏文件有先验→stale，无先验→500 | DEV16-B | 1万/10万归档观察未做（骨架见 DEV16-D） |
| L10 | 导出/回执扫盘 OOM 或截断隐瞒 | 导出 JSON、磁盘预算 | ReadLimited；Budget/`incomplete`；perfbaseline 观察骨架 | DEV16-C/D | 1万/10万人工归档与空闲无污点过期未宣称 |
| L11 | 供应链：CI 可变 Action / 未锁镜像 / CDN Mermaid / 未校验 OpenShell 下载 | 构建与静态站 | Actions 完整 SHA；Dockerfile `@sha256`；Mermaid 自托管；OpenShell URL env+摘要+允许域 | DEV17-A—D 检查脚本 | 真实网关下载实测、整包 SBOM 消费未宣称 |
| L12 | 安装备份损坏或卸载误伤用户配置 | 宿主 Agent 配置 | 首备不可覆盖；外科卸载；坏 JSON/symlink fail-closed；pending→签名回执 | DEV07-A—D | 三端真实 GUI 旅程未做 |

### 主体对照（摘要）

| 主体 | 相对 L1–L12 |
| --- | --- |
| 远程网页 / 网络客户端 | L1 为主；不得假设已关闭 rebinding |
| 同机其他 UID | L3 |
| 同 UID Agent / CLI | L2、L6、L8 |
| 恶意 Skill / 配置 | L4、L5 |
| 受损 Connector / 适配器 | 决策路径 only；见控制面 T2/T12 |
| 可信管理员（本机） | 仍受 L7 表述门禁；批准挑战见 L2 |
| 控制面 / 发布 key | 见上表 T*；本地不持有生产密钥 |

更新本表时须同步能力 profile 与发布 checklist 的诚实措辞；不得把“文档已写”记成“威胁已消除”。
