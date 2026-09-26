# ENT-019-AUDIT-WIRE 交付记录：审计精确查询前后端真实响应契约验收

日期：2026-09-25
范围声明：本记录只覆盖总任务书（docs/development/enterprise-auto-onboarding-taskbook-20260925.md）ENT-019 的 **ENT-019-AUDIT-WIRE 子任务**——用隔离后端测试导出真实 HTTP 响应样本，再由前端现有客户端代码消费验证。不代表 ENT-019 整体、审计全链路或项目整体已完成；本验证不证明真实 IAM、网关、PostgreSQL 或部署环境已验收。

## 1. 实际新增文件（未修改任何已有文件）

| 文件 | 说明 |
| --- | --- |
| `apps/control-api/app/tests/test_audit_query_wire.py` | 后端：隔离 TestClient 实际执行 GET /api/v1/audit-events，断言 A–J 场景并导出真实响应样本 |
| `apps/web/dev/audit-query-wire.config.ts` | 前端：独立 Vitest 配置（只包含本检查，不并入标准 glob，不改依赖） |
| `apps/web/dev/audit-query-wire.check.ts` | 前端：消费者契约检查，走真实 `getListPage`（client.ts）与 `parseListMeta`（listMeta.ts），fetch 层原样回放样本 |
| `scripts/enterprise-experience/audit-query-wire-check.py` | 一键验收：建独立证据目录 → 后端导出 → 校验样本 + SHA-256 → 前端消费 → 汇总报告 |
| `docs/development/enterprise-audit-query-wire-handoff.md` | 本交付记录 |

开始前已逐一确认这五个文件不存在，无他人成果被覆盖。未触碰：`apps/web/src/components/audit-search/`（其他开发线在途）、`AuditPage.tsx`、RuntimeBindingsPage 相关文件、共享客户端/hook/CSS、后端路由/模型/schema/conftest、任务书与台账、package.json 与锁文件。

## 2. 验证路径：真实后端响应 → 前端现有消费者

```text
apps/control-api 隔离 TestClient + 测试 SQLite（SIQ_AS_DEV 合成身份，conftest 既有机制）
  → 实际 GET /api/v1/audit-events（断言通过）
  → 原样导出 {status, content-type + X-SIQ-List-* 头, body, 查询参数, 夹具预期 ID}
  → SIQ_AUDIT_QUERY_WIRE_OUTPUT 独占创建（open 'x'）写出样本
  → apps/web vitest 独立配置：vi.stubGlobal('fetch') 受控拦截
  → 真实 client.ts buildUrl（URL.searchParams 编码）+ 信封/错误处理 + listMeta.parseListMeta
  → 断言解码值、分页元数据、错误状态与夹具预期
```

前端检查不 mock 客户端模块、不重新实现“兼容客户端”、不手写响应夹具；样本不经过任何转换或删减。样本中不含身份头、Cookie、环境变量或真实身份；导出内容仅合成数据 + 响应协议字段 + 来源标记 `isolated-testclient-synthetic-data`。

## 3. 场景与断言覆盖

后端（`test_audit_query_wire.py`，2 个测试：场景断言 + 显式导出）：

- A 新旧七条件 AND 组合（7 条诱饵各破坏一个条件，断言仅全匹配命中，total=1）；
- B/C 相同时间戳 7 条记录 limit=2 共 4 页：合并顺序 == 夹具 ID 排序（`(created_at desc, id asc)`）、无重复、无遗漏、returned 2/2/2/1、每页 total 恒为 7（不随翻页递减）、truncated 链路正确；
- D 无匹配：空数组 + `X-SIQ-List-Total: 0`（0 是明确值）；
- E 两租户同名 request_id/resource_id：各自只命中本租户 1 条、total 各为 1；
- F viewer（无 audit:read）带过滤参数 → 403；
- G 四个新参数空字符串逐一 → 422；
- H 四个新参数超长（65/65/17/17）逐一 → 422；
- I 未知 `actor_type=automaton-x` / `decision=quarantine` 精确可查、响应原值不改写；
- J 含空格/`&`/`+`/引号/中文且带尾随空格的 request_id 原值命中；strip().lower() 变体不命中（证明不 trim、不改大小写）；
- 只读：夹具初始化后，全部 GET（含 403/422）前后 AuditEvent/OutboxEvent/AgentAsset 行数快照相等，并回读三条关键记录的 request_id/decision/actor_type/summary 字段未变。

