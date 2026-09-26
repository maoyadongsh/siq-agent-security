# ENT-018-FRAMEWORK-TREE-UI 交接记录（2026-09-25）

企业端「智能体资产」页新增「框架实例」只读视图：环境 → 设备 → 框架配置实例 → 角色资产。
本记录仅声明 ENT-018-FRAMEWORK-TREE-UI 子任务的实际完成情况，不代表 ENT-018 整体、
精确角色—技能关联或整个项目已完成。**未提交、未部署，待主开发者复核。**

## 1. 实际修改与新增文件

新增：

- `apps/web/src/api/frameworkRoleInventory.ts` — `GET /api/v1/framework-role-inventory`
  只读客户端 + 严格响应核验。
- `apps/web/src/api/frameworkRoleInventory.test.ts` — 34 条解析/请求测试。
- `apps/web/src/components/framework-tree/frameworkTree.ts` — 分组纯函数。
- `apps/web/src/components/framework-tree/frameworkTree.test.ts` — 9 条分组测试。
- `apps/web/src/components/framework-tree/FrameworkTreeView.tsx` — 树视图组件。
- `apps/web/src/components/framework-tree/FrameworkTreeView.test.tsx` — 16 条行为测试
  （复用 `src/pages/runtimeBindingPageDomShim.ts` 最小 DOM shim，未修改该文件）。
- `apps/web/src/components/framework-tree/framework-tree.css` — 新样式，全部
  `framework-tree-` 前缀。
- `scripts/enterprise-experience/framework-tree-browser-smoke.py` — 隔离模拟浏览器冒烟。

修改（最小接入）：

- `apps/web/src/pages/AgentsPage.tsx` — 仅新增：import、局部状态 `frameworkView`、
  第三个 tab 按钮「框架实例」、框架视图挂载点；两个既有 tab 的 onClick 增加
  `setFrameworkView(false)`，aria-selected/className 增加 `!frameworkView` 条件；
  既有列表/候选/批量确认/驳回/API 载荷与权限逻辑未改动。
  注意：该文件同时有主开发线的未提交改动（批量选择/BulkCandidateReview），本任务
  未触碰那些行；若对方继续改动同一区域出现冲突，保留双方实现再复核。

未修改：`frameworkSource.ts`、`FrameworkSourcePanel.tsx`（主开发者负责）、后端、
App.tsx 路由、ConsoleContext、共享 client、共享全局 CSS、package.json/锁文件。

## 2. 分组键、分页、重复项与未知来源处理

- 分组键：`environment_id + device_id + framework + instance_key`（NUL 分隔拼接），
  仅 `historical_reported_source` 参与实例分组；不用名称/摘要前缀/框架名做唯一键；
  不同设备同 instance_key 分开（有测试）。
- 同名角色不去重，以完整 `asset_id` 标识并作为 React key。
- 未知来源单列：「来源待确认」区下分「无来源记录」（no_recorded_source）与
  「来源暂不可确认」（source_unavailable）两个可折叠分组，文案区分语义。
- 分页：显式「加载更多角色记录」按钮，`next_cursor` 透传；失败保留已加载记录并
  提供「按同一位置重试」（同游标同过滤，不跳页）；重复游标/非升序/游标与末项不符
  在解析层直接拒绝，组件层另有用过游标集合兜底防死循环。
- 重复 asset_id：内容一致去重；内容冲突保留首条并打「需刷新核对」标记 +
  页面级 alert（冲突计数），不静默当作已核验。
- 展示明确「已加载 N 条角色记录；仅为已加载页，不代表组织全量」；实例摘要写
  「已加载 N 个角色（非完整清单）」。

## 3. 权限、身份切换与迟到响应

- 使用既有 `useConsoleContext`；要求 `access.agents && access.environments` 双权限。
  身份加载中/失败/权限不足：不发清单请求、不显示旧身份数据（有测试断言零请求）。
- 身份（tenant/actor）或已应用 environment_id/device_id 变化时按 key 重挂载结果组件。
- 请求序号（seq ref）+ effect cleanup 使迟到响应失效；刷新立即清空旧页，
  旧「加载更多」迟到响应不得覆盖新结果（单测 + 浏览器均覆盖）。
- 所有请求只读 GET，经既有认证 client；不传 tenant_id 或身份覆盖参数；
  不使用 localStorage/sessionStorage；不自动循环拉取全部页。
- 后端文本一律纯文本渲染（无 dangerouslySetInnerHTML）；`effective_permissions=null`
  显示为「本视图无证据（不代表无权限）」；运行状态未验证、技能安装关系待确认、
  设备凭据吊销/未吊销（≠在线）分开表述。

