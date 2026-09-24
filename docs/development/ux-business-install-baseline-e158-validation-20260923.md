# E158 空库迁移前置依赖修复

E157 发现的 `015` 缺少 `user_artifacts` 前置表问题已修复，原失败用例重新纳入并通过。研究 API 组合回归 **273 项全部通过，无跳过或排除**。本批为源码候选，未迁移真实业务库或部署在线服务，总目标 active。

## 用户和部署行为

用户继续使用原命令 `uv run --directory apps/api python scripts/run_migrations.py`。空库和固定 v008 快照都能升级到 022，无需先启动 API 或手工建表。重复运行不写第二条账本记录；并发安装由既有 PostgreSQL advisory lock 串行保护。

研究仓新增独立的 `migration_prerequisites` SQL/checksum 清单，唯一映射为 artifact 基线 → 历史 015。runner 连接前验证来源，锁内验证主账本和已有前置账本。015 尚未应用时，前置建表、015 原 SQL、两本账的写入在同一事务完成。该事务失败整体回滚，此前已完成的编号迁移仍保留，修正原因后可重跑原命令。

原 001–022 SQL/checksum 和 v008 快照均未改写；没有给旧账本插入版本。已有表不补列或填数据，原 015 的去重及唯一索引规则保持不变。已应用 015 的旧库允许没有前置账本，不虚构历史；它不是侦测管理员删除整本前置账的机制。

Git 不可变历史检查已覆盖前置清单。在线只读审计同时验证前置账本，来源/账本不一致拒绝；离线主账本 JSON 明确标为 `not_verified_offline_export`，不冒充已验证前置记录。所有新增数据库查询、DDL 仅发生在研究仓自己的迁移工具中，无跨仓数据库访问。

## 验证

- 迁移专项 **24 项**：原 12 项与新增 12 项。真实独立 PostgreSQL 的空库/v008 升级、重复执行、并发安装、SQLModel 列/可空性/长度/索引对齐、旧数据保留、原去重语义、旧部署无前置账本兼容均通过。
- 负向测试：SQL/checksum 同步修改仍被 Git 历史门禁拒绝；源篡改在数据库连接前拒绝；符号链接和未知映射拒绝；前置账本摘要、目标、未知版本、缺主链对应版本均阻断 runner 和只读审计。
- 事务验证：前置 SQL 因既有表缺列失败时不留新账本；前置 SQL 成功但原 015 唯一索引失败时，新增普通索引和前置账本同事务回滚，既有两行测试数据保留。
- 实际独立 CLI：原迁移命令重复执行、在线审计、离线导出审计均用子进程验证；没有只调用内部函数替代命令验收。
- 完整组合 **273 passed**：包含上一轮全部结果保存/读取、当前授权、运行清理与非流式最终回复回归，重新启用原空库失败用例。既有 894 条 datetime 弃用提示保留，不计为失败或隐藏。
- 新/改 Python 文件 Ruff、两仓 diff whitespace 检查通过。实际仓库 `migration_governance --baseline-ref HEAD` 通过：主链基线 15 → 当前 22，前置链 0 → 1，冻结 v008 验证通过。

测试通过独立 `pgvector/pgvector:pg16` 容器和随机测试数据库完成，没有挂载业务数据；容器已停止删除。`SIQ_TEST_POSTGRES_URL` 仅注入测试进程。完整命令从研究仓 `apps/api` 执行：

```bash
PYTHONPATH=../..:. .venv/bin/python -m pytest \
  tests/test_migration_governance.py tests/test_migration_prerequisites.py \
  tests/test_business_run_result_store.py tests/test_business_run_results.py \
  tests/test_agent_runtime_read_access.py tests/test_siq_security_export.py \
  tests/test_governed_analysis_entry.py tests/test_qwen38_request_selector.py \
  tests/test_agent_runtime_history.py tests/test_qwen38_request_finalizer.py \
  tests/test_qwen38_request_api.py tests/test_agent_runtime_active_runs.py -q
```

本批未修改业务结果 v1 合同、Web、Go 或模型配置，因此未重复其已有验收。不宣称完整研究 API 测试集或整套产品验收完成。

## 交付、回退与接续

[规格](business-install-baseline-e158-spec.md) 与[证据清单](../evidence/flagship-optimization-20260921/ux-business-install-baseline-e158.json) 固定本批源码和测试结果。E157 原失败日志保留，后续状态由本记录接续，不重写历史证据。

回退 runner/审计代码时保留所有数据、两本账与索引，不删表回退；旧 runner 不认识新前置账，应保留新版只读审计。真实共用 siq_app 部署前仍需核对主账本前缀与代码来源。

编号迁移链修复不等于所有应用表、生产权限和安装体验都已验收。下一步继续终态提交前崩溃恢复、正式产物归属/核验、控制台业务身份连接和结果导航。未提交、推送、发布或替换已安装版本，SEC-F01–F10 保持后续顺序。