前端消费者（`audit-query-wire.check.ts`，11 项）对应任务第五节 12 条：逐字编码（含特殊字符往返）、无 tenant_id/租户覆盖参数（白名单核对）、翻页携带全部已应用条件且 cursor 取自上一次真实解析的响应头、include_total/cursor/limit 协议、total=0 非缺失、四页合并 ID 与顺序等于夹具预期、403/422 保留为 ApiError 错误状态、未知原值不改写（items 与样本 body 全等）、全程只发 GET（非 GET 或未预期请求记入 violations 并立即失败）、Proxy 化的 localStorage/sessionStorage 访问即抛错、afterEach 恢复 fetch 与替身。

## 4. 实际命令与结果

```bash
# 后端聚焦（未设输出环境变量 → 普通运行不导出）
cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run pytest -o addopts='' -q app/tests/test_audit_query_wire.py app/tests/test_audit_exact_filters.py --tb=short
# 21 passed, 1 warning（既有 Starlette/httpx 弃用 warning），2.74s

uv run ruff check app/tests/test_audit_query_wire.py
# All checks passed!

uv run ruff check ../../scripts/enterprise-experience/audit-query-wire-check.py
# All checks passed!

# 后端全量回归（含本文件 2 个新测试；默认 addopts 为 -q，勿再叠加 -q 以免丢汇总行）
uv run pytest --tb=short
# 1693 passed, 1 skipped（既有 SIQ_BATCH_WIRE_SAMPLE 未提供时的固定跳过）, 0 failed, exit 0, 96.25s

# 前端消费者（对本次导出样本）
cd /home/maoyd/siq/siq-agent-security/apps/web
SIQ_AUDIT_QUERY_WIRE_OUTPUT=<样本路径> ./node_modules/.bin/vitest run --config dev/audit-query-wire.config.ts
# Test Files 1 passed (1)，Tests 11 passed (11)

# 前端全量（本任务未向标准 glob 新增文件；check.ts 不在 include 内）
npm test
# Test Files 1 failed | 93 passed (94)；Tests 4 failed | 720 passed (724)
# 4 个失败全部在 src/pages/RuntimeBindingsPage.test.tsx（另一开发线在途，本任务禁止介入）；
# 本任务开始前基线（22:02）为 719 passed / 5 failed 同一文件——该开发线正在活跃修改，计数随其改动变化。

# 标准前端构建（独立临时目录）
npm run build -- --outDir /tmp/siq-audit-wire-build-U4Za/out
# exit 1：7 个 TS 错误，全部位于他人「运行时绑定」在途文件——
#   src/pages/RuntimeBindingsPage.tsx(29,3) TS6133 ×1
#   src/pages/RuntimeBindingsPage.test.tsx TS6133 ×1、TS2554 ×5（行 366/447/448/479/480/504）
# 按任务要求不替他人修复、不删测试、不用替代配置掩盖；本任务文件均不在 tsc 标准构建范围（tsconfig include 仅 src）。
# 标准构建当前被该开发线阻断，特此记录，不宣称标准构建通过。

# 本任务前端文件的严格类型自检（/tmp 一次性配置，非构建替代品）
npx tsc -p /tmp/tsconfig.audit-wire-check.json
# 通过（覆盖 check.ts 及其真实依赖链 client.ts/listMeta.ts/protocol.ts/types.ts）

# 独占创建行为验证：同一路径第二次导出必须失败
SIQ_AUDIT_QUERY_WIRE_OUTPUT=<同一路径> uv run pytest -o addopts='' -q app/tests/test_audit_query_wire.py::test_export_audit_query_wire_sample
# 第一次 1 passed；第二次 1 failed（FileExistsError，写入失败即测试失败）

# 一键验收（前后端共用同一份本次生成样本）
python3 scripts/enterprise-experience/audit-query-wire-check.py
# exit 0；backend-pytest exit 0（2 passed）、frontend-vitest exit 0（11 passed）

git diff --check   # 通过；四个新源码文件另经尾随空白/Tab/CR 检查均干净
```

