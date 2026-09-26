# 企业生产 Runbook 模板 v1（DEV18-C）

- 日期：2026-09-06（2026-09-26 增补第 9–10 节：故障排查顺序与发行包前置条件，均为 template；同日增补 §9.1 周期发现确认与导出截断排查）
- 计划：[DEV18](development-plan-20260906-022735.md#dev18)
- 状态：**模板 / 缺口清单**。下列步骤是交付所需操作面，**不是**已在客户环境执行并通过的证明。
- 集成边界：只经本仓版本化合同对接 SIQ Platform/Gateway；**禁止**为绕过缺陷改兄弟仓代码或数据库。

每节状态：`template`（仅文档）、`partial`（仓库有工程控制但缺生产证据）、`blocked`（缺环境/权限无法验证）。

## 1. 受控入口与 TLS

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| 终止 TLS 于受信入口（反代/网关） | template | 企业 `nginx` 已有安全头模板（DEV17-B）；HTTP 开发拓扑不得套 HSTS |
| 仅 HTTPS 暴露控制面 API | template | 生产 CORS 白名单；通配拒绝（config 门禁） |
| 健康检查与只读探针路径 | partial | 以部署清单为准 |

## 2. OIDC / 身份

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| 配置 `SIQ_AS_OIDC_JWKS_URL` / `SIQ_AS_OIDC_ISSUER` / `SIQ_AS_JWT_AUDIENCE` | partial | 生产启动强制；资源 token 仅 access/user/service（DEV08） |
| 与真实 IdP 联调（错 aud/iss/轮换） | blocked | **缺证**；仓库仅有 mock JWKS 矩阵（DEV08-C） |
| 刷新令牌不得访问资源 API | partial | 代码拒绝 `type=refresh`；IdP 实际 claim 合同未核 |

## 3. Secret 注入

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| `SIQ_AS_TASK_SIGNING_KEY_SEED` 由 Secret Manager 注入 | partial | 生产缺 seed 拒启 |
| 发布种子 `SIQ_AGENT_SECURITY_RELEASE_SEED` 不入库 | partial | gitignore + 清单禁止打印 |
| 轮换与吊销演练 | blocked | 未做生产演练 |

## 4. PostgreSQL

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| 生产仅 PostgreSQL URL | partial | SQLite 生产拒启 |
| 迁移 / 备份 / 恢复演练 | blocked | **缺真实 PG 证据**；不得宣称已验收 |
| 多副本 Outbox SKIP LOCKED | blocked | DEV12 仅仓库侧 CAS；真实 PG 未测 |

## 5. Edge 设备注册与吊销

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| 注册码 TTL / 限速 / 冲突 409 | partial | DEV11 仓库测试 |
| 吊销即时拒绝后续上传 | partial | 单元/集成有；生产设备清单未对账 |
| 在役信任指纹与生产撤销 | blocked | DEV01 仓库侧清单有；在役比对未做 |

## 6. 任务与 Worker

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| worker 领取 / 退避 / 死信 | partial | DEV12 仓库侧 |
| uploaded 未回执恢复 | partial | DEV10 路径；强杀全矩阵未宣称 |
| 监控：积压、验签失败、JWKS 刷新失败 | template | 指标名见 DEV16 计划；未接生产报警 |

## 7. 证书与密钥轮换

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| TLS 证书轮换 | template | 入口侧运维 |
| JWKS 轮换信任窗口 = TTL | partial | mock 时钟测过；真实 IdP 未测 |
| 任务签名密钥轮换 | blocked | 需运维窗口与双读者 |

## 8. 事故处置

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| 吊销 Edge / 撤销管理会话 | template | 本地 daemon 另见能力 profile |
| 导出脱敏证据包 | partial | DEV15-B |
| 独立安全扫描与对抗复核 | blocked | 深扫未启动，缺口保留 |

## 9. 常见故障排查顺序（template）

排查约束：只使用下列仓库已有诊断入口；**不得**打印环境变量、凭据、设备私钥或上传未脱敏日志；删除数据库、重置身份、重复注册**不是**默认修复手段，须先按本节顺序定位。

| 症状 | 排查顺序 |
| --- | --- |
| 前端打不开 | 先确认 Control API `/health` 与 `/api/v1/health` 返回正常；再核对接入拓扑中网关路由与 HTTPS 入口；最后检查浏览器端配置（企业 Web 使用独立的 Control API 配置，不与个人管理端入口混用） |
| 环境 / 设备为空 | `GET /api/v1/environments` 与 `GET /api/v1/environments/{id}/onboarding` 查看环境注册与汇总状态；网络可达不等于设备已注册；确认 Edge `register` 已完成且注册码未过期 |
| 注册后无心跳 | 确认 Edge `serve`/`heartbeat` 正在运行；控制面侧核对 `/edge/v1/heartbeat` 是否收到记录；确认设备凭据未被吊销（吊销即时生效，每次请求在线校验） |
| 心跳正常但无发现结果 | 核对已启用 Connector 类型与采集范围是否覆盖目标资产；确认 `/edge/v1/initial-scan` 是否成功返回；采集结果先成为候选，需负责人确认后才进入资产清单，未确认前清单为空属预期 |
| 采集失败或能力不匹配 | 先核对已有失败记录和能力声明，必要时在获准设备使用 `inspect-host`；对照[兼容说明](compatibility.md)核对支持范围。`run-once` 会实际执行采集，并非仅查询状态；只有取得目标与范围授权后才使用明确的 `--connector`、`--scope`，不得省略范围而扫描默认目录。输出不直接外传，不通过放宽范围绕过能力限制 |
| 策略未生效 | 依次核对部署预览与提交记录、后端策略读回与漂移检测结果；企业 OpenShell CLI 后端当前只支持 `block` 部署，`audit_only` / `warn` 不是已生效模式；读回正常不等于真实动作已受阻，需正负用例核验 |
| 升级与恢复 | 升级前先备份并核对数据库迁移版本与恢复路径。注册响应丢失且有原待恢复材料时核对 `recover-registration`；凭据轮换走 `rotate-credential` 的既有前置条件和恢复流程，两者都会涉及状态变化，不作为通用只读排障。已吊销或材料缺失时停止并交管理员处理，不重置身份、不重复注册；恢复后核对审计记录完整 |

### 9.1 周期发现确认 `confirm-discovery-schedule --discover` 排查

排查约束同 §9：只使用只读诊断入口，**不得**打印设备私钥、种子、凭据、令牌或未脱敏日志；发现结果只是"本机是否有活干"的事实，**不是**授权，任何排查都不产生确认。

| 症状 | 排查顺序 |
| --- | --- |
| `--discover` 报 **0 个待确认计划** | 这是诚实结果，不是周期接入成功：本次未创建请求、周期发现未启用，本机没有等待确认的计划。纯只读 `--discover` 查询以成功退出；若命令还带 `--interactive` 或 `--confirm-intent-sha256` 明确要求确认，则以失败退出，因为实际没有计划被确认。依次核对：组织控制台是否已为该**设备**（不是同环境的其他设备）创建周期计划；计划状态是否为 `pending_confirmation`（`active`/`paused`/`revoked` 都不进入待办列表）；设备的租户/环境归属是否与创建时一致（不一致时该计划对本机不可见）。**不得**把 0 项当成"周期接入已完成"，也不得改用其他设备或环境的计划顶替 |
| `--discover` 报**多个待确认计划** | 端点有意不自动挑选：命令只打印有界候选（`schedule_id` / `intent_sha256` / 状态 / 起止时间）并以失败退出。由人对照组织控制台确定应确认哪一个，再用精确 `--schedule-id <ID>` 重试。**不得**让脚本按顺序取第一个、也不得为"简化"而要求实现自动选择 |
| `--discover` 报**完整性失败**（`integrity_failed`） | 命令只输出受控 `schedule_id` 与固定原因，这是失败关闭而非"没有待办"。把列出的 schedule_id 交组织控制台核对：记录是否被改绑、投影字段（`schedule_id`/`intent_digest`/起止时间/间隔/预算）与持久行是否一致、原安装计划摘要是否仍匹配。在核对清楚前**不要**对该 ID 执行确认；完整性失败的行不会被投影内容，也不会被静默跳过。**不得**通过删除记录或放宽校验来"修复" |
| 已有确认请求但结果未知 | 保留状态目录中的 `discovery-schedule-pending.json` 与既有回执，**不要**删除或覆盖。按 [周期计划合同](packages/contracts/enterprise-discovery-schedule.v1.md)"Linux CLI 增量"用 `--resume` 只重发**原请求**（不重新签名、不用当前时间续期）；`confirmation_result_unknown` 表示需保留日志后重试原请求，`confirmation_receipt_not_saved` 表示需保留日志与原回执并先核对。恢复日志可读不代表可发送或已授权，服务端仍按截止时间判定 |
| 服务起不来且报周期未确认 | `serve`/`install-user-service` 持任务锁复验周期日志与回执：只有成功回执（含残缺文件或链接）会被视为未完成恢复并拒绝启动。先补齐原确认回执，或按管理员流程处理；**不得**删除回执或日志以让服务启动，也不得自动确认或改写材料 |
| 导出结果疑似不完整（`X-SIQ-Export-Truncated`） | 见 [OCSF 导出合同](packages/contracts/enterprise-ocsf-export.v1.md)。响应头为 `1` 只表示"在本次 `class` + `since` + 租户条件下还有更多匹配记录"，**不是**导出失败、不是归档、也不代表这些记录已发布或已核验；需要更多数据时收窄 `since` 或提高 `limit`（≤2000）后重新导出。头为 `0` 只表示本次未看到更多匹配记录，不代表数据保留范围。审计 `summary.count` 是实际返回条数，用它核对本次导出规模 |

卸载语义：**停止采集**（移除 Connector/Edge 采集组件）与**撤销运行保护**（移除宿主适配器/执行后端约束）是两件事，分别确认；卸载不自动删除审计记录，也不自动放宽已部署策略。

## 10. 发行包与部署前置条件（template）

- 企业候选包由 `scripts/release/enterprise_candidate.py` 产出，为 unsigned candidate 与待签材料；**不得**交给生产安装器或替代正式包部署。
- 正式企业包须在受控环境完成签发，经 `enterprise_finalize.py` 组包；按工具要求使用独立可信且固定摘要的 verifier，并用 `edge-agent verify-enterprise-release` 的 `--bundle` 模式同时核验签名信封与实际制品。仅验证信封不证明目录内二进制完整，验签也不替代原生安装验收。
- 个人客户端签名包用 `scripts/release/verify.py --release-dir --version --source-sha` 验证（源码身份需显式传入核对）；发布后用 `readback.py` 做只读公开回读。
- 签名发行材料（签名、清单、源码固定提交）不齐时，升级/恢复流程视为缺前置条件，不使用开发版或未签名候选顶替；版本号、制品摘要与下载地址以正式发行后的回读记录为准，本节不预填。

## 明确不在本 runbook 宣称通过的项

- 真实 IdP 兼容矩阵
- 真实 PostgreSQL 备份恢复 RPO/RTO
- OpenShell `L3_enforce` / `enforcement_verified`
- `managed-linux` 同机隔离
- 浏览器 DNS rebinding 真机链（S2b）
- 独立托管环境安全扫描产物
