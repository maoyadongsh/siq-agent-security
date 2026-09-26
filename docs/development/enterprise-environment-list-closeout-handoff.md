# 环境列表分页、加载状态与选择安全收口（CL-02-ENVIRONMENT-LIST-CLOSEOUT）交付与复核说明

日期：2026-09-26
状态：**未提交、未部署，待主开发者复核**。本文件仅声明 CL-02-ENVIRONMENT-LIST-CLOSEOUT 子任务完成，不声明 CL-02 整体、auto-onboarding 任务书或整个项目完成。

## 一、改动文件（均为工作树未提交内容，未推送、未建分支）

| 文件 | 状态 | 内容 |
| --- | --- | --- |
| `apps/web/src/pages/EnvironmentsPage.tsx` | 修改（未提交） | 分页/覆盖/URL 选择收口（见第三节）。注意：该文件相对 git HEAD 的 diff 还包含同一子任务线先前会话留下的未提交改动（桌面/移动双列表、接入子面板挂载、创建成功文案与页头描述调整），一并待复核；本会话在其上追加收口改动，未回退、未覆盖任何他人成果 |
| `apps/web/src/pages/environments.css` | 新增（未跟踪） | 仅列表局部样式：`.environment-desktop-list/.environment-mobile-list` 响应式切换与 `.environment-list-footer/-note/-coverage/-error` 最小样式；未改任何共享全局 CSS |
| `apps/web/src/pages/EnvironmentsPage.test.tsx` | 新增（未跟踪） | 14 条行为测试（node 环境 + 最小 DOM shim + react-dom/client 真实渲染，非源码字符串匹配） |
| `scripts/enterprise-experience/environment-list-pagination-browser-smoke.py` | 新增（未跟踪） | 隔离浏览器冒烟（全 API 合成 mock，仅本机回环） |