## 5. 样本与证据

- 证据目录：`/tmp/siq-audit-query-wire-wrmfdsub/`（`report.json`、`backend-pytest.log`、`frontend-vitest.log`、`audit-query-wire-sample.json`）
- 样本 SHA-256：`1b46d3dff25c56103cb87738509350cb74490cd1b560ba8c57176525b9007e48`
- 样本来源标记：`isolated-testclient-synthetic-data`；合成记录前缀 `ent019-wire`
- 脚本每次运行创建新的 `siq-audit-query-wire-*` 临时目录（或要求 `--out-dir` 指向尚不存在的目录），不删除他人临时目录、不覆盖已有证据；/tmp 可能被系统清理，复跑直接重新执行脚本生成新样本即可。

## 6. 隔离与只读证据

- 租户隔离：同名 `request_id`/`resource_id` 下，tnt-A / tnt-B 各自响应只含本租户夹具记录（total 各为 1），且两租户预期 ID 不同；后端断言 + 前端消费双重验证。
- 权限：viewer 无 `audit:read` → 403 样本在前端被保留为 ApiError(403)，不会变成成功空列表。
- 只读：查询前后三张表行数相等 + 关键行字段回读未变（不止凭“用了 GET”）。
- 无真实网络/存储：前端 fetch 全部被 stub 接管（非 GET、队列外请求立即失败）；localStorage/sessionStorage 为访问即抛错的 Proxy；测试结束恢复全部替身（最后一项断言 fetch 已非 mock）。
- 无真实数据库/服务：后端为 conftest 既有隔离 SQLite + dev 合成身份头。

## 7. 已知限制与范围外问题

- 本验收是“真实后端响应样本的消费者契约验证”，不是部署环境网络联调；不证明生产 IAM、网关、PostgreSQL。
- 标准前端构建当前被另一开发线的 RuntimeBindingsPage 在途修改阻断（第 4 节），与本任务文件无关；待其修复后可直接复跑标准构建，本任务文件不影响 tsc（dev/ 不在 tsconfig include 内）。
- `npm test` 中同文件 4 项失败同样属该开发线在途状态，本任务未介入。
- 既有 cursor 宽松行为（畸形 cursor 回退 `id > cursor`）属既有兼容行为，见 enterprise-audit-query-handoff.md 第 7 节，本任务未改动。
- 样本导出到 /tmp，属易失存储；如需长期证据，重新运行一键脚本生成新样本（独占创建拒绝覆盖）。

## 8. 状态

未提交、未推送、未部署，待主开发者复核。仅声明 ENT-019-AUDIT-WIRE 子任务完成；不宣称 ENT-019、完整审计链路或项目整体完成。

## 9. 主开发者复核（2026-09-25）

已检查五个实际文件，核心样本来源、产品客户端消费、独占导出和失败退出逻辑符合本子任务。发现并复现脚本相对 `--out-dir evidence` 路径缺陷：子进程切换 cwd 后无法找到导出目录，后端 1 failed / 1 passed，脚本正确返回非零。修复为在调用者目录中将指定输出路径 resolve 为绝对路径，不改变禁止覆盖行为。

修复后从独立临时目录使用相对输出参数重跑：后端 2 passed（1.94 秒）、消费者 11 passed，一键脚本 exit 0。再次指定同一目录 exit 2，拒绝覆盖。新证据目录 `/tmp/siq-audit-review-fixed-lSZQGn/evidence/`，样本 SHA-256 `27abf20054e1047d1a9a8faf4d64e7ba32d9f228e3eba641ff286a23f1f462c9`。Ruff 与 diff 检查通过。

本次复核没有重跑后端全量或宣称前端标准构建通过；生产 IAM/网关/PostgreSQL 仍在证明范围之外。任务可按“隔离契约验收子任务已复核（含上述修复）”接收，仍未提交、未部署。聊天摘要中省略或拼接的路径以本文实际五文件路径为准。
