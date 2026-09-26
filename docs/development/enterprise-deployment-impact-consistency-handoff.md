# CL-04-IMPACT-SNAPSHOT-CLOSEOUT 交付记录：影响报告生成时的证据一致性复验

日期：2026-09-26。范围：`POST /api/v1/deployment-preview/impact` 在准备期发生绑定吊销、身份字段变化或实例来源变化时，是否因 ORM identity map 旧值而返回已经失效的身份报告。

结论：**该风险已复现，属真实缺陷**；已做最小修复。未提交、未部署，待主开发者复核。本记录只声明该子项完成，不关闭 CL-04，也不声明整体项目完成。

## 1. 实际检查链路与基线

`inspect_deployment_impact`（`apps/control-api/app/routers/deployment_impact.py:54`）在修复前的实际顺序：

1. `_locate_batch`：按验证租户定位 CR/策略/环境/绑定（列级 `select(...)`，只取 id，不填充 identity map），失败 404；随后 `policy:manage`/`policy:read`/`env:read` 403。
2. `ensure_permission(identity, "agent:read")`——在 `_prepare`（因而在任何外部探测）之前。
3. `_prepare` → `policies.prepare_deployment`：CR 行锁（`with_for_update().execution_options(populate_existing=True)`）→ 环境/策略 → `policy:manage`+额外权限 → 预约排斥 → CR 状态 → 环境 enforce → **绑定 `active`/环境一致 → `require_binding_source_identity`** → 隔离门禁 → selector 强绑定 → 后端/能力检查 → openshell-cli 分支：`adapter.probe()`（**外部只读探测**）→ `require_target_authority`（针对 operator authority 文件做精确匹配）→ 编译/validate/plan_change → 返回 `PreparedDeployment`，其中 `binding_snapshot` 由 `snapshot_binding_identity(binding)` 在**函数返回时**生成。
4. `_snapshot(prepared, identity)`：digest 覆盖 `binding` 的 id/environment/asset/instance/backend/target/status/**attestation**、`backend_scope`、`live` 等；这些值全部来自 `prepared.binding` 这个 ORM 对象。
5. `preview_digest` 比对（`hmac.compare_digest`）→ 不匹配 409 `deployment_preview_changed`。
6. `registered_subject` 取自同一个 `prepared.binding`。

**关键机制**：`prepare_deployment` 用 `session.scalar(select(RuntimeBinding)...)` 载入绑定，**没有** `populate_existing=True`，之后不再重读该行。请求会话 `expire_on_commit=False`，请求内也没有 commit/refresh。因此从该 SELECT 起，`binding` 的所有属性在整个请求内都是**常量**，不随持久状态变化。

**绑定已有独立标量快照**：`snapshot_binding_identity`（`app/binding_identity.py:20`）返回绑定 id + 六个标量字段（`status`、`environment_id`、`asset_id`、`agent_instance_id`、`backend`、`backend_target_id`）的普通 dict。但快照也是从同一个 ORM 对象 `getattr` 得到的，所以它记录的是**准备阶段读到的那份值**，不是“准备结束时刻的持久值”。

**既有复验的覆盖面**：`require_binding_identity_unchanged(session, snapshot, tenant_id)`（`app/binding_identity.py:25`）按 `id + tenant_id`（租户谓词只来自验证身份）做**列级**重读——列级查询不经 ORM identity map——再比 `status`（非 active → 409 `binding_revoked`）、六个标量字段（任一不符 → 409 `binding_source_identity_changed`），最后用**当前持久值**重跑 `_source_identity_missing`（AgentInstance ⨝ AgentAsset，校验实例/资产归属与 `environment_id`）。它此前只在 `execute_deployment` 的“最后一次外部探测之后、任何副作用之前”被调用（`app/routers/policies.py:605`），影响预检路径没有调用。

**读一致性边界**：请求级会话（`app/db.py:59` 的 `get_session`）只 `close` 不 commit，单请求内的多次读取由数据库隔离级别决定是否能看到别的已提交事务。SQLite（pysqlite）对纯 SELECT 不显式开事务，列级重读能看到新提交的数据；PostgreSQL READ COMMITTED 下每条语句取最新已提交快照，语义一致。REPEATABLE READ 及以上不成立（见 §6）。

**基线**：`apps/control-api/app/routers/deployment_impact.py` 在本仓库中是**未跟踪文件**（`git status --short` → `??`），HEAD 里不存在该路径（`git show HEAD:...` 报 “不在 HEAD 中”）。因此本任务没有 HEAD 基线，回退基线使用我自己的修复前副本（由当前文件精确删除插入的 8 行生成），见 §4。

## 2. 是否存在真实缺陷：是

**缺陷**：`_prepare` 的外部只读探测（openshell-cli 的 `adapter.probe()`）期间，若另一事务提交了绑定吊销或身份/来源漂移，本次请求的 ORM identity map 仍持有准备阶段旧值，`_snapshot` 的 `preview_digest` 与 `registered_subject` 都从旧值产出。客户端提交的原摘要（此前由 `/api/v1/deployment-preview` 在同一旧状态上生成）**照样匹配**，于是接口返回 **HTTP 200 与已经失效的身份报告**；同一持久状态若早一步提交，同一接口会以 409 `binding_revoked` / `binding_source_identity_changed` 拒绝。结果是**结果依赖漂移发生的时刻**，报告不再是一份可信的“报告生成时的登记身份”证据。

**复现输入**（真实 TestClient + 真实路由 + 隔离 SQLite；openshell-cli 后端由 `StatefulRunner` 与 operator target authority 文件作可控探测替身，不接真实 OpenShell）：

- 目标：全新租户 + enforce 环境 + 经 API 登记的 `active` 绑定（`backend=openshell-cli`、`target=s1`）+ 已批准变更请求 + operator authority 文件。
- 先调 `POST /api/v1/deployment-preview` 取得 `preview_digest`（探测计数 1）。
- 安装探测包装：**本次请求的 `probe()` 返回后**，用独立会话（`session_scope()`，独立连接）提交漂移，即漂移落在“准备期最后一次外部只读探测”之内。
- 再调 `POST /api/v1/deployment-preview/impact`，提交原 `preview_digest`。

**修复前结果**（5 个失败用例）：

| 漂移（带外提交） | 修复前 | 修复后 |
| --- | --- | --- |
| 绑定 `active` → `revoked` | **200**；`preview` 与 `registered_subject` 照常返回；持久行已为 `revoked` | 409 `binding_revoked` |
| 绑定 `asset_id` 改指另一资产 | **200**；`registered_subject.asset_id` = 漂移前资产 | 409 `binding_source_identity_changed` |
| 绑定 `agent_instance_id` 改指另一实例 | **200**；`registered_subject.agent_instance_id` = 漂移前实例 | 409 `binding_source_identity_changed` |
| 实例 `asset_id` 改指另一角色资产（绑定行不变） | **200**；来源核对未重跑 | 409 `binding_source_identity_changed` |
| 默认 fake 后端：`_prepare` 之后、报告生成之前提交吊销 | **200** | 409 `binding_revoked` |

**可达性**：

- 吊销路径有真实、已审计的合法入口：`POST /api/v1/runtime-bindings/{binding_id}/revoke`（`app/routers/bindings.py:131`，独立提交自己的事务）。任何持该权限的操作者/并发流程都可在窗口内触发。
- 窗口长度由 `_prepare` 内的外部调用决定：openshell-cli 分支的 `probe()` 是真实子进程/网关调用，是窗口的主体；默认 fake 后端没有网络探测，窗口仅剩预检内部的本地读取，同类问题仍然存在但更窄。
- 影响面：报告被当作“登记身份的当前快照”消费（合同要求 `registered_subject` 与 `coverage=registered_binding_only`），过期身份会误导后续人工判断。**注意**：报告不是授权令牌，`impact_digest` 也不被任何执行接口接受（见 §6），因此本缺陷不直接放大为执行权限绕过；同时部署执行路径另有 `execute_deployment` 的复验兜底。
- 同理可达但**不在本次白名单**的还有 `POST /api/v1/deployment-preview` 与 `POST /api/v1/deployment-previews/batch`（同一 `_prepare`/`_snapshot` 旧值读取）。它们的消费者是 `submit`，而 `submit` 走 `execute_deployment` 的复验；见 §5 记录的后续项。

**未发现缺陷的部分**（实测，不重复加测试）：`_locate_batch` 的 404/403 顺序、`agent:read` 先于任何外部探测、`preview_digest` 不匹配失败关闭、响应 schema/字段/规范 JSON 摘要算法、`coverage`/`shared_runtime_occupants`/`skill_isolation`/`execution_confirmation_supported` 四个固定值、`Cache-Control: no-store`、只读性（不创建 Deployment/EdgeTask/Finding/AuditEvent/OutboxEvent，不改绑定）——修复前后均成立。

## 3. 最小修复及复用的既有机制

修改（白名单内，唯一改动文件）：`apps/control-api/app/routers/deployment_impact.py`（+8 行）。

在 `prepared = _prepare(...)` 之后、`preview = _snapshot(...)`（报告生成）之前插入：

```python
from app.binding_identity import require_binding_identity_unchanged

require_binding_identity_unchanged(session, prepared.binding_snapshot, identity.tenant_id)
```

- **复用而非新造**：直接调用既有的绑定身份复验函数，使用既有的 `binding_snapshot` 与既有 `SNAPSHOT_FIELDS`，未复制第二套绑定权限/来源判定，未新增权限枚举、schema、错误码或公共错误体系。
- **位置**：`_prepare` 是该请求内最后一次外部只读探测的所在（含 probe + `require_target_authority`），插入点在其返回之后、`_snapshot` 之前，与任务要求的“最后一次外部只读探测后、报告生成前复验”一致，且报告内容**从不**基于未复验状态生成。
- **拒绝语义**：漂移即 409，复用既有固定脱敏错误码 `binding_revoked` / `binding_source_identity_changed`（`_prepare` 本来就会产生这两个码，故不是新增对外行为）；不采用新值、不重编译、不重算成新身份、不刷新后继续、不重试、不吞异常返回空报告、不修改执行链。
- **一致性推论**：复验通过与 `_snapshot` 读取之间没有对该绑定行的写操作，且两者读的是同一个 ORM 对象；因此复验通过即保证 `_snapshot` 与 `registered_subject` 使用的 `status/environment_id/asset_id/agent_instance_id/backend/backend_target_id` 等于持久值，且实例/资产来源核对在报告生成时刻成立。
- **顺序保留**：404（同租户定位）→ 403（权限）→ `agent:read` → 复验 → digest → 报告，未改动既有错误优先级；漂移早于请求提交时，`_prepare` 自己就以原错误码拒绝，`preview_digest` 语义不变。
- **只读性**：复验是列级 SELECT + 拒绝，不写任何表。

## 4. 测试命令、实际数量、失败情况

环境：`apps/control-api`，`uv run --no-sync pytest -o addopts=''`。SQLite 合成夹具 + 隔离租户 + 模拟适配器；未安装依赖、未联网、未连真实数据库/控制面/设备、未启停服务。

新增 `apps/control-api/app/tests/test_deployment_impact_consistency.py`（6 个函数 / 8 个用例）：稳定身份对照（含独立持久行比对与只读断言）、探测期吊销、探测期身份/来源漂移 ×3、默认后端报告窗口吊销、复验字段集外漂移仍由 digest 失败关闭、拒绝先于外部探测且不回显字段。

实际结果：

1. 修复前基线（把我的修复前副本覆盖回 `deployment_impact.py`，用后 `cp` 还原并 `cmp` 校验一致）：
   `... -q app/tests/test_deployment_impact_consistency.py app/tests/test_deployment_impact.py` → **5 failed / 10 passed**（10 passed = 原 7 项 + 本文件 3 项对照/既有语义项）。
2. 修复后同一命令 → **15 passed**（本文件 8 + 原 `test_deployment_impact.py` 7）。
3. 直接相关回归（复用绑定校验与预检链路）：
   `... -q app/tests/test_binding_execution_recheck.py app/tests/test_binding_source_identity.py app/tests/test_deployment_preview.py app/tests/test_deployment_submission.py` → **55 passed**。
4. `uv run --no-sync ruff check app/routers/deployment_impact.py app/tests/test_deployment_impact_consistency.py` → **All checks passed!**
5. `git diff --check` → 通过；`deployment_impact.py`（未跟踪）与新测试文件的尾随空白检查 → 无。

未运行：control-api 全量、Go/前端/浏览器、真实 PostgreSQL、真实 OpenShell、`test_policy_flow.py`（既有顺序敏感脆弱性，见先前交接记录，与本改动无关）。修复前后对比在同一测试文件、同一夹具、同一命令下取得，因此失败可归因于该 8 行插入。

## 5. 只读性、租户与权限边界验证

- **只读性**：新增用例在成功与各类拒绝路径上断言 `Deployment`/`EdgeTask`/`Finding`/`AuditEvent`/`OutboxEvent` 五表计数不变，且绑定持久行（六个标量字段）不变；未新增任何写入、预约、任务、审计或 outbox。修复本身不新增写入。
- **租户**：跨租户请求 404，响应体恰为 `{"detail":"not_found"}`，`binding_id`/`asset_id`/`agent_instance_id`/`environment_id` 均不出现在响应文本中。
- **权限**：同租户但无 `agent:read` → 403；配合探测计数器断言**外部探测调用次数为 0**（权限与租户拒绝都发生在任何外部探测之前）。
- **固定未知值**：`coverage=registered_binding_only`、`shared_runtime_occupants=unknown`、`skill_isolation=not_established`、`execution_confirmation_supported=false` 在修复后仍原样返回；没有把 `unknown` 改成 `verified`。不返回 attestation、原始秘密或其他租户对象。
- **预期值来源**：漂移是否已生效、以及应返回的身份，均来自独立会话的持久行读取与变更前后对比，不从被测响应反推；漂移一律经独立会话真实提交，测试内标注为**数据库带外变更**（`asset_id`/`agent_instance_id` 的改指与实例来源改指没有对应的合法修改 API，属带外提交，不声称可经合法 API 修改；绑定吊销有合法入口，见 §2）。

## 6. 未解决边界

- **复验之后的并发窗口未消除**：复验（读）与响应返回之间仍可提交漂移。本修复只保证“复验时已能从数据库观察到的漂移被拒绝”，不构成原子快照，也不消除 TOCTOU。消除它需要绑定行锁贯穿预检、或读快照/租约协议，超出本任务范围。
- **SQLite 不证明 PostgreSQL 并发隔离**：全部证据来自 SQLite 合成夹具与模拟适配器（L1/L2 级），不冒充真实 PostgreSQL 并发证明，也不冒充真实 OpenShell、真实设备或生产环境的验证。
- **影响报告不是授权令牌**：`impact_digest` 不被任何执行接口接受，本合同不声称它是完整影响确认；客户端不得据此自动部署。本次修复不改变这一点。
- **本任务不证明**共享沙箱完整覆盖、Skill 独立隔离、真实运行归属或运行时占用；仍处于 `registered_binding_only` / `unknown` / `not_established`。
- **公开合同未同步（需越白名单，仅记录）**：`packages/contracts/enterprise-deployment-impact.v1.md` 本轮只读。建议后续由合同负责人补一句实现保证（“报告生成前按持久状态复验绑定身份，漂移即 409，不返回过时影响报告”），wire 无需变更。我没有擅自修改该文件。
- **同源旧值读取仍在其他路由（仅记录，未改）**：`POST /api/v1/deployment-preview`（`:228`）与 `POST /api/v1/deployment-previews/batch`（`:250`）用同一 `_prepare`/`_snapshot` 从 ORM 旧值生成响应。它们的 digest 在 `submit` 阶段比对，而 `submit` 走 `execute_deployment` 的复验，因此不构成执行绕过的缺口；但其**响应本身**在窗口内同样可能陈旧，是否需要对这两个只读响应也加复验属 `deployment_preview.py`（本轮只读）的后续决定。
- **复验字段集之外的可变字段**：`SNAPSHOT_FIELDS` 不含 `attestation`（digest 覆盖它，但不属于 `registered_subject`）。已用一个专门用例证明这类漂移仍由 `preview_digest` 失败关闭（409 `deployment_preview_changed`）；未扩展复验字段集（会改动只读的 `binding_identity.py`）。
- **带外变更的范围**：`asset_id`/`agent_instance_id` 的改指与实例来源改指在本次复现中是带外提交，不声称存在合法 API；`revoke`、`attestation` 类变更则确有合法入口。
- 未处理：保留/删除治理、完整共享影响、运行时占用发现、执行授权闭环（仍属 CL-04/CL-05 后续）。

## 7. 状态

CL-04-IMPACT-SNAPSHOT-CLOSEOUT：机制核对完成、缺陷复现完成、最小修复完成、定向验证完成。**未提交、未推送、未部署**，待主开发者复核。仅声明该子项完成，不关闭 CL-04，也不声明整体项目完成。未触碰其他开发线（Kimi/GLM/Qwen/主开发者）的文件。

## 8. 主开发者验收与证据修正（2026-09-26）

产品修复位置正确，无需追加产品代码修改。主开发者补充 impact v1 合同的实现保证与事务可见性边界，没有改变 wire、摘要算法或执行授权。

发现并修复一处测试归因问题：`agent_owner` 实际拥有 `agent:read`，原新增权限测试的 403 不能证明缺少此权限被拒。现使用测试内临时角色，保留 `policy:manage/policy:read/env:read`，仅缺 `agent:read`，仍核对 403 与零后端探测；不修改生产权限映射。原测试文件同类负例也保持不变。

证据澄清：attestation 用例是在 impact 请求开始前提交变化，只证明下次预览摘要能够识别该变化；不能推导为“probe 期间的全部非复验字段漂移也被阻断”。当前修复只覆盖登记身份字段及来源关联。ORM 对象不是语言层面常量，只是在本复现场景下持有旧值。历史 `test_policy_flow.py` 顺序污染已在独立子任务验收修复，不再列作当前未解决阻断。

定向验收命令：

```bash
cd apps/control-api
uv run --no-sync pytest -o addopts='' -q app/tests/test_deployment_impact_consistency.py \
  app/tests/test_deployment_impact.py app/tests/test_binding_execution_recheck.py \
  app/tests/test_binding_source_identity.py app/tests/test_deployment_preview.py \
  app/tests/test_deployment_submission.py --tb=short
uv run --no-sync ruff check app/routers/deployment_impact.py app/tests/test_deployment_impact_consistency.py
```

权限负例修正后，上述合并回归 **70 passed**（11.63s），仅 1 条既有 Starlette/httpx 弃用警告；Ruff、git diff --check 与目标文件尾随空白检查通过。

本次仍是 SQLite/TestClient/模拟后端证据，不证明真实 PostgreSQL/OpenShell 并发行为。未提交、未部署，仅接受本登记身份一致性子项，不关闭 CL-04。
