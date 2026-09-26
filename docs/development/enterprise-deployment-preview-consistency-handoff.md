# CL-04-PREVIEW-CONSISTENCY-CLOSEOUT 交付记录：两个预览接口的登记身份一致性复验

日期：2026-09-26。范围：`POST /api/v1/deployment-preview` 与 `POST /api/v1/deployment-previews/batch` 在准备期发生绑定吊销或身份/来源漂移时，是否因 ORM identity map 旧值而返回已经失效的预览响应。

结论：**该风险已复现，属真实缺陷（预览响应一致性缺陷）**；已做最小修复（+13 行，复用既有复验函数）。**这不是已确认的执行绕过**：执行链 `execute_deployment` 另有独立复验，本次只收口预览响应本身。未提交、未推送、未部署，待主开发者复核。本记录只声明该预览一致性子项完成，不关闭 CL-04，也不声明整体项目完成。

## 1. 实际链路与基线

两个接口的实际顺序（修复前）：

**`preview_deployment`**（`apps/control-api/app/routers/deployment_preview.py:230`）：

1. `response.headers["Cache-Control"] = "no-store"`。
2. `_prepare(body, session, identity)`（本文件内定义）：CR 行锁（`with_for_update().execution_options(populate_existing=True)`）→ 环境/策略 → `policy:manage`/`policy:read`/`env:read` + 额外权限 → 预约排斥 → CR 状态 → 环境 enforce → 绑定 `active`/环境一致 → `require_binding_source_identity` → 隔离门禁 → selector 强绑定 → 后端能力检查 → openshell-cli 分支：`adapter.probe()`（**外部只读探测**）→ `require_target_authority` → 编译/validate/plan_change → 返回 `PreparedDeployment`，其 `binding_snapshot` 由 `snapshot_binding_identity(binding)` 在函数返回时生成。
3. `_snapshot(prepared, identity)`：`target`/`action`/`base_revision`/`preview_digest` 等**全部**读自 `prepared.binding` 这个 ORM 对象。
4. 直接返回。此接口没有客户端摘要输入，因此**没有** digest 失败关闭这一步可依赖。

**`preview_deployment_batch`**（同文件 `:258`）：`_locate_batch`（同租户定位失败 404 → 权限失败 403）→ 按 `binding_id` 排序 → 逐项 `_prepare` + `_snapshot` → `(backend, target)` 重复即 409 `batch_preview_target_overlap` → 对 `items` 计算规范 JSON 摘要 → 返回整批。

**关键机制**：`prepare_deployment` 用 `session.scalar(select(RuntimeBinding)...)` 载入绑定，**没有** `populate_existing=True`，之后不再重读该行；请求会话 `expire_on_commit=False` 且请求内无 commit/refresh。因此自该 SELECT 起，`binding` 的所有属性在**整个请求内**是常量，不随持久状态变化。`_snapshot` 与 `binding_snapshot` 都从这个对象取值，二者记录的都只是“准备阶段读到的那份值”。

**既有复验的覆盖面**：`require_binding_identity_unchanged(session, snapshot, tenant_id)`（`app/binding_identity.py:25`）按 `id + tenant_id` 做**列级**重读（列级查询不经 ORM identity map），再比 `status`（非 active → 409 `binding_revoked`）、六个标量字段 `status`/`environment_id`/`asset_id`/`agent_instance_id`/`backend`/`backend_target_id`（任一不符 → 409 `binding_source_identity_changed`），最后用**当前持久值**重跑 `_source_identity_missing`（AgentInstance ⨝ AgentAsset，校验实例/资产归属与 `environment_id`）。它此前只在 `execute_deployment` 的“最后一次外部探测之后、任何副作用之前”被调用（`app/routers/policies.py:605`）。已验收的 `deployment-preview/impact` 已复用同一函数；两个预览接口此前没有调用。

**`_prepare`/`_snapshot`/`_locate_batch` 的全部消费者（本次只读检索，未修改）**：本文件内的 `submit_deployment`、`app/routers/deployment_impact.py`、`app/routers/deployment_submission.py`、`app/routers/deployment_batch_draft.py`（`change_review._snapshot` 同名但无关）。本次未改动其中任何一个；也未改动 `_prepare`/`_snapshot`/`_locate_batch` 本身的既有语义。

