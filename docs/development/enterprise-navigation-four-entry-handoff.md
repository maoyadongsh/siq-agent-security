# ENT-018 子任务交付记录：企业端导航简化（四主入口）

日期：2026-09-25
范围：仅 ENT-018 中"企业端导航简化"子任务（导航组织与交互）。
**未提交、未部署，待主开发者复核。**

## 1. 实际修改/新增文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `apps/web/src/components/Layout.tsx` | 修改 | 导航组织改为四主入口 + 高级折叠区；标题计算改用纯函数；保留桌面折叠/移动抽屉/滚动锁/Escape 关闭/权限拒绝渲染逻辑 |
| `apps/web/src/components/enterpriseNav.ts` | 新增 | 纯函数模块：导航定义、分组、权限过滤、标题/归属、高级区域判定 |
| `apps/web/src/components/enterpriseNav.test.ts` | 新增 | 20 项单元测试 |
| `apps/web/src/components/enterprise-nav.css` | 新增 | 企业导航专用样式（仅 `entnav-*` 前缀类名，由 Layout 导入；未改共享全局 CSS） |
| `scripts/enterprise-experience/four-entry-navigation-browser-smoke.py` | 新增 | 独立浏览器验收脚本（隔离 mock 控制面 + VITE_DEV_MODE 模拟身份构建） |
| `docs/development/enterprise-navigation-four-entry-handoff.md` | 新增 | 本交付记录 |

未修改：`App.tsx` 路由、`local/**`、`onboarding/**`、`EnvironmentsPage.tsx`、`api/onboarding.ts`、后端/Edge/Connector、`package.json`/锁文件、共享全局 CSS、公共进度台账与总任务书。工作树中其他开发者的未提交改动一律未触碰。

## 2. 导航映射与交互行为

主导航（保持现有 URL）：

| 入口 | URL | 权限键 |
| --- | --- | --- |
| 资产 | `/agents` | agents |
| 权限 | `/permissions` | permissions |
| 安全 | `/findings` | findings |
| 审计 | `/audit` | audit |

次级"管理与高级功能"（默认折叠，折叠不是删除功能）：
工作台 `/workspace`、总览 `/overview`、策略中心 `/policies`、变更中心 `/changes`、运行时绑定 `/runtime-bindings`、环境与设备 `/environments`、设置 `/settings`。

交互：
- 高级区域为原生 `<button aria-expanded aria-controls>` 折叠控件，键盘可展开/收起（Enter/Space），内部为原生 `<a>` 链接。
- 当前位于次级页面时自动展开（`isAdvancedPath` 精确匹配），不改变浏览器 URL；用户手动切换后以用户选择为准，路由变化时恢复自动。
- 高级区域无任何可访问项目时整个分组不渲染（不显示空分组）。
- 顶栏标题：`/agents/skills` → "技能清单"；`/agents/:id` → "资产详情"；旧管理页面显示各自名称；未知路径回落"总览"。修复了原 `currentTitle` 前缀匹配把 `/agents/skills`、`/agents/:id` 误判为"智能体资产"、以及未匹配时一律显示"总览"的问题。
- 高亮（经主开发者复核修正）：资产入口覆盖 `/agents/skills` 与 `/agents/:id`，两类子页面均保留唯一的“资产”高亮；其余入口精确匹配，详见下方复核记录。
- 桌面图标折叠态：高级折叠控件保留 `title` 可访问名称，可展开并访问其链接（浏览器实测通过）。
- 移动端：点选链接关闭抽屉、Escape 关闭、滚动锁与事件清理逻辑原样保留。
- 所有旧 URL 保留可达，直接打开/刷新/前进/后退正常（浏览器实测通过）。

## 3. 权限过滤如何保留

- 每个入口单独按 `canVisit(context.data, item.to)`（内部走 `routeAccessKey`）过滤，主入口与高级入口各自独立过滤。
- 无权限链接不因移动到高级区域而重新出现（单测 + 浏览器实测：模拟身份无 policies/changes/runtime_bindings/environments 权限时，高级区域只显示工作台/总览/设置）。
- 不硬编码管理员身份、不模拟权限通过（单测覆盖"角色标签声称管理员但 access 为 false"场景）。
- 页面访问拒绝、身份加载失败（`正在核对页面访问权限…`）、重新核对权限（`context.reload`）机制原样保留在 Layout 中。
- 直达无权限页面（如 `/policies`）仍被拒绝渲染（浏览器实测通过）。

## 4. 测试命令、通过数量和失败情况

```
cd /home/maoyd/siq/siq-agent-security/apps/web
npm test
```

- 结果：**全部通过，无失败**。首次运行 69 文件 / 442 项；最终复核运行 71 文件 / 463 项（增量来自其他开发者并发新增的测试，非本任务改动）。本任务新增 `enterpriseNav.test.ts` 20 项，单独运行 `npx vitest run src/components/enterpriseNav.test.ts` 通过。
- 新增测试覆盖：四主入口标签与 URL；不同访问权限下的独立过滤；高级区域为空时隐藏（空数组语义）；`/agents/skills`、资产详情与旧管理页面的标题/归属；不因路径前缀相似误判（`/agents/skills`、`/agents/asset-1`、`/policies/extra` 等）；权限加载失败（context 为 undefined）与拒绝访问逻辑不被绕过。

