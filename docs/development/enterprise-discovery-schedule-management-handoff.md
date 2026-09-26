# 交付记录：企业端周期发现计划可视化查看与撤销闭环（CL-02-SCHEDULE-MANAGEMENT）

任务书：`docs/development/cl02-glm-schedule-management-taskbook.md`
状态：**本子任务完成，未提交、未推送、未部署，待主开发者复核。** 不声明 CL-02 或整体项目完成。

## 1. 交付内容概览

在既有周期计划确认（POST）路由上新增租户隔离的只读分页查询（GET），在企业端环境页面挂载独立管理面板，并接通既有撤销 POST，形成"查看 → 评估权限 → 撤销（含 revision 冲突、审计）"闭环。既有确认合同、调度器、设备协议全部未改动。

## 2. 实际改动文件

### 新增
| 文件 | 内容 |
| --- | --- |
| `packages/contracts/enterprise-discovery-schedule-management.v1.md` | GET 只读查询合同：端点、权限、分页、11 字段白名单、排除项、消费边界 |
| `apps/web/src/api/discoveryScheduleManagement.ts` | 前端 API 客户端：严格解析（精确键校验、回显检查、传输前 ID 正则校验、拒绝继承字段）+ 撤销调用 |
| `apps/web/src/api/discoveryScheduleManagement.test.ts` | 客户端解析与调用测试（36 个 Vitest 的一部分） |
| `apps/web/src/components/discovery-schedule-management/dsmState.ts` | 面板状态机 reducer：加载/分页/撤销全流程、票据隔离、409/403/未知结果文案 |
| `apps/web/src/components/discovery-schedule-management/dsmState.test.ts` | reducer 测试（迟到的成功被忽略、分页失败保留数据并可同 cursor 重试、双击防抖、取消零写入等） |
| `apps/web/src/components/discovery-schedule-management/DiscoverySchedulePanel.tsx` | 面板组件：权限门控、展开才拉取、无后台轮询、撤销 ConfirmDialog |
| `apps/web/src/components/discovery-schedule-management/DiscoverySchedulePanel.test.tsx` | 组件门控测试（renderToStaticMarkup，node 环境无 jsdom） |
| `apps/web/src/components/discovery-schedule-management/discovery-schedule-management.css` | 面板样式：仅 `dsm-*` 前缀类，复用项目 CSS 变量，375px 断点、focus-visible |
| `apps/control-api/app/tests/test_discovery_schedule_management.py`（追加段） | 见 §3；该文件原有 117 行 POST 测试逐字节保留，我在其后追加 GET 测试段并标注分界注释 |
| `scripts/enterprise-experience/discovery-schedule-management-browser-smoke.py` | 隔离浏览器冒烟（Playwright + 本地 fixture 服务 + 路由拦截），见 §6 |

### 修改
| 文件 | 改动 |
| --- | --- |
| `apps/control-api/app/routers/discovery_schedules.py` | 仅追加：`_utc_z`、`management_item`、`list_schedules`（GET）。原有两个 POST 端点及其共享的 `_env_or_404`/`lock_tenant` 等未改一行 |
| `apps/web/src/pages/EnvironmentsPage.tsx` | 仅 2 行：import + 在 `<DeviceLifecyclePanel>` 之后挂载 `<DiscoverySchedulePanel environmentId={selected.id} />`。保留了并行开发者的其他改动 |

### 未触碰（按任务书与 AGENTS.md 约束）
`discovery_scheduler.py` 及其测试、`models.py`、数据库迁移、Edge/Connector、`App.tsx`、个人端、`onboarding/**`、共享 CSS、共享 client/hook、权限模型、依赖/锁文件、README、公共台账。已运行确认合同与 tick 相关测试证明 POST 行为未变。

## 3. 后端：只读分页查询

`GET /api/v1/environments/{environment_id}/discovery-schedules`

