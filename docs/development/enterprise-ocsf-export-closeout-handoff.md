# 既有 OCSF 导出收口交接（CL-06-OCSF-EXPORT-CLOSEOUT）

日期：2026-09-26
状态：子任务完成（**未提交、未推送、未部署，待主开发者复核**）
范围：`GET /api/v1/export/ocsf` 的租户隔离、权限、导出审计、失败关闭与稳定输出收口。
本轮仅声明既有 OCSF 导出子项完成；**不宣称 CL-06（完整审计链与保留/导出治理）或整体项目完成**。

---

## 1. 实际修改 / 新增文件

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `apps/control-api/app/routers/export.py` | 修改（+17 / −6） | 只改 `_parse_since`（新增 OverflowError 受控拒绝）与成功响应的 `Cache-Control: no-store`；模块不变量注释同步。查询、租户限定、权限依赖、审计写入、排序、limit、媒体类型、正文均未改 |
| `apps/control-api/app/tests/test_ocsf_export_closeout.py` | 新增 | 440 行，13 个测试函数 / 19 个用例（含 6 项参数化拒绝路径、2 项参数化极端日期） |
| `docs/development/enterprise-ocsf-export-closeout-handoff.md` | 新增 | 本文件 |

未修改其他文件：`app/ocsf.py`、`app/tests/test_ocsf_export.py`、`app/outbox.py`、`app/security.py`、`models.py`、`schemas.py`、迁移、共享审计/权限依赖、其他路由、前端、Edge、Connector、安装器、依赖与锁文件、公共台账均只读。
`git status` 中其他开发线的既有改动（GLM 部署测试隔离、Qwen 前端审计、主开发者 Edge 主线、上两轮 drift 改动）未被触碰。

## 2. 已有测试覆盖与本轮增量（不重复造边界测试）

`test_ocsf_export.py` 已覆盖：映射纯函数（severity/status/time/confidence/structure/resource fallback/API Activity/disposition）、基础 NDJSON 两类导出、基础租户隔离（不同 rule_id）、无 `audit:read` 403、非法 class/缺 class 422、since 过滤与非法 since 422、limit 计数与 2001 上限 422、导出审计写入与摘要键集。

本轮新增文件只补上述未覆盖的收口面：同标识同时间戳的严格隔离（集合相等）、拒绝路径"不写成功导出审计"的逐项证明、since 时区换算与包含边界、极端非法日期受控拒绝、NDJSON 字节级行完整性与空结果、顺序 + limit 独立对照、审计/提交失败的失败关闭、审计摘要 canary、no-store、只读性与响应自排除。

## 3. 逐项核对结论（真实缺陷 / 复现 / 可达性 / 修复）

复现方法（可逆、未清理工作树）：新测试文件先在 **HEAD 版 `export.py`** 上运行，再在修复版上运行；HEAD 文件与修复前逐字节一致（`git diff` 只含本轮 +17/−6），跑完用 `cmp` 校验还原一致。全部为合成 SQLite + dev 身份头，**不是生产环境证据**。