**读一致性边界**：请求级会话（`app/db.py:59` 的 `get_session`）只 `close` 不 commit；单请求内多次读取由数据库隔离级别决定。SQLite（pysqlite）对纯 SELECT 不显式开事务，列级重读能看到别的已提交事务；PostgreSQL READ COMMITTED 下每条语句取最新已提交快照，语义一致。REPEATABLE READ 及以上不成立（见 §6）。

**基线**：`deployment_preview.py` 是**已跟踪**文件，但工作树里的该文件同时携带其他开发线的在途改动（`git diff --stat` → 109 插入 / 5 删除，其中本次只占 13 插入 / 0 删除），因此 HEAD 不是本任务的干净基线，且任务第七节明确**禁止在共享工作树临时覆盖或替换整个源文件做基线**。故基线对照在**独立临时副本**中完成：`rsync` 复制 `apps/control-api`（排除 `.venv`/缓存）到 `/tmp/prefix-baseline`，`ln -s` 复用既有 `.venv`，在该副本内按插入位置精确删除本次新增的 13 行。`diff -u` 校验：副本与共享工作树文件之间的差异**恰为**本次新增的 13 行（`grep -c '^+[^+]'` = 13、`^-[^-]` = 0），共享工作树全程未被覆盖。

## 2. 是否存在真实缺陷：是（响应一致性缺陷，不是执行绕过）

**缺陷一（单项接口）**：`_prepare` 的外部只读探测（openshell-cli 的 `adapter.probe()`）期间，若另一事务提交绑定吊销或身份/来源漂移，本次请求的 ORM 对象仍持有准备阶段旧值，`_snapshot` 的 `target`/`action`/`base_revision`/`preview_digest` 全部从旧值产出 → 返回 **HTTP 200 与已经失效的预览**；同一持久状态若早一步提交，同一接口会以 409 `binding_revoked` / `binding_source_identity_changed` 拒绝。

**缺陷二（批量接口的跨条目窗口）**：批处理是“逐项 `_prepare` + `_snapshot`”，后续条目的外部探测**可能使前面条目失效**。条目 A 已完整准备并生成 `preview_digest` 之后，条目 B 的 `probe()` 期间提交 A 的吊销 → 仍然返回 **HTTP 200 且响应 `items` 里包含 A 的陈旧预览**。这一点**不能**靠“每项 `_prepare` 之后立即复验一次”覆盖：复验必须落在**全部外部准备完成之后、成功批次响应生成之前**才有意义。

**复现输入**（真实 TestClient + 真实路由 + 隔离租户 + 合成 SQLite；openshell-cli 后端用 `StatefulRunner` 与 operator target authority 文件作可控探测替身，不接真实 OpenShell）：

- 目标：全新租户 + enforce 环境 + 经 API 登记的 `active` 绑定（`backend=openshell-cli`，目标 `s1`/`s2`）+ 已批准变更请求 + operator authority 文件。
- 安装探测包装：**本次预览请求的 `probe()` 调用返回后**，用独立会话（`session_scope()`，独立连接）提交漂移——即漂移落在该请求的准备期外部探测之内。
- 单项：直接调 `POST /api/v1/deployment-preview`。批量：调 `POST /api/v1/deployment-previews/batch`，漂移落在**第 2 次** `probe()`（条目 B 的探测）内，此时条目 A 已准备并快照完毕。

**修复前 / 修复后对照**（同一测试文件、同一夹具、同一命令）：

| 场景 | 漂移（带外提交） | 修复前 | 修复后 |
| --- | --- | --- | --- |
| 单项 | 绑定 `active` → `revoked` | **200** 陈旧预览 | 409 `binding_revoked` |
| 单项 | 绑定 `asset_id` 改指另一资产 | **200** 陈旧预览 | 409 `binding_source_identity_changed` |
| 单项 | 实例 `asset_id` 改指另一角色资产（绑定行不变） | **200** 陈旧预览 | 409 `binding_source_identity_changed` |
| 批量 | 第 2 次探测（条目 B）期间吊销条目 A（A 已准备快照） | **200**，`items` 含 A 的陈旧预览 | 409 `binding_revoked`，无 `items` |
| 批量 | 末项自身在其探测期间被吊销（跨条目窗口的最小对照） | **200**，整批返回 | 409 `binding_revoked`，无 `items` |

