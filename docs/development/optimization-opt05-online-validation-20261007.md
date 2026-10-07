# OPT-05：持久 OpenShell 回滚与真实链路验证

日期：2026-10-07。分支 `codex/security-optimization-20261007`。

## 结果及范围

控制面已将原后端来源、加密快照、持久状态台账和跨进程目标锁接入真实 apply/rollback。新的 API 进程可以从既有数据库和独立密钥环恢复精确回滚材料；重复回滚不会再次写后端。可确认的已提交操作与未知结果分开处理，未知结果不自动重放。

DGX Spark 上的 **OpenShell 原生联验通过 14 项检查**：实际浏览器提交并刷新读回、允许网络请求、撤销后明确 HTTP 403、新的 API 进程独立回滚、精确恢复原策略及同一请求重新成功。私有临时网关、沙箱和 Docker 网络均已清理，原配置与 TLS 文件保持不变。可复核摘要与源码哈希见 [原生证据](evidence/optimization-20261007/openshell-durable-recovery-native.json)。

这是使用本机既有 OpenShell 0.0.83 二进制、缓存 ARM64 镜像和专用模板的隔离验收。API 为独立开发身份，浏览器使用测试层模拟刷新会话；目标授权文件只覆盖本次创建的沙箱。没有测试客户生产 IAM，也没有挂载业务目录或调用模型。配置读回仍标记 `readback_verified`；独立实际网络探针的通过不自动将所有部署升级为行为验证。

## 实现

1. 迁移 0029 保存原部署后端；配置切换、缺失来源或绑定冲突时拒绝回滚。
2. 迁移 0030 保存每个 deployment 唯一的 operation、AEAD 绑定的完整快照密文、状态、epoch、应用/恢复 revision 与摘要；禁止非空恢复历史被降级删除。密钥独立供应，不入库、不复用签名密钥。
3. 原部署入口与已有单项/批量 reservation 均在外部写入前提交带审计的占位；CLI 在目标锁中提交 prepared/applying，写入并读回后提交 applied。回滚使用 rollback_pending/rolled_back。
4. 每次新回滚重新检查身份、活体授权链、绑定来源、网关及后端 revision/digest。没有持久操作的历史记录不回退到进程缓存，客户端不能提交快照修复来源。
5. 状态与 epoch 条件更新和审计同事务；未知写入结果保留 applying/rollback_pending/unknown，不猜测成功、不自动重试。
6. `GET /api/v1/deployments/{id}/recovery` 按新 v1 合同返回经认证的历史状态摘要，不返回快照、密文或密钥。材料可用不代表当前获准执行。先定位 tenant 对象，再检查 `policy:read`，响应 `no-store`。
7. 外部应用及 journal 提交成功、API 最后事务失败时，显式管理回滚可从 journal 重建绑定。外部回滚及 journal 已提交、API 最后审计失败时，再次请求只确认历史结果并补齐控制面事务，不再次 policy set。

目标互斥采用同数据库的登记目标 ID。调用指纹含 HOME/XDG 等进程配置，不能用它划分互斥域；不同网关的同名目标因此保守串行。来源认证仍精确绑定原指纹。锁不阻止外部管理员，不识别任意后端别名，也不替代后端原子 CAS。

## 验证证据

| 层次 | 证据 |
| --- | --- |
| 后端来源、迁移与兼容 | [A 批验证](optimization-opt05-backend-validation-20261007.md) |
| 加密、台账、密钥和锁 | [B 批组件验证](optimization-opt05-journal-validation-20261007.md) |
| CLI 与 API 定向集 | 332 通过，包括公共恢复合同校验、权限隔离和未确认结果拒绝 |
| 恢复故障 API | 缺失密钥、缺少/篡改材料、回滚末尾审计失败等 5 项通过；无持久事实却宣称成功的适配器另有拒绝回归 |
| 真正独立进程 | 3 项通过；正常进程接续、应用写后 `os._exit`、回滚写后 `os._exit`；后续请求不增加外部写入 |
| 容量与锁范围 | 17 项通过；完成 257 个后续 no-op 操作后，第一条实际应用仍能精确回滚；上下文变化不绕过同目标锁 |
| 数据库提交故障 | 2 项通过；prepared 提交失败时外部零写，applied 提交失败时保留未知结果，不丢失前置材料 |
| 控制面最终全量 | `SIQ_TEST_NATIVE_BWRAP=1 pytest app/tests -o addopts='' -q -ra`：**2,475 通过、1 条 wire sample 条件跳过**，177.86 秒；日志 `opt05-online-control-final.log` |
| PostgreSQL | 最新隔离 harness **31 项检查通过**，覆盖在线接入、独立进程锁、旧守卫直接复核及非空 0030 降级保护 |
| 原生实际效果 | 最终可复现 harness 14 项通过；真实策略写入、读回及网络行为、新 API 进程回滚和资源清理 |

旧路由负向对照加载 `d302b0b1` 的 `policies.py`，给适配器注入“成功但没有持久操作”的回执：旧路径将其记成 effective，当前路径拒绝。该对照是内部持久事实门禁验证，不表述成远程攻击已经成功。

原始日志位于 `var/optimization-20261007/`：`opt05-online-focused-004.log`、`opt05-online-recovery-api.log`、`opt05-process-recovery.log`、`opt05-capacity-and-context-lock.log`、`opt05-database-fault.log`、`opt05-online-negative.log`、`opt05-online-postgres-003/`、`opt05-reproducible-native-001/`。不提交原始运行目录、密钥、数据库或完整日志。

首次原生尝试发现历史验证网关未监听；隔离引导首次缺少新网关自身的 JWT 密钥，随后显式生成独立材料。浏览器 worker 还遗漏了 OPT-02 的测试会话适配，已补齐测试层刷新，不改变生产身份边界。所有失败尝试与清理记录保留，未合并到通过分母。旧单测中伪造成功回执的两处夹具已改为运行完整受控 CLI 链路。

## 复现入口

```bash
# 需要本机已安装依赖、原生 CLI/网关及已缓存沙箱镜像；不自动拉镜像。
python3 scripts/enterprise-experience/owned-openshell-recovery-check.py \
  var/optimization-20261007/NEW_NATIVE_OUTPUT \
  --gateway-template /home/maoyd/siq-research-engine/var/openshell/gateway/siq-openshell-scope-validation/gateway.toml \
  --gateway-binary /home/maoyd/siq-research-engine/var/openshell/toolchains/v0.0.83/bin/openshell-gateway \
  --web apps/web/dist

apps/control-api/.venv/bin/python scripts/enterprise-experience/deployment-postgres-check.py \
  var/optimization-20261007/NEW_POSTGRES_OUTPUT
```

原生引导拒绝复用已有输出目录或占用的 17771/17772 端口，复制配置时创建独立数据库、namespace、Docker 网络和 JWT 材料，关闭宿主目录挂载，保留 mTLS，限制网关地址空间为 2 GiB。原始模板和 TLS 仅引用/读验。验收只清理本次拥有的资源，不启动或改写原业务网关。没有宣称断电恢复、生产多副本吞吐或未经实测的 OpenShell 版本兼容性。