- **租户与权限**：tenant 仅来自已验证身份；`_env_or_404(session, identity.tenant_id, environment_id)` 先按租户定位环境（跨租户/不存在统一 404），再 `ensure_permission(identity, "env:read")`（无权限 403）。查询额外按 `tenant_id + environment_id` 双过滤。
- **分页**：cursor 形如 `^eds-[a-f0-9]{32}$`（非法 422）；limit 默认 20、范围 1..100（越界 422）；按计划 ID 升序；取 limit+1 判断是否还有下一页；`next_cursor` 为本页最后一条的 ID，空页为 `null`。响应头 `Cache-Control: no-store`。
- **顶层字段（精确 6 个）**：`schema_version`（`enterprise-discovery-schedule-management/v1`）、`environment_id`（回显）、`evaluated_at`（服务端评估时刻 UTC Z）、`can_revoke`、`items`、`next_cursor`。
- **can_revoke**：`has_permission("env:manage") AND has_permission("edge:manage")`。仅是 UI 提示，永不替代撤销 POST 的实时鉴权。
- **条目白名单（精确 11 字段）**：`schedule_id, edge_agent_id, status, revision, starts_at, expires_at, interval_seconds, max_runs, reserved_runs, last_reserved_slot, created_at`。不返回 installation_plan/intent 原文、根目录、签名、凭据、tenant_id，不做 ORM 行序列化。naive-UTC 列经 `_utc_z` 转为 UTC Z 字符串，不改写时钟或状态。
- **无副作用**：GET 不写审计、不发 outbox、不 reserve、不 tick、不加锁（测试 `test_list_changes_no_state` 断言 5 张表计数不变）。
- **status 语义**：仅 `pending_confirmation / active / paused / revoked`。文档与 UI 明确：active ≠ 设备在线、≠ 采集成功、≠ 防护生效；`reserved_runs` 是已预约轮次而非成功扫描次数；窗口事实仅在 `evaluated_at` 时刻成立；`max_runs − reserved_runs` 为未预约预算，实际调度仍受期限与其他门禁约束。

## 4. 撤销闭环

- 面板仅对 `can_revoke && status !== 'revoked'` 的记录显示撤销按钮（`pending_confirmation` 也可撤销，任务书只禁止对已撤销记录）。
- 确认对话框（复用共享 `ConfirmDialog`：Escape 关闭、焦点圈、portal、busy 期间不可关闭），描述含计划 ID/设备/revision 及边界提示：确认后停止该计划**后续调度**，不保证已派发任务被取消，不撤销智能体业务权限。
- 请求体严格 `{expected_revision}`，走既有 POST 撤销端点：实时鉴权、revision 冲突（409）、审计均由既有代码承担，未修改。
- 结果处理：409 → 提示刷新后重试，**不自动用新版本重试**；403 → 明示无权限，**不伪装成功**；网络错误/5xx → 声明结果未知，**不自动重发**；成功必须匹配 `schedule_id` 且 `status === 'revoked'` 才算成功。成功后从第一页整体刷新（无乐观删除）；取消 = 零写入。
- 组件内 pending ref + busy 状态双重防双击。

## 5. 前端面板与隔离

- 挂载于 `EnvironmentsPage` 选中环境详情区，复用项目视觉（CSS 变量、卡片风格），支持桌面、375px（行内标签改为上下堆叠断点）与键盘操作（可聚焦按钮、focus-visible、冒烟含键盘 Enter 路径）。
- 权限门控：`useConsoleContext()` 未 ready 或无 `access.environments` 时渲染 null，不发任何请求。
- 拉取时机：仅在展开（`aria-expanded` 切换）时加载第一页；无后台轮询；"加载更多"用 `next_cursor` 追加，"只读刷新"从第一页替换。
- 并发隔离：组件级 generation 票据，所有 reducer 动作带显式 ticket，迟到响应被 reducer 忽略；身份/环境变化以 key 重挂载（`${tenant.id}:${actor.type}:${actor.id}:${environmentId}`）。

## 6. 定向验证（实际执行命令与真实结果）

