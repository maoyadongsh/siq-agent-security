# ENT-018-OVERVIEW 子任务交付记录：企业总览页四入口对齐与状态展示优化

日期：2026-09-25
范围：仅 ENT-018-OVERVIEW 子任务（企业总览页 `/overview` 的快捷入口对齐与统计状态展示）。
**未提交、未部署，待主开发者复核。**

## 1. 实际修改/新增文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `apps/web/src/pages/OverviewPage.tsx` | 修改 | 四主入口固定顺序 + 次级折叠区；统计区分 加载中/真实 0/失败/缺失异常；请求序号防过期覆盖；失败态不显示历史统计 |
| `apps/web/src/components/enterprise-overview/overviewStats.ts` | 新增 | 纯函数：`isSafeCount`（非负安全整数）、`statDisplayValue`（缺失/异常返回 undefined，不转 0）、`hasInvalidStat`、七项统计键、边界说明文案常量 |
| `apps/web/src/components/enterprise-overview/overviewEntries.ts` | 新增 | 纯函数：四主入口/次级入口定义（标签、URL、说明、图标）、`filterEntries` 逐项按 `canVisit(context, 实际路径)` 过滤 |
| `apps/web/src/components/enterprise-overview/overview.css` | 新增 | 仅 `entoverview-*` 前缀局部样式（加载/未知值、异常提示、边界说明、次级 details/summary 与 chevron）；未改共享全局 CSS |
| `apps/web/src/components/enterprise-overview/overviewStats.test.ts` | 新增 | 10 项单元测试（统计校验纯函数） |
| `apps/web/src/components/enterprise-overview/overviewEntries.test.ts` | 新增 | 8 项单元测试（入口定义、逐项权限过滤、空分组、角色名不覆盖权限） |
| `apps/web/src/pages/OverviewPage.test.tsx` | 新增 | 11 项组件行为测试（最小 DOM shim + react-dom/client 真实渲染；mock `api.overview` 与 `getConsoleContext`） |
| `scripts/enterprise-experience/overview-four-entry-browser-smoke.py` | 新增 | 隔离浏览器验收脚本（127.0.0.1 静态服务 + 拦截 mock API，VITE_DEV_MODE 模拟身份构建，仅测试用途、不可发布） |
| `docs/development/enterprise-overview-four-entry-handoff.md` | 新增 | 本交付记录 |

未修改（任务禁止清单）：`Layout.tsx`、`enterpriseNav.ts`、`enterprise-nav.css`、`App.tsx` 路由、`PermissionsPage.tsx`、`components/permission-facts/**`、`SkillsPage.tsx`、`SkillHistory.tsx`、`api/skillInventory.ts`、`api/skillHistory.ts`、`hooks/useApiList.ts`、`local/**`、`components/onboarding/**`、`EnvironmentsPage.tsx`、共享 API/类型/权限/图标/PageHeader/DisconnectedNotice、共享全局 CSS、后端/Edge/Connector/安装器/安全规则、`package.json`/锁文件、任务书/进度台账。未安装任何新依赖。工作树中其他开发者的未提交改动（如 `enterpriseNav.ts`、`Layout.tsx`、`useApiList.ts` 等）一律未触碰，按当前状态对待。

## 2. 四主入口与次级入口、权限过滤规则

主入口（顺序固定，保持原 URL，说明文字为事实性描述、不含无证据承诺）：

| 入口 | URL | 权限键 | 说明文字 |
| --- | --- | --- | --- |
| 资产 | `/agents` | agents | 查看发现候选与已纳管资产 |
| 权限 | `/permissions` | permissions | 查看权限事实与来源 |
| 安全 | `/findings` | findings | 查看风险与处置记录（"安全"仅为入口名称，不是防护承诺） |
| 审计 | `/audit` | audit | 查看事件与溯源记录 |

次级入口（收进默认折叠的"管理与高级功能"区域，折叠不是删除功能）：
策略中心 `/policies`（期望策略管理）、变更中心 `/changes`（审批与变更状态）。

权限过滤规则：

- 每个链接独立调用 `canVisit(context, 实际路径)` 过滤；不按角色名称判断、不硬编码 admin。
- 身份未加载（context 为 undefined）或加载失败时不假设任何权限通过（入口全空）。
- 主入口无可访问项时不渲染空网格；次级区域无可访问项时整个 `<details>` 不渲染（不显示空壳）。
- 次级区域使用原生 `<details>/<summary>`（原生键盘可访问：Tab 聚焦 summary、Enter/Space 展开），未复制整条侧边栏，未新增页面/路由。

