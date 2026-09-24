# E157 业务运行结果的持久保存与独立读取

状态：源码实现及定向验收完成，**不是生产放行**；总体目标 active。承接 [E156](ux-business-result-access-e156-validation-20260923.md) 和 [本批规格](business-result-retention-e157-spec.md)。

## 已实现

研究 API 新增 `business_run_results` 与追加迁移 022。结果按 tenant/user/profile/session/run 的完整归属定位，只保存 siq_analysis → OpenShell → confidential_local 且主运行、子任务均确认终态的回复。源 scope/授权快照、业务状态、内容和摘要一起保存；结果与不含正文的审计同事务。同键同内容重试幂等，不同内容拒绝覆盖。

保存已接到运行清理路径。非流式原先未把最终回复写入运行缓冲，本批补齐，回归断言保存的是最终规范化正文。超过 1 MiB UTF-8 的正文不截断保存为完整回复，只保留 too_large 元数据；空内容独立显示 empty。保存失败只输出固定错误类别，不回滚已完成的清理、不伪造保存成功。

E156 两条 HTTP 路由保持原 v1 合同。在准确原运行不在内存时查已提交结果；同会话新运行不会替代旧正文。历史源快照按签发时刻复验，当前账户与精确 scope grant 在读前后重新查询，记录也再次核对。仍存在但失权的准确内存运行不会通过历史回退绕过权限。历史快照过期本身不会冒充当前授权，也不会阻止持有效当前授权的合法历史读取。

结果仍是 `generated_reply`，`publication_status=not_attested`。没有把生成回复当作正式发布报告；记录摘要检查不一致，不构成抵御数据库管理员重写内容与摘要的签名证明。

## 验证及真实失败

| 范围 | 结果与含义 |
| --- | --- |
| 最终研究 API 组合回归 | **260 passed，1 deselected**；包含新增持久结果 35 项、原 HTTP/授权/导出/运行流程回归。排除项的真实失败保留在下面，不称全绿 |
| 新增历史访问 | 真实 FastAPI + 隔离 SQLite；清空缓冲、换运行、连接池重建、独立新 Python 进程读取、跨租户/用户、撤权、摘要/正文/来源篡改、读中删除/替换、空/超限、冲突拒绝 |
| 独立 PostgreSQL | 022 重复执行；实际服务 8 路并发首次保存只有 1 行及 1 条审计；冲突拒绝、内容读取、撤权及审计插入失败整笔回滚通过 |
| 运行清理接入 | 调用实际清理函数与真实存储，运行结束传输为替身；未确认清理不保存，清理确认后保存，保存失败不撤销清理。不是沙箱实测 |
| 安全项目合同 | **275 passed**，三份业务结果 v1 合同未变，无新增前端功能 |
| 静态检查 | 本批新增/修改 Python 文件 Ruff 和两仓 diff whitespace 检查通过 |

首次完整组合运行是 **257 passed、1 failed**。失败为既有 `test_full_chain_fresh_and_008_snapshot_upgrade_on_postgres`：在独立空 PostgreSQL 回放到历史 015，因 `user_artifacts` 不存在而报 UndefinedTable。001–014 没有创建该表。这不是 022 的失败，也不能用 022 定向测试通过替代整链验收。

保留 `var/flagship/ux-e157/api-initial-full.log`；最终回归显式排除此已定位项，未删除/跳过修改原测试、未修改历史 SQL/checksum、未偷偷给空库补表。安装基线修复已写入 [任务书](user-experience-onboarding-taskbook-20260923.md)。完成前，新安装迁移和生产门禁均不放行。独立 PostgreSQL 容器已停止并删除；没有挂载真实业务数据或应用真实业务库迁移。

主要命令（研究仓 `apps/api`）：

```bash
PYTHONPATH=../..:. .venv/bin/python -m pytest \
  tests/test_business_run_result_store.py tests/test_business_run_results.py \
  tests/test_migration_governance.py tests/test_agent_runtime_read_access.py \
  tests/test_siq_security_export.py tests/test_governed_analysis_entry.py \
  tests/test_qwen38_request_selector.py tests/test_agent_runtime_history.py \
  tests/test_qwen38_request_finalizer.py tests/test_qwen38_request_api.py \
  tests/test_agent_runtime_active_runs.py \
  -k 'not test_full_chain_fresh_and_008_snapshot_upgrade_on_postgres' -q
```

测试 PostgreSQL 地址仅传入临时测试进程的 `SIQ_TEST_POSTGRES_URL`；常规无该环境的执行会跳过 PostgreSQL 用例，应核对跳过项。既有 datetime 弃用提示未被隐藏。新增两个 import 排序问题已修复后重新检查。未改 Go/Web，本批不重复构建它们。

## 仍需完成与回退

1. 安装初始数据库基线与历史迁移前置关系修复，重新跑完整空库及旧版本升级。
2. 终态到数据库提交之间崩溃的恢复。当前只保证已成功提交结果的跨进程读取；不能保证所有已向客户端发送 done 的任务都已持久保存。
3. 正式发布产物的不可变归属、独立发布核验、准确版本读取；控制台业务身份连接、可信运行映射及报告导航。
4. 实际业务 HTTP → Hermes/OpenShell → 发布 → 页面查看验收；生产 IAM、安装发行仍单独验收。

源码候选尚未部署，没有替换已安装二进制、修改业务模型/Profile 或重启业务 API。回退本批存储/读取及清理钩子代码即可；若未来已应用迁移，保留结果表和审计，不删历史数据。未提交/推送/发布，SEC-F01–F10 按用户指定继续列后续。

[本批证据](../evidence/flagship-optimization-20260921/ux-business-result-retention-e157.json) 绑定两个仓库的相关源码、日志、规格及候选。