**可达性**：吊销路径有真实、已审计的合法入口 `POST /api/v1/runtime-bindings/{binding_id}/revoke`（`app/routers/bindings.py:131`，独立提交自己的事务）。窗口长度由 `_prepare` 内的外部调用决定：openshell-cli 分支的 `probe()` 是真实子进程/网关调用，是窗口的主体；默认 fake 后端无网络探测，窗口更窄但同类问题仍存在。

**为什么这不是执行绕过（必须区分）**：客户端拿到预览后若去 `POST /api/v1/deployment-preview/submit`，`submit_deployment` 会**重新** `_prepare` + `_snapshot` 并逐字节比对客户端回传的 `preview_digest`，不匹配即 409 `deployment_preview_changed`；即便漂移字段落在 digest 覆盖之外，`execute_deployment` 在最后一次外部探测之后、任何副作用之前还会再跑一次 `require_binding_identity_unchanged`。因此陈旧预览**不会**转化为执行权限。本缺陷的实际影响是“只读预览响应在窗口内不反映持久状态”，会让使用者基于过期预览判断。

**未发现缺陷的部分**（实测，不重复加测试）：`_locate_batch` 的 404→403 顺序、权限门禁先于任何外部探测、批量的绑定 id 排序、`(backend,target)` 重叠拒绝、条数上限、请求/响应 schema 与字段、规范 JSON 摘要算法、`Cache-Control: no-store`、`batch_submission_supported=false`、只读性（不创建 Deployment/EdgeTask/预约/Finding/审计/outbox，不改绑定，不写回，无 apply/rollback，无重试、无重编译）——修复前后均成立。

## 3. 最小修复及复用的既有机制

修改（白名单内，唯一改动文件）：`apps/control-api/app/routers/deployment_preview.py`，**+13 行 / -0 行**（其余在途 diff 属其他开发线，未触碰）。

- **改动一**：顶层新增导入（`from app.binding_identity import require_binding_identity_unchanged`）。

- **改动二**：`preview_deployment` 在 `_prepare` 之后、`_snapshot` 之前：

```python
require_binding_identity_unchanged(session, prepared.binding_snapshot, identity.tenant_id)
```

- **改动三**：`preview_deployment_batch` 在既有循环内只多收集 `prepared_items`（排序键、`target = (value.backend, value.target)` 重叠判定、`targets.add(target)` 的位置与语义**未变**），循环结束后、计算 `digest` 之前：

```python
for prepared in prepared_items:
    require_binding_identity_unchanged(session, prepared.binding_snapshot, identity.tenant_id)
```

- **复用而非新造**：直接调用既有复验函数，使用既有 `binding_snapshot` 与既有 `SNAPSHOT_FIELDS`，未复制第二套绑定权限/来源判定，未新增权限枚举、schema、错误码或公共错误体系（`binding_revoked` / `binding_source_identity_changed` 本来就是 `_prepare` 会对同一漂移产生的码）。
- **位置**：单项在“最后一次外部只读探测之后、响应生成之前”；批量在“**全部**外部准备完成之后、成功批次响应生成之前”，正是为覆盖 §2 缺陷二描述的跨条目窗口。预览内容**从不**基于未复验状态生成。
- **批量的整批失败语义**：任一条目复验失败即抛 409，整批不返回成功预览，无部分成功、无部分 `items`（既有 `test_deployment_batch_preview.py` 断言 `"items" not in response.json()` 的行为保持一致）。
- **保留的约束**：不新增网络探测、不重复 `_prepare`、不持有数据库锁跨越外部网络调用、不采用漂移后的新身份、不重试、不重编译、不修改执行链、不把预览响应变成授权令牌。
- **顺序保留**：租户定位 404 → 权限 403 → 逐项 `_prepare`（含原错误码）→ 重叠 409 → 最终复验 → 摘要 → 响应。已存在的拒绝（例如重叠）仍然先于最终复验发生，不会为复验强行跑完所有探测。
- **只读性**：复验是列级 SELECT + 拒绝，不写任何表。

## 4. 测试命令、实际数量、失败情况

环境：`apps/control-api`，`uv run --no-sync pytest -o addopts=''`。SQLite 合成夹具 + 隔离租户 + 模拟适配器；未安装依赖、未联网、未连真实数据库/控制面/设备、未启停服务、未改动依赖或锁文件。