## 3. 统计加载/异常/失败处理

- 保留既有七项统计与真实 `/overview` API 映射（agents、candidates、open_findings、critical_findings、environments、edges_online、policies），无新增请求依赖、无轮询、无业务写。
- 状态区分：
  - 加载中：显示"加载中…"（`role="status"`），不显示伪 0。
  - 真实 0：显示 0（合法值），但不解释为"已安全/没有风险/已全面保护"。
  - 失败：显示 `DisconnectedNotice`（明确错误 + "重试连接"），不显示历史统计；重试成功清除旧错误并恢复统计。
  - 缺失/非法值（负数、小数、NaN、字符串、字段缺失）：显示"未知/未提供"，绝不以 `?? 0` 之类方式静默转 0；并显示 `role="alert"` 提示"部分统计数值缺失或异常（列出字段名）"。
  - 有效值判定：`Number.isSafeInteger(value) && value >= 0`。
- 边界说明：统计区下方固定显示"设备心跳正常不等于已完成盘点或运行时防护已核验。"；不从心跳/资产数量/风险零值推导"防护已生效/已受保护/自动完成隔离"。
- 过期请求防护：`requestSeq` 序号守卫，卸载或新请求后旧响应不覆盖当前状态；重试成功清除旧错误。

## 4. 项目风格保持方式

- 复用既有 `stat-card`/`stats-grid`/`quick-tile`/`quick-grid`/`card`/`btn`/`notice` 类与 `PageHeader`/`DisconnectedNotice`/`Icon` 组件；未另起视觉设计。
- 新增样式仅 `entoverview-*` 前缀，全部使用既有设计变量（`--card`、`--border`、`--radius-card`、`--shadow-card`、`--text-secondary`、`--tone-*` 等），未改共享全局 CSS。
- 配色、字体、间距、按钮、卡片、图标与现有页面一致（浏览器截图核对）。

## 5. 测试/构建命令与实际结果

| 命令 | 结果 |
| --- | --- |
| `npx vitest run src/components/enterprise-overview src/pages/OverviewPage.test.tsx`（apps/web） | 3 个文件、29 项测试全部通过 |
| `npm test`（apps/web 全量） | 78 个文件、520 项测试全部通过 |
| `npm run build -- --outDir /tmp/siq-overview-nav-build-IlEYUc`（含 `tsc -b`） | 成功（独立临时目录，未覆盖他人构建产物） |
| `git diff --check` | 通过（无空白错误）；新增未跟踪文件另行检查无尾随空白 |

单测覆盖（按任务要求逐项）：四入口标签/URL/顺序；次级入口保留；逐项权限过滤 + 空分组隐藏；admin 角色名不覆盖真实权限；真实 0/正数/缺失/负值/非法类型；不从心跳/资产数量/风险零值推导防护。

## 6. 浏览器验收报告与截图

脚本：`scripts/enterprise-experience/overview-four-entry-browser-smoke.py`
运行：`python scripts/enterprise-experience/overview-four-entry-browser-smoke.py --output /tmp/siq-overview-four-entry-evidence-20260925-final`
环境：127.0.0.1 本地静态服务 + 拦截 mock API（不连接真实控制面）；VITE_DEV_MODE 模拟身份构建（仅测试用途、不可发布）。**本验收为模拟环境验收，不代表生产环境验收。**

结果：**19/19 通过**（报告：`/tmp/siq-overview-four-entry-evidence-20260925-final/report.json`）：
加载无伪零值；真实 0 显示 0 且不解释为已安全；心跳边界说明显示；缺失/负值/非数字显示"未知/未提供"（不转 0）+ 异常提示；失败显示错误与重试入口且不显示历史统计；重试成功恢复；四主入口顺序与 URL 正确；高级区默认折叠、键盘 Enter 展开、保留策略/变更入口；无权限入口不出现、有权限入口出现、次级空壳不显示；375/768/1024/1280/1440px 五个视口 `documentElement` 与 `.content` 的 scrollWidth-clientWidth 均 ≤ 0（未用 overflow:hidden 伪装）；无新增业务写请求（POST/PUT/PATCH/DELETE 全部被 mock 拒绝且页面未发起）；无浏览器未捕获异常。

截图（已实际查看，均可见被验证的快捷入口，非只截页头）：

