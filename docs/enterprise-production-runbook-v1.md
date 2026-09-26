# 企业生产 Runbook 模板 v1（DEV18-C）

- 日期：2026-09-06（2026-09-26 增补第 9–10 节：故障排查顺序与发行包前置条件，均为 template）
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
