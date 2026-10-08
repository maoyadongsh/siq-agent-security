# OPT-09：认证行为验证接口与真实 OpenShell 接线

日期：2026-10-08。状态：本批接口接线完成；OPT-09 仍为 implementing。本报告不替代完整优化方案或最终产品验收。

## 本批结论

企业接口已能在验证请求身份、部署批准链与操作员目标归属后，使用批准模板执行真实 OpenShell 三臂探测，并将观测及审计持久化。相同请求重复提交只返回历史记录；历史查询不启动探针、不读取网关，也不要求当前恢复密钥仍可用。

真实链路使用专用临时网关、实际 CLI、固定镜像内的受保护 ELF、真实 CONNECT 代理与回显接收端。API 经进程内 ASGI 调用，RS256 签名实际校验，发行者密钥与审批身份为合成测试材料，数据库为独立开发 SQLite。它证明了认证 API 与真实执行通道的接线，不代表生产身份提供方、反向代理入口或生产 PostgreSQL 的同次端到端验收。PostgreSQL 迁移与事务另有独立实测。

公开、可复核的本批材料：[认证 API 证据](evidence/optimization-20261007/enterprise-behavior-api.json)。其中包含挑战、完整观测、API 投影、父操作与审计核对、各层检查及候选文件摘要；不含令牌、签名私钥或恢复密钥。

## 接口与安全边界

| 接口 | 权限与行为 |
| --- | --- |
| POST `/api/v1/deployments/{id}/behavior-verifications` | 要求 `policy:manage` 与 `policy:read`；请求只含版本、`verification_id`、`profile_id`；不允许指定租户、端点、程序路径、nonce 或上传观测 |
| GET 同一路径 | 要求 `policy:read`；默认20条、上限100条；响应头明确是否截断 |
| GET 同一路径 `/{verification_id}` | 按租户及部署定位单条历史；不执行外部动作 |

对象先在已验证租户范围内定位，再判权限；跨租户或不存在均返回404，已存在但权限不足返回403。响应使用 `Cache-Control: no-store`。

主动采集每臂重新核验原请求身份、令牌时效、租户状态、enforce 环境、有效部署、未撤销的运行绑定、批准人和策略选择器、网关身份与操作员目标授权。网络探测在持久领取提交之后执行，不占用数据库写事务。最终接受事务再次检查授权和已验证的令牌截止时间；不在事务内访问 JWKS 或发送探针。

异常导致 unknown 或保留未确认的 running，不提升验证等级。已采信的历史记录过期后仍保留 accepted，另以 `time_window=expired` 表达时效；`current_enforcement_verified=false` 明确历史采信不能替代当前防护读回。原部署仍为 `readback_verified`。

JWT 数值日期的畸形类型、无穷值和超大值按无效令牌处理，避免解析异常进入未处理错误路径。可空完成时间也已适配，未完成／未知记录能够正常返回。

## 持久证据与迁移

新增迁移0032及配对约束，保存批准模板 `profile_id` 与 `profile_sha256`。旧记录两字段保持空值，不伪造新版本执行来源；新协调器将二者同时写入状态和审计。同ID绑定不同模板拒绝；相同ID不恢复 prepared、不重放探针。

从0031升级不会删除历史记录。有模板证据时拒绝降级0031；只有旧格式记录时允许移除新增空列。更早0031已有的非空行为证据降级保护继续有效。真实临时 PostgreSQL 验证了这些分支、部分字段更新被数据库约束拒绝、竞争消费只有一个胜者以及事务审计失败回滚。

## 验证结果

| 层次 | 本批结果 | 解释 |
| --- | --- | --- |
| 定向回归 | 167项通过 | 包含13项新API用例、9项新认证截止时间用例，以及协调器、台账、协议和既有身份验证回归；重叠批次不累加 |
| 临时 PostgreSQL | 43项通过 | Alembic干净升级／降级／回放、旧数据保留、模板字段约束、证据保留和真实行锁竞争；容器已删除 |
| 专用 OpenShell | 12项检查通过 | 真实父策略下发、持久协调、三轮差分、策略变更和清理 |
| 同次 API 检查 | 6项通过 | 匿名／开发头拒绝、跨租户／只读探针拒绝、RS256采集、重复／历史不重放、撤权拒绝和审计归属；与上一行有重叠，不相加为独立测评样本 |
| 独立复核 | 通过 | 唯一accepted记录／epoch2、数据库结果与公开观测逐项一致、模板摘要一致、父revision/digest一致、三条认证主体审计、协议和响应schema |
| 静态检查 | 通过 | 受影响实现及新测试／工具Ruff；原有网关脚本按Python3.12、`app`第一方导入配置检查；差异空白检查 |

实际三轮共12次探测：允许3/3完成200 CONNECT及原标识回显；拒绝3/3收到严格 `policy_denied`；主机前后对照6/6连通。接收端收到9条预期标识。随后显式授权原拒绝路径，新挑战成功并收到第10条标识；旧策略证据不再通过当前策略核验。

首轮API夹具使用了错误长度的部署请求键，随后发现夹具未建立租户行、审计查询误按verification ID当资源ID；三者均在夹具中修正。相应失败输出保留在本地，不计成功。最终167项及真实链路均使用修正后的候选。没有重跑未修改的前端、Go全量或模型业务。

## 可重现入口与候选身份

```bash
cd apps/control-api
.venv/bin/pytest -q \
  app/tests/test_behavior_identity_expiry.py \
  app/tests/test_deployment_behavior.py \
  app/tests/test_openshell_behavior_coordinator.py \
  app/tests/test_openshell_behavior_journal.py \
  app/tests/test_openshell_behavior_protocol.py \
  app/tests/test_oidc_jwt_verify.py app/tests/test_identity_jwt.py
```

仓库根目录的 `scripts/enterprise-experience/behavior-postgres-check.py NEW_OUTPUT_DIRECTORY` 只创建并回收自己的临时PostgreSQL，不接受现有业务数据库地址。真实链路复用 `owned-openshell-recovery-check.py` 的 `--behavior-api`，同时显式提供批准网关模板、网关二进制、镜像与ELF摘要；工具拒绝复用已有输出目录。

本次输出位于忽略目录：

- `var/optimization-20261007/opt09-api-postgres-001/`
- `var/optimization-20261007/opt09-owned-api-001/`
- `var/optimization-20261007/opt09-api-development-001/`（定向测试原始输出）

本批以 `ce6618a0` 为提交基线；实际执行候选以公开证据内 `source_sha256` 为准，不能只凭基线SHA声称全部代码已存在。未重新构建探针镜像；复用已核验镜像 `sha256:ea5c48273e4c11b782e788a734a32e3b8043f2d22e1c341e0f297482aae9eefc` 与ELF `0d8c89512c9f373725abf44595801fc2c16b3dd1f7a86f88e66ab50fdf49f7df`，同次独立保护检查再次核验其实际身份。

## 清理与剩余工作

临时网关、沙箱、网络、接收端和私有配置目录已清理；原网关模板及TLS文件摘要不变。数据库、合成观测和失败输出在忽略目录保留用于复核。未调用模型、未访问日常业务数据库、未更改现有业务服务；没有执行远端CI、发布或main合并。

后续仍需前端操作／结果呈现、部署验证等级与过期／策略漂移生命周期的完整接入及相应真实验收。当前实现没有通过永久缓存的accepted自动宣称持续防护，未覆盖IPv6、重定向或所有替代程序路径。OPT-09保持implementing，总体仍为9/16；其他OPT任务与最终候选业务／平台验收继续按原任务书执行。