- `/tmp/siq-overview-four-entry-evidence-20260925-final/overview-desktop.png` — 桌面 1280px，滚动至快捷入口区：四主入口 + 折叠的"管理与高级功能"
- `/tmp/siq-overview-four-entry-evidence-20260925-final/overview-desktop-expanded.png` — 展开后的次级区域元素截图：策略中心/变更中心
- `/tmp/siq-overview-four-entry-evidence-20260925-final/overview-375.png` — 375px 移动视口，滚动至快捷入口区
- `/tmp/siq-overview-four-entry-evidence-20260925-final/overview-1024.png` — 1024px 中等视口，滚动至快捷入口区

注：页面布局为 `.app-shell { height:100dvh; overflow:hidden }`，文档本身不滚动，滚动容器是 `.content`；截图前将 `.content` 滚动到快捷入口区域再截视口（展开区为元素级截图）。

## 7. 未完成项 / 范围外发现 / 验证限制

- 未完成项：无（本子任务范围内全部完成）。
- 范围外发现（未处理，仅记录）：
  - `enterpriseNav.ts`/`Layout.tsx` 存在其他开发者的未提交改动（资产入口高亮覆盖 `/agents/` 子路径等），本任务未触碰、未复核。
  - 浏览器验收基于 VITE_DEV_MODE 模拟身份与 mock 控制面，真实控制面下的权限/统计行为未验证（任务禁止连接真实控制面）。
  - 组件单测使用最小 DOM shim（node 环境、无 jsdom/testing-library，任务禁止安装依赖），交互细节（键盘、视口、滚动）由浏览器验收覆盖。
- 验证限制：未做生产环境验收、未做真实设备/真实用户数据验证、未做 a11y 自动化工具扫描（键盘可访问性经浏览器脚本 Enter 展开实测）。

## 8. 状态声明

**未提交、未部署，待主开发者复核。** 本记录仅声明 ENT-018-OVERVIEW 子任务状态，不代表整个 ENT-018 或项目完成。

## 9. 主开发者复核与修复（2026-09-25）

结论：本子任务通过源码与隔离模拟 UI 验收。未提交、未部署，未改变真实业务状态；不代表 ENT-018 整体或生产验收完成。

复核发现：HTTP 200 的 `false`、`0`、空字符串、数组响应未被总览页识别为协议异常，会进入成功展示分支。已在 OverviewPage 成功回调、requestSeq 校验之后增加非对象校验，异常显示错误及重试，不渲染统计卡。字段级缺失继续显示未知而非伪零，合法零值保持原样。`null` 已由共享 client 拒绝，本轮只增加页面防御和回归，不声称原 HTTP 链路可绕过 null 检查。

新增 5 项组件负向测试，修复前均失败；测试表使用对象包装数组值，确保 `[]` 实际作为响应传入。浏览器补充 5 种异常根值：首次 23/24，null 的断言误用页面错误文案；核对共享 client 后按真实“协议错误”文案验证，未更改共享协议校验。最终 24/24 通过。

本轮只修改 `OverviewPage.tsx`、`OverviewPage.test.tsx`、`overview-four-entry-browser-smoke.py` 和交付/进度记录。React 技能用于异步请求及派生状态复核，保留原 requestSeq 和卸载清理；未添加 effect、依赖或全局样式。

实跑验证：

```bash
# apps/web
npm test
npm test -- src/components/enterprise-overview src/pages/OverviewPage.test.tsx
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-overview-review-standard-20260925
# 仓库根目录，脚本自行构建隔离的模拟身份产物，不可发布
python3 scripts/enterprise-experience/overview-four-entry-browser-smoke.py --output /tmp/siq-overview-review-final-20260925
git diff --check
```

- 全量 78 文件 / 529 项通过；总览专项 3 文件 / 34 项通过。
- 标准构建通过，未使用 import 映射或覆盖运行产物。
- 隔离浏览器 24/24 通过；零业务写请求、无未捕获异常，五视口宽度检查通过。
- 证据：`/tmp/siq-overview-review-final-20260925/report.json`，同目录四张 `overview-desktop.png`、`overview-desktop-expanded.png`、`overview-375.png`、`overview-1024.png` 已实际查看；保留现有暖纸、墨蓝、深金、卡片和按钮风格。窄视口部分描述沿用现有省略样式，不将宽度通过解释为所有文案完整展开。
- 权限仍逐项使用 canVisit；未修改路由、共享身份逻辑、后端或防御能力。真实 IAM/真实统计联验仍未执行，临时证据目录可能被系统清理。