新增 `apps/control-api/app/tests/test_deployment_preview_consistency.py`（6 个函数 / 8 个用例）：openshell 单项预览稳定且只读（含重复调用稳定、不同 actor 摘要不同、持久行与五表计数不变）、openshell 批量预览排序稳定且只读、单项探测期漂移 ×3（吊销/绑定改资产/实例来源改指）、批量第二项探测期吊销整批拒绝（断言探测序列 `calls == [1,1]`、响应体恰为 `{"detail":"binding_revoked"}`、无 `items`）、批量末项漂移无部分结果、拒绝先于任何外部探测（跨租户 404 不回显字段、无权限 403、探测计数为 0）。

实际结果：

1. **修复前基线**（独立临时副本 `/tmp/prefix-baseline`，共享工作树未被覆盖）：
   `uv run --no-sync pytest -o addopts='' -q app/tests/test_deployment_preview_consistency.py` → **5 failed / 3 passed**，5 个失败全部为 `assert 200 == 409`，批量两条的失败消息里能看到响应体确实带了完整 `items` 且包含已被吊销的绑定。
2. 修复后本文件 → **8 passed**。
3. 合并定向套件：
   `... -q app/tests/test_deployment_preview_consistency.py app/tests/test_deployment_preview.py app/tests/test_deployment_batch_preview.py app/tests/test_deployment_impact.py app/tests/test_deployment_impact_consistency.py` → **54 passed**（含原有 preview/batch/impact 及其一致性命例全部通过，证明新增顶层导入无循环依赖、既有语义未变）。
4. 直接相关 submission 回归：
   `... -q app/tests/test_deployment_submission.py app/tests/test_binding_execution_recheck.py app/tests/test_binding_source_identity.py app/tests/test_submission_execution_stage.py` → **40 passed**。
5. `uv run --no-sync ruff check app/routers/deployment_preview.py app/tests/test_deployment_preview_consistency.py` → **All checks passed!**
6. `git diff --check` → 通过（exit 0）；两个目标文件的尾随空白/制表符检查 → 无。

未运行：control-api 全量、Go/前端/浏览器、真实 PostgreSQL、真实 OpenShell。修复前后对比在同一测试文件、同一夹具、同一命令下取得，基线副本与工作树文件仅差本次 13 行，因此失败可归因于该插入。

## 5. 只读性、租户、权限与摘要兼容证据

- **只读性**：新增用例在成功与各类拒绝路径上断言 `Deployment`/`EdgeTask`/`Finding`/`AuditEvent`/`OutboxEvent` 五表计数不变，且 `DeploymentSubmission` 预约集合（id + state）不变。断言只用仓库中既有的模型与既有预约模型，未新增任何模型或写路径来“方便”断言。绑定持久行（六个标量字段）在稳定用例中也不变。
- **摘要兼容**：批量摘要仍是 `sha256`，覆盖既有规范 JSON（`schema_version`/`tenant`/`actor`/`actor_type`/`items`），修复只在摘要**之前**插入复验，不改变任何输入字段或算法；单项 `preview_digest` 同理。**未**把生产摘要/比较公式复制进测试作为预期（任务明确禁止），改用合同派生性质（sha256 十六进制长度 64、同输入稳定、不同 actor 不同）+ 既有 `test_deployment_preview.py`/`test_deployment_submission.py` 全绿作为兼容性证据。
- **租户**：跨租户请求 404，响应体恰为 `{"detail":"not_found"}`，`binding_id`/`asset_id`/`agent_instance_id`/`environment_id` 均不出现在响应文本中。
- **权限**：预览接口需要 `policy:manage`/`policy:read`/`env:read`（`_prepare` 的额外权限；批量还有 `_locate_batch` 的前置检查），**不需要** `agent:read`。用例先核对真实权限映射——`assert not REQUIRED_PERMISSIONS <= ROLE_PERMISSIONS["viewer"]` 与 `assert "agent:read" in ROLE_PERMISSIONS["agent_owner"]`——再断言 `viewer` 在两个接口上都是 403，且**外部探测调用次数为 0**。即：不把拥有 `agent:read` 的 `agent_owner` 当成缺少 `agent:read`，也不声称 403 证明“缺少 `agent:read` 被拒”（该结论在本接口上不成立）。
- **固定值保留**：批量响应 `batch_submission_supported=false` 原样返回；未把任何 `unknown`/`false` 改成肯定值。

## 6. 未解决边界

