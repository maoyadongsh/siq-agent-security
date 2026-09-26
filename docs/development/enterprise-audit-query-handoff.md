# ENT-019-AUDIT-QUERY 交付记录：审计精确查询增强

日期：2026-09-25
范围声明：本记录只覆盖总任务书（docs/development/enterprise-auto-onboarding-taskbook-20260925.md）中 ENT-019 的 **ENT-019-AUDIT-QUERY 子任务**（审计精确查询增强）。不代表 ENT-019 整体、审计全链路或整体项目已完成。

## 1. 实际修改与新增文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `apps/control-api/app/routers/audit.py` | 修改 | `GET /api/v1/audit-events` 新增四个可选精确过滤参数；列表与总数改为共用同一组过滤条件 |
| `apps/control-api/app/tests/test_audit_exact_filters.py` | 新增 | 19 个独立测试，覆盖任务书要求的全部 16 类场景 |
| `packages/contracts/enterprise-audit-query.v1.md` | 新增 | 查询能力合同 v1 |
| `docs/development/enterprise-audit-query-handoff.md` | 新增 | 本交付记录 |

未修改任何其他文件。开始前已确认 `routers/audit.py` 无其他开发者的在途改动（`git status` 中未列出），无重叠修改冲突。工作树中他人对 `models.py`/`schemas.py` 的修改不涉及 `AuditEvent`，未触碰。

## 2. 新参数、长度边界与兼容行为

新增四个可选查询参数，均为非空严格相等匹配（SQLAlchemy 参数化 `==`，无字符串拼接、无模糊/子串匹配、无 `.strip()`/大小写变换）：

| 参数 | 匹配字段 | 最大长度 | 依据 |
| --- | --- | --- | --- |
| `request_id` | `AuditEvent.request_id` | 64 | `models.py` String(64) |
| `resource_id` | `AuditEvent.resource_id` | 64 | `models.py` String(64) |
| `actor_type` | `AuditEvent.actor_type` | 16 | `models.py` String(16) |
| `decision` | `AuditEvent.decision` | 16 | `models.py` String(16) |

边界行为（FastAPI `Query(min_length=1, max_length=N)`）：

- 缺省：不加过滤，与旧行为一致；
- 空字符串：422；
- 超长：422；恰为上限长度：正常精确查询（测试验证 64/16 边界返回 200 空列表）；
- `actor_type`/`decision` 不限定为 UI 已知枚举，合法长度未知原值可查（测试用 `automaton-x`/`quarantine` 验证）。

旧参数（`actor_id`、`action`、`resource_type`、`cursor`、`limit`、`include_total`）行为完全未改；所有新旧条件 AND 组合。

## 3. 列表与总数共用过滤条件

`audit.py` 中先构造 `filters = [tenant_id == 验证身份租户, ...全部新旧过滤]`，列表查询 `select(AuditEvent).where(*filters)` 与总数查询 `select(func.count()).select_from(AuditEvent).where(*filters)` 使用同一列表；`cursor` 条件只追加到列表查询，不进入总数。因此 `include_total=true` 的总数包含全部新旧过滤、不受 cursor 影响，后续页总数仍是全部匹配数（测试：`test_total_stable_across_pages` 三页总数恒为 5）。排序、`limit` 上限（50/200）、响应头与 cursor 格式/兼容回退均未改动。

## 4. 租户与权限校验保留

- `tenant_id` 仍只来自 `require_permission("audit:read")` 验证后的 `Identity`，无租户覆盖参数；
- 同名 `request_id`/`resource_id` 跨租户严格隔离（`test_cross_tenant_same_identifiers_isolated`，两租户各命中 1 条、总数各为 1）；
- 无 `audit:read` 的 viewer 身份带不带过滤参数均 403（`test_missing_audit_read_permission_forbidden`）；
- 未新增 summary/原文搜索、导出、写入接口；响应仍为现有 `AuditEventOut`。

## 5. 测试命令与真实结果