| # | 检查项 | 结论 | 复现与证据 |
| --- | --- | --- | --- |
| 1 | 不同租户同名标识/相同时间戳是否严格隔离 | **不是缺陷** | 两租户各写入同名 `rule_id="clo-same-rule"`、同时间戳的 Finding 与同名同时间戳的审计动作，两端导出用集合相等断言：A 只看得到 `{a1,a2}`，B 只看得到 `{b1}`；`api_activity` 同理。租户条件来自 `identity.tenant_id`（`model.tenant_id == identity.tenant_id`），无跨租户读取 |
| 2 | 无权限与无效参数是否在导出前拒绝、且不生成成功导出审计 | **不是缺陷** | 参数化 6 条路径（非法 class / 缺 class / 非法 since / limit=2001 / limit=0 / 无 `audit:read` 403）：状态码分别为 422/422/422/422/422/403，响应体无 `"class_uid"`，且该租户 `export.ocsf` 审计条数不变。依赖顺序保证 403 在端点体之前，参数校验在查询与审计之前 |
| 3 | since 合法时区换算与极端非法日期 | **是真缺陷（已修）** | 非法输入本身已受控（`not-a-date`/空串/尾随空格/`2024-13-01`/`now` → 422 `invalid_since`，不回显输入）。但**极端显式偏移在时区换算时越过 `datetime` 上下限**：`since=9999-12-31T23:59:59-14:00`（以及百分号编码的 `0001-01-01T00:00:00%2B14:00`）触发未捕获的 `OverflowError` → **HTTP 500**。可达性：任何持有 `audit:read` 的调用方用一个合法形状的查询串即可触发，属"非法输入未被受控拒绝"；不涉及跨租户或写操作。修复：`_parse_since` 把 `astimezone` 纳入同一个 `try` 并捕获 `(ValueError, OverflowError)` → 422 `invalid_since`；**未放宽解析**，也未新增"修正"逻辑。修复前后对其它 10 个样例（含 `2024-06-01`、`20240601`、`2024-W23-1`、`+02:00`、`+15:00`）的接受集与归一值逐一比对完全一致 |
| 4 | NDJSON 每行可独立解析、空结果、中文/换行、顺序稳定、limit 生效 | **不是缺陷** | 正文字段含 `\n`、`\r\n`、引号、中文时：按字节以 `\n` 切分仍只有 1 行，`json.loads` 可解析，`impact`/`remediation` 往返一致（`json.dumps` 已转义控制字符，`ensure_ascii=False` 保留中文）。空结果 → 200 + 空 body + 仍写 `count=0` 审计。顺序 = (时间升序, id 升序)，期望值由测试自己排序种子得出；`limit=2` 取该顺序前 2 条 |
| 5 | 审计/提交失败时客户端不得拿到 200 导出内容、状态与审计回滚 | **不是缺陷** | 注入审计写入异常 → 500，响应无 `"class_uid"`、无 canary，`export.ocsf` 审计与 outbox 均无新增；注入提交异常（合成）→ 500、无正文、审计未落库。端点先 `audit()` 后 `session.commit()` 再返回 `Response`，提交失败时异常先于响应产生；`get_session` 只 close，未提交的事务随连接回滚 |
| 6 | 审计 summary 只保留既有受控元信息 | **不是缺陷** | 导出审计 summary 键集恰为 `{class,count,since}`；把 canary 写进 Finding 正文（`impact`/`remediation`/`rule_id`）后，正文按设计含 canary，而导出审计摘要 JSON 中不含 canary。`since` 记录的是请求方原始输入，但其取值被解析器限制为可解析的日期形态 |
| 7 | 敏感导出的缓存控制 | **是真缺陷（已修）** | 修复前 200 响应**没有** `Cache-Control`（探针实测 header 缺失；应用层无全局 no-store 中间件，`request_id_middleware` 只写请求 ID 头）。可达性：任何中间缓存/代理/浏览器可缓存含 Finding 与审计内容的 NDJSON。修复：成功响应加 `Cache-Control: no-store`，媒体类型（`application/x-ndjson`）与正文未变 |
| 8 | 路由安全问题 vs OCSF 映射合同问题 | 见 §5 | 本轮未发现"导出路由"层面的其他安全缺陷；映射侧的若干保真度/边界观察只记录，`ocsf.py` 只读，未删字段、未改公共 schema |

修复前基线（新测试文件 + HEAD 版 `export.py`）：**3 failed / 16 passed** —— 失败项恰为上述两处：`test_extreme_since_is_controlled_rejection[两例]`、`test_sensitive_export_is_not_cacheable_and_media_type_unchanged`。
修复后：**19 passed**。

## 4. 实际执行的验证命令与结果

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api

# 1) 新增收口用例（修复后）
uv run --no-sync pytest -o addopts='' -q app/tests/test_ocsf_export_closeout.py
#    结果：19 passed
# 2) 原导出测试（未改动，确认无回归）
uv run --no-sync pytest -o addopts='' -q app/tests/test_ocsf_export.py
#    结果：16 passed
# 3) 基线：临时换回 HEAD 版 export.py（跑完 cmp 校验还原一致）
#    结果：3 failed / 16 passed（失败项见 §3）
# 4) 直接受影响的审计/关联回归（导出审计走同一 outbox 写入，且新响应经同一 request_id 中间件）
uv run --no-sync pytest -o addopts='' -q app/tests/test_ocsf_export.py app/tests/test_ocsf_export_closeout.py \
  app/tests/test_request_id.py app/tests/test_audit_outbox.py
