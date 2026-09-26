# CL-02 周期采集同槽重放完整性修复交接

日期：2026-09-26。任务编号 CL-02-SCHEDULE-REPLAY-CLOSEOUT。范围：只修复既有周期预约同槽重放的范围完整性，不增加接口、产品能力、数据表或依赖。

## 1. 复现与旧行为

`reserve_discovery_round`（`apps/control-api/app/discovery_scheduler.py`）的 `previous is not None` 分支（同槽重试）旧实现仅核对：

- `previous.tenant_id == tenant_id`
- 任务存在且数量等于 `previous.task_ids`
- 每个任务的 `environment_id` 与 `payload["target_device_identity"]`

**未核对**任务的 `task_type` 与完整采集 payload（connector、scope.roots、scope.include、inventory_kind）。因此同槽任务的 connector/roots/include/task_type 被篡改、但设备与环境不变时，旧实现仍成功返回原 task_ids。

复现（合成夹具，隔离 SQLite + 测试签名材料，未读真实 .env、未连生产库）：

| 篡改项（同设备同环境） | 旧实现行为 |
| --- | --- |
| `payload.connector` 改为 openclaw | 仍返回原 ID（**缺陷**） |
| `payload.scope.roots` 改为 /tmp/other | 仍返回原 ID（**缺陷**） |
| `payload.scope.include` 改为 SOUL.md | 仍返回原 ID（**缺陷**） |
| `task.task_type` 改为 skill_scan | 仍返回原 ID（**缺陷**） |
| 追加 `payload.inventory_kind=skills` | 仍返回原 ID（**缺陷**） |
| `payload.target_device_identity` 改为 other-device | 拒绝（旧检查已覆盖） |
| `task_ids` 含重复 ID | 拒绝（旧检查已覆盖） |
| `task_ids` 含不存在 ID | 拒绝（旧检查已覆盖） |
| directory 拆分：skill_scan 的 include 被改成 config.yaml | 仍返回原 ID（**缺陷**） |

边界说明：本缺口只证明**计划范围核对**缺失，不证明 Edge 会执行被篡改任务——Edge 领取时仍按现有范围/制品/签名/设备身份独立复验。

## 2. 最小修复

仅改 `apps/control-api/app/discovery_scheduler.py`：

1. 新增文件内小型纯函数（首次创建与重放共用，避免两个任务拆分事实源）：
   - `_connector_specs(connector)`：确定性拆分——directory 的 SKILL.md 单独 `skill_scan`，其余 include 为 `scan`；不含能力/时间检查。
   - `_task_payload(connector, kind, include, device_identity)`：构造与旧实现逐字节一致的 payload（skill_scan 携 `inventory_kind=skills`）。
   - `_expected_round_tasks(plan, device_identity)`：从已验证的 `installation_plan` 派生预期 `(task_type, payload)` 列表。
   - `_task_key(task_type, payload)`：`task_type + "\x00" + 规范化 JSON`，用于多重性比较。
2. 重放分支改为严格核对：`task_ids` 须为非空、无重复、全为字符串的列表；任务数量与 `task_ids` 相等且环境一致；**观测到的 `(task_type, payload)` 多重集合**与从绑定计划派生的预期多重集合 `sorted` 后相等，否则固定错误 `discovery_schedule_replay_unavailable`。返回 `list(task_ids)` 保留原顺序，不依赖 SQL `IN` 返回顺序。
3. 首次创建路径复用 `_connector_specs` / `_task_payload`，能力检查顺序与错误码不变（version 检查 → skill_scan 的 roots/skills 检查 → scan 的 available 检查）。

未改动：合同、模型、迁移、签名模块、路由、共享测试夹具、Edge、Connector、前端、发行工具、README、公共台账、锁文件。未新增 commit、未重签历史任务、未删除/补齐/重签已有记录。重放不引用当前能力心跳/配额/任务终态（背压检查仅在新槽路径），正常重试仍可读回原 ID。