- **复验之后的并发窗口未消除**：复验（读）与响应返回之间仍可提交漂移；本修复只保证“复验时已能从数据库观察到的漂移被拒绝”，不构成原子快照，不消除 TOCTOU。
- **复验只见当前事务可见的数据**：列级重读不越过数据库隔离级别。SQLite（pysqlite）纯 SELECT 能看到新提交；PostgreSQL READ COMMITTED 语义相同；**REPEATABLE READ 及以上看不到复验前的并发提交**，此时本复验不提供任何额外保证。
- **批量不是原子快照**：最终复验是**多条列级查询**的顺序执行，不是整批一次性一致快照；条目 A 复验通过后、条目 B 复验（乃至响应返回）之前提交的 A 漂移仍然不可见。窗口被显著收窄，但未被消除。
- **不证明复验字段集之外的不变量**：本修复只覆盖登记身份字段与实例/资产来源关联（`SNAPSHOT_FIELDS` 及其来源核对范围）。**不证明**探测期间策略、审批状态、`attestation` 或其他运行态字段未变——它们既不在 `SNAPSHOT_FIELDS` 内，也不由本复验覆盖。
- **不证明真实环境行为**：全部证据来自 SQLite 合成夹具、TestClient 与模拟适配器；不证明真实 PostgreSQL 并发隔离，不证明真实 OpenShell、共享沙箱完整覆盖、Skill 独立隔离或真实运行归属（仍处于 `registered_binding_only` / `unknown` / `not_established`）。
- **预览不是授权令牌**：`preview_digest` 只是预览内容的完整性标记，不构成执行授权、不构成影响确认。**执行前的独立复验（`execute_deployment`）必须保留**，不得因本次预览侧复验而删除或弱化。
- **以上限制不构成新增要求**：这些边界**不应**被解释为需要自行增加行锁、租约、快照读或新的公共合同；是否引入属架构决策，超出本子项白名单。
- **公开合同未同步（需越白名单，仅记录，未改）**：`packages/contracts/enterprise-deployment-batch-preview.v1.md`、`packages/contracts/deployment-preview.v1.schema.json` 本轮只读。若合同负责人认为需要在合同里写明“预览生成前按持久状态复验绑定身份、漂移即 409”，属其职权范围，`wire` 无需变更；我没有擅自修改。
- **带外变更的范围**：`asset_id`/`agent_instance_id` 改指与实例来源改指在本次复现中是带外提交，不声称存在合法修改 API；`revoke` 确有合法入口（§2）。

## 7. 状态

CL-04-PREVIEW-CONSISTENCY-CLOSEOUT：机制核对完成、缺陷复现完成（单项 + 批量跨条目窗口）、最小修复完成、定向验证完成。**未提交、未推送、未部署**，待主开发者复核。仅声明本预览一致性子项完成，**不关闭 CL-04**，也不声明整体项目或正式发行完成。未触碰其他开发线（Kimi/GLM/Qwen/主开发者）的文件，未改动执行链、绑定判定、公共合同、前端、Edge、Connector、依赖与锁文件。

## 8. 主开发者验收（2026-09-26）

本子项通过定向验收，未发现需追加业务修复的问题。核对最终批次复验确实位于全部 `_prepare` 之后，覆盖 B 探测期间 A 吊销及末项自身漂移；原目标重叠判断、排序、摘要、整批拒绝与提交/执行链未改动。固定字段复验没有被描述为完整共享影响授权。

主开发者仅修正代码注释中的“ORM 请求内恒定”为“可能持有缓存旧值”，并在 `enterprise-deployment-batch-preview.v1.md` 补充单项/批量复验保证和限制，不改 JSON schema 或 wire。关于隔离级别的具体行为仍需真实数据库验证；不能从本次 SQLite 结果推导所有部署配置一致。

独立合并执行交付第 4 节的两个定向集合（共九个测试文件）：**94 passed**，16.24s，1 条既有 Starlette/httpx 弃用警告。Ruff 两文件检查、git diff --check 和本次文件尾随空白检查通过。未运行全量、前端、Go、真实 PostgreSQL/OpenShell，也未覆盖共享工作树做基线。

验收文件：deployment_preview.py（仅注释）、批量预览合同（追加说明）及本记录；其他开发者测试改动保留。未提交、未推送、未部署；仅接受预览登记身份一致性子项，不关闭 CL-04 或整体项目。
