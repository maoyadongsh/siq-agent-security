# OPT-05 A：部署后端来源验证

日期：2026-10-07。分支：`codex/security-optimization-20261007`。

本批只完成原部署后端绑定；持久操作恢复仍在开发，不能据此宣称重启后已可回滚。设计见 [ADR-055](../adr/0055-durable-openshell-operation-recovery.md)。

## 修改与边界

迁移 0029 增加可空 `Deployment.execution_backend`；单项、批量及旧部署入口均从服务端准备结果保存来源，不接受客户端覆盖。回滚校验原来源、同租户/环境/目标的 binding 和当前后端配置，不一致时拒绝，且不产生回滚成功审计或状态。历史空值只允许原 binding 提供兼容来源，无可靠来源则拒绝。

回滚端点修正为先按租户定位对象，再检查管理权限，避免跨租户请求得到权限错误而不是 404。有来源数据后迁移降级拒绝丢弃；未猜测回填历史数据。

## 验证

| 检查 | 结果 |
| --- | --- |
| 后端来源、相关部署/回滚和 SQLite 迁移定向回归 | 53 通过 |
| 控制面全量 `SIQ_TEST_NATIVE_BWRAP=1 pytest app/tests -q -ra` | 退出 0；2,384 项中 2,383 通过、1 条既有浏览器 wire sample 条件跳过 |
| 隔离 PostgreSQL 部署 harness | 22 检查通过 |
| 旧路由负向对照 | 6 个后端切换用例均失败，复现错误状态/分支；非导入或编译错误 |
| 修改文件 Ruff 与 `git diff --check` | 通过 |

全量项目数由同一工作树 `pytest app/tests --collect-only -o addopts='' -q` 复核。PostgreSQL harness 实测后端变化拒绝、状态保持及 0029 降级保护；同时直接验证较早迁移 0020、0028 的保护，避免新守卫提前拒绝掩盖旧守卫测试。

原始本机日志（不提交）：`var/optimization-20261007/opt05-backend-{focused-003,control-all,collection,negative,postgres}.log`，PostgreSQL 输出 `opt05-backend-postgres-001/`。后端切换单测使用受控历史夹具，不是实际 OpenShell 回滚证明。本批没有操作业务数据库或发布生产配置。

## 后续门禁

加密持久快照、外部写入前意图提交、跨进程锁、重启恢复、重复/并发回滚、故障注入和真实 OpenShell 联验仍需完成。OPT-05 保持 `implementing`。