构建（独立临时目录，未覆盖他人产物）：

```
npm run build -- --outDir /tmp/siq-enterprise-nav-qwen-build
```

- 结果：tsc 类型检查 + vite build 成功（`✓ built in 972ms`）。

## 5. 浏览器截图与结果文件路径

脚本：`scripts/enterprise-experience/four-entry-navigation-browser-smoke.py`
证据目录：`/tmp/siq-four-entry-nav-evidence-20260925/`（0700 权限）

- `report.json` — 22/22 检查通过
- `desktop-main.png` — 桌面：四主入口 + 默认折叠高级区域（已实际查看）
- `desktop-collapsed.png` — 桌面图标折叠态 + 高级区域展开（已实际查看）
- `mobile-drawer.png` — 375px 移动抽屉（已实际查看）
- `build.log` — 模拟身份构建日志

检查项（全部通过）：桌面四主入口与默认折叠高级区域；键盘展开/选择/焦点可见（`:focus-visible` 金色焦点环）；直达旧管理 URL 自动展开且 URL 不变；无权限链接不出现且直达页面被拒绝；桌面图标态可访问高级功能；375px 抽屉点选关闭/Escape 关闭/无横向溢出（scrollWidth 差 ≤ 0）；前进/后退正确；无新增业务写请求（mock 服务端记录 0 条 POST/PUT/PATCH/DELETE）；无浏览器未捕获异常。

**注意：浏览器验收使用 VITE_DEV_MODE 模拟身份构建 + 127.0.0.1 隔离 mock 控制面，仅用于导航交互验收，不是生产环境验收。**

## 6. 未完成项及已知限制

- 本记录只覆盖 ENT-018 的导航简化子任务。ENT-018 的其余部分（框架—角色—Skill 展开/搜索/筛选/批量选择、精确关系树、业务权限批量管理）不在本次范围，未完成。
- 浏览器验收基于 mock 数据（空列表），未验证真实数据量下的导航滚动表现；高级区域列表在移动端限高 50vh 可滚动。
- 高级区域自动展开状态不持久化（每次路由变化恢复"跟随路径"），这是有意选择：避免把用户位置偏好写入存储，且保证"当前在次级页面时知道自己在哪"。
- 模拟验收构建（VITE_DEV_MODE）不可发布；生产构建路径未改动。
- 发现（未修改）：`OverviewPage` 的快捷磁贴仍使用旧文案（"智能体资产/权限视图/风险中心"），与四主入口新标签（资产/权限/安全）不完全一致；属页面文案范畴，超出本任务允许范围，留待主开发者决定。

## 7. 状态声明

**未提交、未部署，待主开发者复核。** 未创建提交/分支/PR，未安装依赖，未启动或部署任何生产服务，未连接真实业务数据。

## 8. 主开发者独立复核与修正（2026-09-25）

以上测试数量及状态保留为原交付记录，本节记录后续复核结果。

- 发现：原浏览器 22 项检查通过，但未覆盖资产子页面的导航高亮。独立复现发现 `/agents/skills` 和 `/agents/fixture-agent` 标题正确、主导航高亮数量却为 0，不符合子页面属于资产领域的要求。
- 修正：`Layout.tsx` 仅资产链接采用分段前缀匹配；`enterpriseNav.ts` 同步归属计算，避免 `/agents-old` 等相似前缀误判。遵循 React 技能直接派生路径归属，不新增状态存储、依赖或视觉样式。
- 测试：`enterpriseNav.test.ts` 现为 21 项；全量 `npm test` 为 **71 文件 / 464 项通过**，日志 `/tmp/siq-nav-review-web-tests.log`。浏览器新增两个子页面唯一高亮及标题断言，最终 **24/24 通过**。
- 构建：`env -u VITE_DEV_MODE npm run build -- --outDir /tmp/siq-nav-codex-review-build-20260925` 成功，日志 `/tmp/siq-nav-codex-review-build-20260925.log`。该产物没有部署，不据此声明发行完成。
- 浏览器命令：`python3 scripts/enterprise-experience/four-entry-navigation-browser-smoke.py --output /tmp/siq-nav-codex-review-20260925-r3`。全部 API 为 loopback 隔离模拟；模拟身份构建不可发布，不是生产验收。
- 截图与结果：上述 r3 目录中的 `desktop-main.png`、`desktop-collapsed.png`、`mobile-drawer.png` 和 `report.json`。三张截图已由主开发者实际查看；截图禁用动画以捕获最终显示状态，不修改产品动画。沿用现有米白底色、深蓝文字、金色强调、字体、按钮及卡片样式，375px 检查无横向溢出。
- 权限：逐项过滤、直达拒绝、加载/失败/重新核对分支保留；浏览器覆盖链接过滤和直达拒绝。未新增业务写请求，未修改安全判断或后端接口。未进行真实 IAM、生产部署或全项目防攻击回归验收。
- `git diff --check` 通过。仅导航子任务已复核修正，ENT-018 其余事项及整体目标仍未完成；未提交、未部署。