#    结果：45 passed
# 5) 静态与格式
uv run --no-sync ruff check app/routers/export.py app/tests/test_ocsf_export_closeout.py   # All checks passed!
cd /home/maoyd/siq/siq-agent-security && git diff --check -- apps/control-api/app/routers/export.py   # 无输出
grep -nP "[ \t]+$" apps/control-api/app/routers/export.py apps/control-api/app/tests/test_ocsf_export_closeout.py  # 无匹配
```

未跑后端/前端/Go 全量，未连接真实数据库或控制面，未安装依赖。失败注入用例使用 `raise_server_exceptions=False` 的客户端观察**真实 HTTP 状态**（500 呈现为 500），断言显式的 4xx/5xx；没有把测试客户端抛出的异常当成验收成功的负例。

## 5. 记录但不修改的边界（映射/解析侧，`ocsf.py` 只读）

- **`finding_info.types` 用 `domain` 原值**（`policy`/`threat`）：OCSF 的 `finding_info.types` 期望类型名列表，这里的取值是内部分类名。属映射保真度问题，不是路由安全问题；改它需要改 `ocsf.py` 与可能消费该字段的下游，本轮只记录。
- **U+2028 / U+2029（行分隔符 / 段分隔符）不被 `json.dumps` 转义**：它们出现在正文（如 `impact`）时仍合法地留在 JSON 字符串内，按字节以 `\n` 切分的 NDJSON 不受影响（本轮已按字节级断言）。注意：用 Python `str.splitlines()` 之类按 Unicode 行边界切分的消费者会在该字符处多切一行——这是消费方实现问题，本轮不改变导出字节。
- **`since` 原样回显进导出审计摘要**：取值受解析器限制（仅日期形态字符串），不含导出正文或 canary；若未来要求审计只存归一化 UTC，会改变既有审计摘要语义，需另行决策。
- **Python `fromisoformat` 接受超出 ISO 8601 的偏移**（如 `+15:00`）并正常归一：本轮未收紧（收紧会改变既有解析合同，且不属安全缺陷），只记录。
- **已入库的审计摘要原样透传**：`audit_to_ocsf` 把 `event.summary` 放入 `unmapped.summary`，依据是"入库前已脱敏"（outbox 约定）。若历史库中存在未脱敏摘要，导出会将其呈现给**同租户**的 `audit:read` 持有者；本轮不新增过滤（会改变导出内容契约）。
- **`count` 是本次导出条数（≤ limit）**：导出审计没有"是否被 limit 截断"字段，本轮未新增（新增字段会改变既有审计摘要契约）。

## 6. 未解决边界（明确不做声明）

- **成功导出审计不证明用户已经完整下载**：审计只证明服务端完成了一次查询并在同一事务内提交了该次导出动作；断连、客户端中断、正文被丢弃都不体现在审计里。
- **受 limit 限制的导出不等于完整审计归档**：默认 500、上限 2000，`count` 只是本次导出条数；`export.ocsf` 审计不能当作"已导出全部历史"的证据。
- **保留/删除治理未解决**：本轮不涉及保留期限、删除对象、合规保留规则，也没有可删除或清理任何历史记录的入口；`GET /api/v1/export/ocsf` 只读且不改业务状态（已断言 `status`/`severity`/`last_seen_at` 等不变，且不写 outbox）。
- **未验证真实环境**：未验证真实反向代理/浏览器缓存行为（只断言响应头）、未验证真实 PostgreSQL 下的行为（合成 SQLite）、未做并发导出压测。
- 未新增导出产品、删除/保留周期、后台导出任务、权限枚举、路由或数据模型；未加自动重试；未把异常吞掉返回空列表。

## 7. 交付状态

- 未提交、未推送、未创建分支/PR、未部署；未改治理或台账文件；其他开发线文件未被触碰。
- **待主开发者复核点**：①新增 `Cache-Control: no-store` 是否只应出现在本端点（其他敏感 GET 端点是否也需要，属其他子任务范围）；②极端 since 统一按 `invalid_since` 422 处理（而非区分"溢出"原因码）是否接受；③§5 中映射侧观察是否需要单开子任务。
- **仅完成既有 OCSF 导出子项收口，未提交、未部署，待主开发者复核；不代表 CL-06（完整审计链与保留/导出治理）或整体项目完成。**

## 8. 主开发者验收（2026-09-26）

本子项通过定向验收。接受极端日期统一返回既有 `422 invalid_since`，不增加错误枚举；接受本端点成功响应的 `Cache-Control: no-store`，不扩展到全站中间件。缓存头是遵循 HTTP 缓存规则的控制信号，不声称能阻止客户端主动保存或违规代理存储，也不追溯清除历史缓存。两个 class 共用该响应路径。

本次未追加产品代码修复；补强 `test_commit_failure_delivers_no_content_and_persists_no_audit`：原替身在 commit 前直接抛错，现先执行真实 flush，在请求事务内确认一条新导出审计确实可见，再抛合成异常。通过独立会话确认审计无残留、outbox 数量不变，并确认失败响应不带导出正文。证明的是提交前失败的事务回滚，不证明数据库已提交但响应丢失的情形。

独立重跑（补强后）：

```bash
cd apps/control-api
uv run --no-sync pytest -o addopts='' -q app/tests/test_ocsf_export.py \
  app/tests/test_ocsf_export_closeout.py app/tests/test_request_id.py \
  app/tests/test_audit_outbox.py --tb=short
# 45 passed；1 条既有 Starlette/httpx 弃用警告
uv run --no-sync ruff check app/routers/export.py app/tests/test_ocsf_export_closeout.py
```

第五节的映射观察暂不另开开发任务：其中关于外部 OCSF/ISO 标准符合性的判断未在本次独立核验，不能作为已确认缺陷；其余限制继续保留。导出已有审计摘要不等于导出时再次脱敏，且该 GET 会新增导出审计，不是零数据库写入。未验证真实代理、PostgreSQL 或客户端下载完成。

仅修改此交接记录及本子项新增测试，原导出测试和其他开发线文件未动。未提交、未推送、未部署；仅关闭本次既有导出安全子项，不关闭 CL-06 整体。