## 3. 实际修改文件

- `apps/control-api/app/discovery_scheduler.py`（修改）
- `apps/control-api/app/tests/test_discovery_scheduler.py`（新增回归）
- `docs/development/enterprise-schedule-replay-closeout-handoff.md`（本文件，新增）

两目标脚本均为未跟踪新文件（并行成果），本任务在其上增量修改，未还原/清理/覆盖他人改动。

## 4. 新增回归（`test_discovery_scheduler.py`）

- `test_replay_rejects_tampered_task_scope`（参数化 connector/roots/include/task_type/inventory_kind/device）：合法同槽先成功，篡改后重放须 `replay_unavailable` 且计数/任务/outbox/审计不变。
- `test_replay_rejects_duplicate_or_missing_task_ids`：重复 ID 与不存在 ID 均拒绝。
- `test_directory_skill_split_replay_and_tamper`（新夹具 `confirmed_directory`，directory 计划含 SKILL.md+config.yaml，v2 能力声明 skill_scan）：首建拆为 skill_scan(include=[SKILL.md])+scan(include=[config.yaml])，同槽重放返回原 ID 且顺序一致；篡改 skill_scan 的 include 后重放拒绝。

复用既有 `confirmed` 夹具与 `counts()` 断言，未新建测试框架。

## 5. 精确测试命令与结果

在 `apps/control-api`（本机已装环境，`--no-sync` 不联网）：

```bash
uv run --no-sync pytest -o addopts='' -q app/tests/test_discovery_scheduler.py app/tests/test_discovery_schedule_tick.py
uv run --no-sync ruff check app/discovery_scheduler.py app/tests/test_discovery_scheduler.py
```

- 两文件合跑：**29 passed**（scheduler 25 + tick 4），0 failed。
- `ruff check`：All checks passed。
- `git diff --check -- <两目标文件>`：干净（exit 0）。

复现阶段（修复前）：上述篡改用例 `DID NOT RAISE`，确认旧缺陷可复现。

## 6. 剩余限制与未运行事项

- 本修复只保证**计划范围核对**（同槽任务集合与绑定计划一致）；**历史签名/原始任务身份溯源**（证明任务当初由本计划签发、未被换 ID 重签）不在本次范围，未添加新存储或信任机制，不声称已证明。
- 未运行后端/前端/Go 全量、浏览器、数据库服务或原生验收脚本。
- 未读取 admin-password.private/真实 .env/密码/令牌/私钥/设备种子；未启停/部署服务、未操作真实设备、未扫描真实目录、未上传、未签发。
- 未提交、未建分支、未推送、未打标签、未发 PR；未运行 git reset/checkout --/clean。

## 7. 状态

未提交、未部署，待主开发者复核。仅完成 CL-02-SCHEDULE-REPLAY-CLOSEOUT，不宣称 CL-02、ENT 总任务或正式发行完成。

## 8. 主开发者复核与修复（2026-09-26）

复核发现类型检查顺序遗漏：`len(set(task_ids))` 在元素字符串校验之前执行。持久 JSON 数组含数组/对象元素时抛出未处理 TypeError，不符合任务书“异常 task_ids 固定拒绝”的要求。新增两个合成持久记录负例，修复前分别复现 `unhashable type: list/dict`，并非已证明外部攻击者能写入该数据库字段。

最小修复只调换条件顺序，先拒绝非字符串元素，再构造 set 检查重复。未改首次预约、范围匹配、签名、权限、事务或历史重放语义。回归断言固定 ValueError、任务/轮次/审计/outbox 数量、预约预算/槽/revision 及原异常记录均不变。

重跑本任务既定两个文件：**31 passed**（含新增两个负例），既有 Starlette/httpx 弃用警告保留；两文件 Ruff 与 git diff --check 通过。未运行全量或真实设备/数据库服务。原交付的范围完整性修复经本次补正验收；历史签名/来源认证仍不由此证明，CL-02 保持开放。未提交、未部署。