工作树：`/home/maoyd/siq/siq-agent-security`。所有命令均在其中执行。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `apps/control-api/.venv/bin/python -m pytest apps/control-api/app/tests/test_discovery_schedule_management.py apps/control-api/app/tests/test_discovery_scheduler.py` | **41 passed**（含既有 POST/确认合同/tick 测试，证明 POST 未被改动） |
| 2 | `cd apps/web && npx vitest run`（`src/api/discoveryScheduleManagement.test.ts`、`dsmState.test.ts`、`DiscoverySchedulePanel.test.tsx`） | **36 passed** |
| 3 | `cd apps/web && npx tsc -b` | 通过，无错误 |
| 4 | `cd apps/web && npx vite build`（正式 `VITE_DEV_MODE=false`） | 构建成功（产物在 /tmp 临时目录，仅用于验证，未部署） |
| 5 | `VITE_DEV_MODE=true npx vite build`（模拟构建，仅冒烟用） | 构建成功；产物目录名即标注 **SIMULATED-NOT-RELEASABLE，不可发布** |
| 6 | `/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/discovery-schedule-management-browser-smoke.py --web <模拟构建目录> --out-dir /tmp/siq-dsm-smoke-final2` | **passed: true，13/13 checks**（Ruff 修复后复跑） |
| 7 | `apps/control-api/.venv/bin/python -m ruff check`（3 个新增/改动 Python 文件） | All checks passed（修复 2×SIM905、chmod +x 解决 EXE001 后复跑通过） |
| 8 | `git diff --check` | 干净（exit 0） |

### 浏览器冒烟覆盖（13 项，全部为真实浏览器执行）
只读阶段零写入与状态标签、已撤销行无撤销按钮、撤销成功（精确断言请求路径与 `{expected_revision: 0}` 载荷并触发刷新）、409 提示刷新不自动重试（恰好 1 次撤销 POST）、403 不伪装成功、未知结果不自动重发（恰好 1 次）、无 `env:read` 权限渲染空且零请求、分页"加载更多"、键盘操作、桌面与 375px 无横向溢出、无未捕获页面错误。

### 产物位置（/tmp 临时目录，未入库、未部署）
- 截图：`/tmp/siq-dsm-smoke-final2/desktop.png`、`/tmp/siq-dsm-smoke-final2/mobile.png`（任务书要求"实际查看"——已查看：桌面版三条记录完整渲染，含状态标签、active 免责声明、预算说明；移动版正确堆叠、无溢出）
- 结果 JSON：`/tmp/siq-dsm-smoke-final2/result.json`（含 `build_mode`、`production_deployed: false`）

## 7. 源码证据与模拟证据的区分

- **真实源码验证**：pytest（真实 FastAPI TestClient + SQLite，覆盖 404/403/分页/校验/权限组合/白名单泄漏断言/无副作用/撤销反映）、Vitest、tsc、正式构建。
- **模拟证据（非生产验证）**：浏览器冒烟运行在 `VITE_DEV_MODE=true` 模拟构建上（正式构建的 AuthGate 登录门会阻断无头浏览器进入应用），API 全部经 `page.route` 拦截的 mock 响应。**它不证明**：生产 IAM、真实设备确认、真实扫描停止、真实撤销链路端到端。
- 冒烟脚本内 `result.json` 明确记录 `scope: "browser UI with mocked API; not backend E2E, not production IAM"`。

## 8. 范围外观察（未修改，仅供主开发者参考）

1. **AuthGate 与自动化**：正式构建（`VITE_DEV_MODE=false`）下自动化浏览器无法进入应用（需真实登录流程）。冒烟因此依赖模拟构建。未来若要真实 E2E，需要一个受控的测试登录路径或显式的 dev-only 旁路设计。
2. **并行开发迹象**：`EnvironmentsPage.tsx` 含其他未提交改动（DeviceLifecyclePanel 等）；工作树内存在大量其他开发者的未提交/未跟踪文件（agentshield、control-api 多处）。我的改动严格限于白名单文件，并保留了这些改动。
3. `test_discovery_schedule_management.py` 在我开始前已含他人未提交的 POST 测试（117 行）；任务书将其列为允许新增文件，故采用"原样保留 + 分界注释 + 追加 GET 测试"策略。
4. `apps/web` Vitest 为 node 环境（无 jsdom/testing-library），组件交互测试能力有限；组件级行为已由 reducer 测试 + 浏览器冒烟共同覆盖。

## 9. 完成边界