## 4. 风格复用

复用现有类：`tabs/tab-btn`、`btn/btn-sm`、`card 变量体系`、`kv-list`、`mono`、`tag`、
`list-more`、`row-actions`、`PageHeader`。新 CSS 全部 `framework-tree-` 前缀，
引用既有 CSS 变量（--card/--bg/--border/--ink/--text-secondary/--siq-primary 焦点框
等），未改任何共享全局样式。交互用原生 details/summary + button + link（可访问的
分层折叠列表，非伪装 ARIA tree）；焦点可见；加载/失败用 role=status/role=alert。

## 5. 实际测试命令与结果

- `cd apps/web && npm test`：101 文件 / 839 用例全部通过（含本任务新增 59 条：
  34 解析 + 9 分组 + 16 组件行为）。
- `cd apps/web && npm run build -- --outDir /tmp/ent018-framework-tree-build-20260925`：
  成功（tsc -b && vite build，exit 0）。标准构建未被并行开发线阻断。
- `uv run ruff check scripts/enterprise-experience/framework-tree-browser-smoke.py`：通过。
- 浏览器冒烟（仅模拟验收，不可发布）：先用
  `VITE_DEV_MODE=true ./node_modules/.bin/vite build --outDir /tmp/ent018-framework-tree-mock-20260925`
  构建隔离包，再运行
  `python3 scripts/enterprise-experience/framework-tree-browser-smoke.py --web /tmp/ent018-framework-tree-mock-20260925 --out .tmp/ent018-framework-tree-smoke-20260925`。
  12 项检查全过：默认列表无清单请求、切视图才请求、折叠键盘与详情链接、XSS 不执行、
  跨页合并/跨设备不混并、刷新不混页、迟到响应不覆盖、分页失败保留+同游标重试、
  权限不足不请求、加载/空/失败状态、375/768/1280 无横向溢出、零写请求零未捕获异常。
  报告：`.tmp/ent018-framework-tree-smoke-20260925/report.json`。
- `git diff --check`：通过（新文件含在内，ruff 校验过脚本格式）。

## 6. 浏览器报告与截图

目录 `.tmp/ent018-framework-tree-smoke-20260925/`（本地证据，未提交）：

- `report.json` — 检查清单、违规与错误（均空）、清单请求游标序列。
- `framework-tree-1280.png` / `framework-tree-375.png` — 折叠态桌面/移动。
- `framework-tree-expanded-1280.png` / `framework-tree-expanded-375.png` — 展开态
  （含跨页合并后 3 角色实例、edge-two 吊销设备分组、来源待确认两桶），已实际查看。

以上为合成 fixture + Playwright 拦截的隔离模拟验收，不证明真实控制面、IAM 或生产
环境行为；未连接任何真实业务数据。

## 7. 未完成项与范围外问题

- 本任务只读展示：不含纳管、授权、扫描、运行时绑定或任何治理写操作。
- 角色—技能精确关联仍是 ENT-008/ENT-018 后续事项；本视图只展示「技能安装关系待
  确认」说明，没有也不伪造技能节点。
- 「重复游标」在严格解析下不可达组件层兜底分支（解析层已拒绝），兜底代码保留为
  纵深防御；组件级重复游标用例因此由解析层测试覆盖。
- vitest 4.1 环境实测发现：在 `beforeEach` 钩子内对 hoisted mock 调用
  `mockReset/mockClear` 会让后续 `mockRejectedValue` 的拒绝被误报为未处理拒绝；
  本任务测试改在测试体内首行重置（已在两个测试文件注释中记录）。该现象是否影响
  其他任务的测试，留待主开发者判断。
- 详情页返回链接：`/agents/:id` 的「返回列表」固定回 `view=agents|candidates`；
  从框架实例视图进入详情后返回会落到资产清单而非框架实例视图（AgentDetailPage
  不在本任务允许修改范围）。

## 8. 合同与实现一致性核对

- `GET /api/v1/framework-role-inventory` 实现（`apps/control-api/app/routers/framework_inventory.py`，
  未跟踪文件，主开发线在收口）与合同 `enterprise-framework-role-inventory.v1.md` 一致：
  schema_version/items/next_cursor/coverage 四字段、cursor=上一页末资产 ID、
  limit 1..100 默认 50、按资产 ID 升序、来源投影为完整
  `enterprise-framework-source-view/v1` 且 asset_id 与清单项一致。未发现差异。
- 后端清单接口仍在主开发线收口；若其字段或状态值后续变化，需同步
  `frameworkRoleInventory.ts` 解析器与测试。
