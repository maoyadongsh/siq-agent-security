# 企业生产 Runbook 模板 v1（DEV18-C）

- 日期：2026-09-06
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

## 明确不在本 runbook 宣称通过的项

- 真实 IdP 兼容矩阵
- 真实 PostgreSQL 备份恢复 RPO/RTO
- OpenShell `L3_enforce` / `enforcement_verified`
- `managed-linux` 同机隔离
- 浏览器 DNS rebinding 真机链（S2b）
- 独立托管环境安全扫描产物