- **已完成**：CL-02-SCHEDULE-MANAGEMENT 子任务（后端只读查询 + 前端面板 + 撤销闭环 + 定向验证）。
- **未声明**：CL-02 整体完成、整体项目完成。
- **未执行**：任何 git 提交/推送/分支操作；任何部署；任何真实计划确认/撤销、真实设备操作、真实生产服务访问；未读取任何秘密（admin-password.private、真实 .env、令牌、密码、私钥、种子均未触碰）。
- 所有改动仅在工作树落盘，**待主开发者复核**。

## 10. 主开发者复核与修复（2026-09-26）

原交付并非无缺陷通过。旧模拟构建实测：首次撤销成功后刷新增加 generation，finally 未清理 pending，导致第二条计划确认撤销后没有请求。修复为成功刷新前释放 pending，并在 finally 无条件清理当前挂载实例的标记；后端撤销载荷、鉴权和审计未修改。

同步修复以下边界：

- 分页失败保留已加载行与同一游标，但清除旧 canRevoke；撤销失败也须先只读刷新，避免沿用旧权限提示。重试成功清除旧告警；撤销期间拒绝刷新/分页，刷新清除旧确认目标。
- 客户端严格核对 next_cursor 等于非空页最后 ID、后续页所有 ID 大于请求 cursor、撤销响应 revision 不低于 expected_revision（允许既有幂等相等）。拒绝日历滚转日期及 reserved_runs 超预算。
- 身份/环境挂载 key 改为 JSON 数组编码，避免分隔符歧义。无环境不发请求。保持项目设计语言；实际查看移动截图还发现列布局沿用桌面标签的 6em flex-basis，造成字段之间大块留白，仅在专用 CSS 移动断点重置为 auto，并在冒烟断言标签高度小于 40px。
- 冒烟只读阶段改为严格零业务写；新增不重载连续撤销与分页失败同游标重试。截图改为实际视口，避免对滚动容器内长元素截图造成大面积空白。

修复前前端针对性负例得到 6 failed / 31 passed；旧构建浏览器在第二次撤销检查失败（证据目录 `/tmp/siq-dsm-review-before-20260926`，脚本失败时未生成成功报告）。修复后实际命令与结果如下，取代原 §6 不够准确的命令覆盖描述：

| 检查 | 实际命令 / 结果 |
| --- | --- |
| 前端定向 | `cd apps/web && npm test -- src/api/discoveryScheduleManagement.test.ts src/components/discovery-schedule-management`：3 文件 / 39 passed |
| 后端定向 | `cd apps/control-api && uv run --no-sync pytest -o addopts='' -q app/tests/test_discovery_schedule_management.py app/tests/test_discovery_schedule_confirmation.py app/tests/test_discovery_schedule_tick.py --tb=short`：41 passed |
| 正式构建 | `VITE_DEV_MODE=false npm run build -- --outDir /tmp/siq-dsm-final-production-YRuCBt --logLevel error`：成功，含 tsc |
| 模拟构建 | `VITE_DEV_MODE=true npm exec -- vite build --outDir /tmp/siq-dsm-final-SIMULATED-NOT-RELEASABLE-0069Or --logLevel error`：成功，仅隔离模拟使用，不可发布 |
| 浏览器 | 独立 mock：15/15；连续两次撤销分别核对 revision 0 与 3，无自动重发，无未捕获异常 |
| 静态检查 | 后端目录内 Ruff 检查路由/测试；冒烟按 control-api 配置检查；`git diff --check` 与本次前端/脚本未跟踪文件空白检查通过 |

最终浏览器命令：

```bash
/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/discovery-schedule-management-browser-smoke.py --web /tmp/siq-dsm-final-SIMULATED-NOT-RELEASABLE-0069Or --out-dir /tmp/siq-dsm-review-final-compact-20260926
```

报告为该目录 `result.json`，桌面与 375px 截图为 `desktop.png` / `mobile.png`。模拟 API 证据不证明生产 IAM、真实设备撤销或停止采集；正式构建也未部署。本次仅管理子任务复核，不关闭 CL-02 或其他主线。未提交、未推送、未部署。