未触碰：useApiList、共享 client、listMeta、ConsoleContext、Layout、App.tsx 路由、components/onboarding/**、components/device-lifecycle/**、components/discovery-schedule-management/**、package.json、锁文件、共享全局 CSS、AuditPage/audit-search（Qwen 审计线）、Edge/Connector/后端调度器/安装器（主开发者线）。

## 二、修复前复现（红）

`/tmp/siq-cl02-envlist-closeout/repro-red-before-implementation.txt`：实现前运行 `EnvironmentsPage.test.tsx`，14 条测试全部失败。针对性复现用例：mock 服务端首批返回 50 条 + `x-siq-next-cursor`（总数 77），页面无“加载更多”入口、无覆盖说明文案，第 51 条环境经任何正常操作不可达，且空列表文案会把“清单完整性无法确认”误报为“尚无环境，请先创建”。

## 三、实现说明

### 分页接入
- 复用 `useApiList` 既有分页协议（服务端 `x-siq-*` 响应头 → `getListPage` → `listMeta`），未改共享 hook：页脚仅当 `hasMore`（`truncated && nextCursor`）时渲染显式“加载更多环境”按钮；`onClick` 直调既有 `loadMore()`，无自动循环、无轮询、无预取。
- 加载中：按钮禁用并显示“正在加载更多环境…”；成功：桌面表格与移动列表统一由 `useApiList` 追加，选中与 URL 不变；失败：既有 hook 语义保留记录与选中、显示 `.environment-list-error`（role=alert），重试以相同 cursor 重发（冒烟证据 `list_read_cursors=[null,'cursor-page-2',null,'cursor-page-2','cursor-page-2',null]`），无自动重试；重试成功后旧错误清除。刷新与过期追加的响应竞争由 hook 既有 requestSeq 丢弃逻辑处理（本会话未改 hook，仅以测试验证其行为）。
- 刷新（“刷新环境列表”）重读第 1 页（cursor=null），不混入旧分页响应。

### 清单覆盖范围（诚实呈现）
- 页脚常驻 `coverageText`（role=status），直接复用 `formatListCoverage`：区分 首次加载中/已连接空列表/截断未读全量/初次读取失败/分页失败但已有记录/刷新中。total 缺失时明确“不得视为全量”；仅当 `truncated === false` 才显示“尚无环境，请先创建。”，其余空态显示“未读取到环境记录，清单完整性无法确认。”。
- 未对“已连接”做任何设备在线、发现成功或受保护状态的推断。

### URL 选择与交互安全
- 保留既有 `environment` 查询参数，未新增路由。URL 指定环境不在已加载记录时：`hasMore` 显示“…在当前已加载记录中尚未找到，可点击‘加载更多环境’继续加载。”；列表完整显示“…在当前可见列表中未找到。”——绝不声称已删除或无权限，不自动创建、不自动切换；不存在的环境不挂载任何子面板（`selected` 未命中即不渲染面板块）。
- 加载更多不改变 URL（冒烟断言两次 `url.endswith('/environments')`）；刷新/选择/分页/重试不触发注册、扫描或计划撤销（冒烟以“非 GET 业务写请求即违规”拦截，violations=[]）。
- 未做任何硬编码管理员判定；权限仍由 ConsoleContext/Layout 与既有 `onboardingApi.access` 门禁承担；创建 API 路径/载荷/防重复提交/“结果未知不自动重发”语义全部原样保留（测试断言 `create('新环境','host')` 且未知结果仅提示不重发）。

## 四、既有能力保留证据

- 面板挂载条件 `selected && access` 不变，五个子面板（InstallPlanSetup/EnvironmentSetup/EnterpriseConnectionPanel/DeviceLifecyclePanel/DiscoverySchedulePanel）按既有权限条件渲染，测试中以哨兵组件断言仅选中真实存在环境时挂载。
- 权限门禁测试：`can_create=false` 隐藏创建表单；access 读取失败显示既有错误提示。
- 创建语义测试：载荷 `(name.trim(), type)` 不变；409 提示原文保留；未知结果文案“未确认创建结果…不会自动重复提交”保留。

## 五、实际执行的验证（命令与数量）

1. 单测（仅相关文件，未跑全仓）：在 `apps/web` 下 `npx vitest run src/pages/EnvironmentsPage.test.tsx` → **14/14 通过**（分页 4、覆盖 3、URL 选择 3、创建语义 2、权限 2）。输出存档 `/tmp/siq-cl02-envlist-closeout/vitest-final.txt`。
2. 标准构建：`apps/web` 下 `VITE_DEV_MODE=false npm run build -- --outDir /tmp/siq-cl02-envlist-closeout/build-KsjG`（独立临时目录）。**tsc 阶段失败，但失败全部来自其他开发线的未跟踪文件**：`src/pages/AuditPage.test.tsx`、`src/pages/__debug.test.tsx`、`src/components/audit-search/auditSearch.test.ts`（完整清单 `/tmp/siq-cl02-envlist-closeout/tsc-standard-build-errors.txt`，0 条涉及本任务文件）。为取得冒烟工件，改用 `VITE_DEV_MODE=false npx vite build --outDir <同一目录>`；测试文件不进入产物模块图，产物内容不受影响。未使用 `VITE_DEV_MODE=true`，故无需 SIMULATED 构建目录。
3. `git diff --check` → 通过（exit 0）；新增未跟踪文件无尾随空白。
4. 隔离浏览器冒烟：`/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/environment-list-pagination-browser-smoke.py --web /tmp/siq-cl02-envlist-closeout/build-KsjG --out /tmp/siq-cl02-envlist-closeout/browser-smoke` → 8 项检查全过（`report.json` scope=`isolated-mock-only-not-production`）：首批 50 条+覆盖文案+按钮、显式点击加载第 51 条（键盘 Enter、focus-visible、URL 不变）、URL 选择挂载面板且服务端名称按纯文本渲染（注入样本不执行）、分页失败保留记录/选中/报错、同 cursor 重试恢复、刷新重读第 1 页不混游标、375/768/1440 无横向溢出、零业务写请求+零外联+零未捕获异常。

## 六、截图与报告路径（截图均已人工查验）

- `/tmp/siq-cl02-envlist-closeout/browser-smoke/environments-1440.png`（桌面 1440 实视口）
- `/tmp/siq-cl02-envlist-closeout/browser-smoke/environments-375.png`（375px 实视口）
- `/tmp/siq-cl02-envlist-closeout/browser-smoke/environments-768.png`
- `/tmp/siq-cl02-envlist-closeout/browser-smoke/report.json`

模拟证据边界：冒烟对 `**/*` 全量路由拦截，所有 API（含 IAM refresh、console-context、环境列表/权限/onboarding）均为本机合成 mock，不访问真实控制面、生产数据库或真实设备；未覆盖的子面板读请求（`/api/v1/environments/env-51/install-options` ×2）返回 404 并记录于 `uncovered_read_paths`，其错误态非本子任务断言对象。

## 七、记录在案但未修的范围外问题

1. **后端 `GET /api/v1/environments` 目前未输出分页头**（`apps/control-api/app/routers/environments.py:123` 直接返回全量列表，未用 `app/list_meta.py` 的 `apply_list_meta`/`take_page`）。前端已完整按既有头部协议消费并在元数据缺失时诚实降级；服务端接线属主开发者范围。
2. 标准构建因其他开发线未跟踪测试文件的 TS 错误失败（见第五节第 2 条），本任务未代为修改。
3. 冒烟中 install-options 端点未覆盖（404），属安装计划面板既有依赖，未触碰。

## 八、复核声明

本子任务全部改动**未提交、未推送、未部署**；未执行任何 git 清理/还原/提交类操作；未启停真实服务；未注册设备、未确认安装计划、未启用周期扫描。工作树内他人未提交与未跟踪成果（含审计线与 `__debug.test.tsx` 等）均未触碰。请主开发者复核后统一处置。

## 九、主开发者验收修复（2026-09-26）

### 修正原复现口径

旧后端忽略 limit/cursor 并返回本租户全量环境，不是只返回 50 条。第二节的“第 51 条不可达”是分页 mock 条件下的前端缺口，不是当时真实后端截断证据。不能把两者混称为生产问题。

### 实际修复

- 刷新在途仍可点击旧加载更多，后发分页会抢占 requestSeq，导致刷新结果失效。新增真实页面回归修复前 1 failed / 14 passed（预期两次请求，实际三次），修复后 15 passed。页面派生 connected 状态同时控制 disabled 和事件门禁；遵循 React 技能，不新增同步 effect、不改共享 hook 或项目视觉。
- 主开发者接通后端列表协议，仅修改 environments.py 的列表端点及必要导入。新增 enterprise-environment-list.v1.md 冻结兼容行为：无 limit 仍全量；显式 limit 为 1–200，按 name/id 排序，同租户 cursor 锚点推进；跨租户/缺失锚点统一 422，env:read 不变。include_total 可选，按租户计算且不受 cursor 影响；返回既有 X-SIQ 列表头及 no-store，不新增写入。
- 新增 test_environment_list_pagination.py：真实隔离 TestClient 验证 51 条跨页、顺序无重复、旧全量调用、元数据、跨租户游标、权限、非法参数、真零条与 GET 不增加审计/outbox。前三项在旧端点均失败（实际忽略分页参数），修复后通过。初次权限夹具误用了不存在的 X-Dev-Permissions 头，已改用既有 viewer 角色，未放宽权限断言。
- 原浏览器截图未展示页脚，本轮补充 environments-pagination-375/768/1440.png，保留真实视口方式。

### 主开发者实际验证

```bash
# apps/web
npm test -- src/pages/EnvironmentsPage.test.tsx
VITE_DEV_MODE=false npm run build -- --outDir /tmp/siq-envlist-review-production-20260926
# apps/control-api
uv run --no-sync pytest -o addopts='' -q app/tests/test_environment_list_pagination.py app/tests/test_list_meta.py app/tests/test_environment_onboarding.py --tb=short
uv run --no-sync ruff check app/routers/environments.py app/tests/test_environment_list_pagination.py
# repo root
/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/environment-list-pagination-browser-smoke.py --web /tmp/siq-envlist-review-production-20260926 --out /tmp/siq-envlist-review-final-20260926
```

结果：前端 **15 passed**；后端 **14 passed**；标准 tsc + vite 成功，之前其他开发线造成的阻断本轮不再出现，未改其文件。隔离浏览器 **8/8**，无业务写/外联/未捕获异常，仍有两次未覆盖 install-options 的 mock 404，不能据此宣称安装面板验收完成。Ruff、git diff --check 与本次新增文件尾随空白检查通过。

报告与截图在 `/tmp/siq-envlist-review-final-20260926/`。浏览器使用模拟 IAM/API，即使静态产物为正式模式，也不是生产验收；后端分页由独立真实 TestClient 合成数据验证，不冒称浏览器已经直连真实后端。

本子任务经修复后验收通过。分页不是数据库快照，跨页重命名/删除可能影响结果；锚点丢失须显式刷新。未提交、未部署、未访问真实设备或业务数据，CL-02 整体仍开放。
