# OPT-05 B：持久恢复基础组件验证

日期：2026-10-07。对应 [ADR-055](../adr/0055-durable-openshell-operation-recovery.md)。

## 当前交付边界

已实现独立加密快照、迁移 0030 私有台账、带 epoch 的状态迁移、事务审计和独立密钥文件加载器。**尚未接入在线 OpenShell apply/rollback，不构成真实后端重启恢复验收。** OPT-05 保持 implementing。已有原后端绑定修复见 [A 批验证](optimization-opt05-backend-validation-20261007.md)。

台账在独立短事务中验证已提交部署的身份，保存密文及来源元数据；同一 deployment 最多一个操作。prepared/applying/applied/rollback_pending/rolled_back/unknown 显式区分，unknown 不允许自动再次 apply。每次状态变化与审计同事务；状态与 epoch 双条件防止旧执行者覆盖新状态。读取限制 tenant/deployment/operation，并验证关联数据和密文；它不是管理权限或目标授权的替代品。

密钥通过 `SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE` 指向的私有普通文件供应。加载器不生成备用密钥，不使用签名密钥；缺失密钥或文件验证失败直接拒绝。格式、权限、轮换及保留旧密钥要求见 ADR。该环境变量尚未成为在线部署入口的必填配置。

## 已执行验证

| 检查 | 结果与含义 |
| --- | --- |
| 加密封装 | 31 项通过；逐字段来源绑定、篡改、轮换与格式/体积边界 |
| 台账主体 | 11 项通过；精确快照、新 registry 读取、258 条保留、并发 CAS、审计故障回滚、unknown 禁重试、来源隔离、外键保留与状态摘要约束 |
| 增补身份与唯一性 | 5 项通过；environment/binding/target 不一致、跨租户 prepare、同部署第二操作拒绝且无额外审计 |
| SQLite 迁移 | 新 0030 与原 0029 两项通过；空库升级/回退/再升级，非空恢复历史禁止降级 |
| PostgreSQL harness | 27 项通过；包含原部署/调度门禁、真正并发连接的 CAS、状态链、精确审计数与非空 0030 降级保护 |
| 密钥文件 | 16 项通过；有效文件、环境引用、权限、符号链接、FIFO、缺失/畸形/超限、读取中变化拒绝 |
| 控制面全量 | `SIQ_TEST_NATIVE_BWRAP=1 pytest app/tests -o addopts='' -q -ra`：2,426 通过、1 条既有 wire sample 条件跳过，146.50 秒；后补的 5 项身份和 16 项密钥测试是单独通过记录，未冒充同一次全量结果 |
| 静态检查 | API 范围 Ruff、仓库配置下两份 PostgreSQL 脚本 Ruff、`git diff --check` 通过 |

SQLite 并发使用线程及独立数据库会话；PostgreSQL 使用独立数据库连接。本批尚未做 CLI 外部写入的进程终止试验，不把“新 registry 读取”称为业务进程崩溃恢复。

PostgreSQL 使用 harness 自建并清理的临时容器；原业务数据没有迁移。组件测试的 SQLite 自动建表只用于临时测试库；生产继续通过 Alembic。

本机日志位于 `var/optimization-20261007/opt05-{sealed-snapshot,journal-focused,journal-identity,journal-migration,journal-postgres,recovery-keys}.log`，PostgreSQL 明细在 `opt05-journal-postgres-001/`。这些原始日志不提交。新增脚本是该临时容器 harness 的内部 worker，拒绝缺少限定环境标识或非 loopback PostgreSQL 的运行环境。

全量日志为 `opt05-journal-control-all.log`。首次把外部脚本放到 API 工作目录运行 Ruff 时触发了该目录不同规则集下的既有格式告警，因此当次 `set -e` 没有启动全量测试；随后按各自配置目录检查通过，并启动了上表全量运行。未把未执行的测试当作通过。

## 接入前必须继续完成

1. 将目标作用域跨进程互斥接入在线入口；数据库状态 CAS 不能替代外部策略写入互斥。
2. 旧入口、单项/批量 reservation 的提交顺序统一，避免外部执行前恢复意图尚未提交。
3. apply 与 rollback 写入前后接入台账，保留未知结果和唯一恢复线索。
4. 每次回滚重新检查当前身份、活体授权、binding、网关及策略 revision/digest；不能由持久记录自行授权。
5. 验证提交故障、重启/不同 worker、重复回滚、超缓存容量及真实 OpenShell 回滚；行为验证与配置读回仍分开报告。

## B4 增量：跨进程目标锁组件

`target_mutex.py` 使用网关指纹和目标作为作用域，PostgreSQL session advisory lock 与 SQLite 开发磁盘库 POSIX 文件锁均已实现。内存库及 URI 别名形式拒绝，锁文件私有、拒绝符号/多硬链接，不在释放后删除共享 inode。PostgreSQL 锁获取或释放结果不确定时使连接失效，防止带锁会话回到池。

本机定向测试 10 项通过：实际子进程争锁与释放、不同目标不互斥、异常释放、危险锁文件及不支持数据库形式拒绝、四类 PostgreSQL 连接故障注入。重新执行临时 PostgreSQL harness **29 项通过**，新增实际独立子进程竞争和释放验证。日志为 `opt05-target-mutex.log`、`opt05-mutex-postgres.log`，明细 `opt05-mutex-postgres-001/`。组件尚未接入在线 CLI 操作；它不能阻止不遵守协议的外部管理员，也不提供后端原子 CAS。