聚焦测试（19 passed）：

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run pytest -o addopts='' -q app/tests/test_audit_exact_filters.py --tb=short
# 19 passed, 1 warning in 2.21s
```

Lint：

```bash
uv run ruff check app/routers/audit.py app/tests/test_audit_exact_filters.py
# All checks passed!
```

既有审计/权限隔离/分页相关回归（35 passed）：

```bash
uv run pytest -o addopts='' -q \
  app/tests/test_audit_outbox.py app/tests/test_tenant_isolation.py \
  app/tests/test_list_meta.py app/tests/test_console_context.py \
  app/tests/test_request_id.py --tb=short
# 35 passed, 1 warning in 3.31s
```

后端全量：

```bash
uv run pytest -q --tb=short
# 1655 passed, 1 skipped, 0 failed（exit 0；计数按输出符号统计，含本文件 19 个新测试）
```

测试场景对照任务书要求：1 旧查询不变、2 四参数分别过滤、3 AND 组合、4 前缀/子串/超串拒绝、5 未知原值可查、6 无匹配空列表+总数 0、7 多页无重复遗漏、8 后续页总数为全量、9 同时间戳稳定分页、10 同名标识跨租户隔离、11 无权限 403、12 空串 422、13 超长 422（含边界 200）、14 引号/SQL/HTML 值只作数据（原值精确可查、片段不扩大结果）、15 旧 cursor 用法兼容、16 多次 GET 后审计/outbox/业务对象计数与被查询行字段不变。全部实现并通过。

测试使用现有 dev 身份头夹具与隔离 SQLite 测试库，合成记录带唯一前缀 `ent019-aq-`，不读真实设备数据、不调真实服务。

## 6. 查询不产生写入的验证

`test_repeated_gets_do_not_mutate_state`：在一系列 GET（普通过滤、include_total、组合过滤+limit、空串 422）前后，对 `AuditEvent`/`OutboxEvent`/`AgentAsset` 三表行数做快照比较，断言完全相等；并回读被查询审计行，确认 `request_id`/`decision`/`actor_type`/`summary` 字段未被修改。通过。

## 7. 未完成项与范围外问题

- 现有 cursor 错误处理存在既有宽松行为：无法按 `<iso>|<id>` 解析的 cursor 回退为 `id > cursor` 比较（`audit.py` 第 72-73 行），对畸形输入不返回 422。按任务要求未顺手修复，仅记录。
- 旧参数（`actor_id`/`action`/`resource_type`）空字符串按“不过滤”处理（既有行为），与新参数的 422 语义不同；为保持兼容未改动，已在合同 §4 明示。
- Go 模块（agentshield/edge/connectors）与前端测试不属于本切片修改面，未运行。
- 未做 PostgreSQL 实库验证（隔离库为 dev SQLite，与仓库既有测试基线一致）。

## 8. 状态

未提交、未推送、未部署，待主开发者复核。仅声明 ENT-019-AUDIT-QUERY 子任务完成。

## 9. 主开发者复核（2026-09-25）

已逐项阅读路由 diff、合同、模型字段长度和新增测试，未发现本切片需要修复的实现问题。保留旧 cursor 行为，不扩大范围修改。

- 复跑新增 19 项与原有审计/隔离/分页/身份/请求 ID 相关 35 项：**54 passed，1 条既有弃用 warning，4.14 秒**。
- `uv run ruff check app/routers/audit.py app/tests/test_audit_exact_filters.py`：通过。
- 在 apps/control-api 执行 `SIQ_BATCH_WIRE_SAMPLE=/tmp/siq-ent-isolated-wire-20260925/batch-contract-output.json uv run pytest -o addopts='' -q --tb=short`：**1656 passed，0 skipped，0 failed，1 条既有 Starlette/httpx 弃用 warning，85.85 秒**。环境变量指向此前生成的隔离合成合同样本，不连接真实设备或外部业务。
- 此统计来自 pytest 最终汇总，不是进度点号估算；替代聊天摘要中的“165 passed”。与第 5 节旧交付快照的 1655 passed/1 skipped 区别在于本轮提供了实际合同样本，未跳过对应测试。
- `git diff --check`：通过。未改变该切片代码；本次为主开发者实际验收记录。

ENT-019-AUDIT-QUERY 子任务验收通过；不等于 ENT-019 全链路完成，亦不证明生产 PostgreSQL 或已部署状态。未提交、未推送、未部署。
