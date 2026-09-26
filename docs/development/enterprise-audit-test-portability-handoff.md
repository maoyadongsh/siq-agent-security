# CL-01-AUDIT-TEST-PORTABILITY 交付记录：移除审计测试对兄弟仓 jsdom 的外部依赖

## 主开发者复核补记（2026-09-26）

已检查完整 harness、组件用例与清理逻辑；结合 React 技能的事件监听与清理边界，
确认当前输入通过原型 setter 和 React 委托监听器进入真实 handler，未绕过组件状态。
没有发现阻断当前用例的实现问题，本轮未改测试代码或产品代码，仅纠正本记录的证据口径。

本轮实际执行：

```bash
# apps/web
npm test -- src/pages/AuditPage.test.tsx \
  src/components/audit-search/auditSearch.test.ts \
  src/components/audit-search/auditCorrelation.test.ts src/pages/RuntimeBindingsPage.test.tsx
./node_modules/.bin/vitest run --no-isolate --no-file-parallelism \
  src/pages/AuditPage.test.tsx src/pages/RuntimeBindingsPage.test.tsx
VITE_DEV_MODE=false npm run build -- --outDir /tmp/siq-audit-portability-review-CcKsQw
```

结果：四文件 **37 passed**；无隔离组合 **26 passed**；正式模式标准构建通过，
输出目录由 mktemp 创建，未覆盖 dist；`git diff --check` 通过。
这两组测试相互重叠，不累加为不同用例总数。未安装依赖、未运行全量或真实浏览器。

代码检查确认当前两个文件无兄弟仓运行时导入。66 条 expect 表达式及交付者的历史
比对不证明所有 DOM 行为等价；同上下文组合通过只说明此次所测组合未失败，不能
证明任意测试顺序、任意其他全局描述符或 React 模块缓存条件均无污染，命令参数
排列也不保证 Vitest 实际反序执行。shim 仍仅用于限定场景，不能替代浏览器验收。

仅接受“审计测试已去除兄弟仓 jsdom 运行时依赖”子项。未在干净机器安装验证，
未提交、未推送、未部署，CL-01 整体仍开放。

日期：2026-09-26
范围声明：本记录只覆盖任务书中的 **CL-01-AUDIT-TEST-PORTABILITY 子任务**——关闭 `AuditPage.test.tsx` 对兄弟仓 `node_modules` 的外部依赖阻断，保留原有真实组件行为测试与安全回归。**仅关闭「审计测试外部依赖」这一项阻断，不关闭 CL-01 整体**；不重新开发审计界面、不增加产品功能、不迁移测试框架。

**状态：未提交、未推送、未部署。待主开发者复核。**

**未修改任何产品代码。** 本次改动全部在测试与测试辅助层。

## 1. 实际修改与新增文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `apps/web/src/pages/AuditPage.test.tsx` | 修改（重写环境获取方式） | 删除 `createRequire` + 兄弟仓绝对路径 jsdom；改为导入审计测试专用 DOM；用例与断言全部保留 |
| `apps/web/src/test-support/auditDomHarness.ts` | 新增 | 审计测试专用最小 DOM（真实挂载 react-dom/client 所需的最小原生表面） |
| `docs/development/enterprise-audit-test-portability-handoff.md` | 新增 | 本交付记录 |

**未修改其他文件。** 尤其未触碰（均按任务书要求只读）：

- `apps/web/src/pages/AuditPage.tsx`（产品代码，含主开发者本轮身份隔离与同条件关联修复）；
- 身份/权限实现、`ConsoleContext`、共享 `@/api/client`；
- 全局测试配置 `vitest.config.ts`、`tsconfig.json`；
- `package.json`、锁文件（**未安装任何依赖**）；
- 其他页面测试（`EnvironmentsPage.test.tsx`、`OverviewPage.test.tsx`、`RuntimeBindingsPage.test.tsx` 等）；
- 既有浏览器脚本（未新增浏览器脚本与截图）。

改动边界用文件时间戳交叉核对：`AuditPage.tsx` 13:18、`auditSearch.ts` 13:17、`auditCorrelation.ts` 11:46、`AuditSearchForm.tsx` 09-25、`vitest.config.ts` 09-25、`package.json` 09-19，均早于本次改动（`AuditPage.test.tsx` 14:51、`auditDomHarness.ts` 14:52），主开发者未提交成果未被覆盖。

开始前 `git status` 显示工作树存在大量他人/在途改动（Edge、Control API、技能与发现周期等其他工作线）。本次仅在上表白名单文件内改动。`AuditPage.test.tsx` 与 `components/audit-search/` 本身是 ENT-019 / CL-06 既有未提交成果，本任务在其上原地重写测试文件。

## 2. 被移除的外部依赖（代码级证据）

证据来自本仓文件本身，**未读取兄弟仓任何内容**。改动前 `AuditPage.test.tsx` 的相关行：

```ts
// L11  环境说明：jsdom 不在本仓依赖中（不安装新依赖），经 createRequire 复用兄弟项目已安装副本。
// L16
import { createRequire } from 'node:module';
// L22
const siblingRequire = createRequire('/home/maoyd/siq/siq-workbench/package.json') as any;
// L24
const { JSDOM } = siblingRequire('jsdom') as any;
```

为什么这是可复现性阻断（均为实测，非推断）：

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 本仓是否声明 jsdom | `grep -n "jsdom" apps/web/package.json` | 无（同查 `testing-library`、`happy-dom` 也无） |
| 本仓安装是否含 jsdom | `ls -d apps/web/node_modules/jsdom` | 不存在 |
| 本仓能否解析 jsdom | `node -e "require.resolve('jsdom')"` | `UNRESOLVED: MODULE_NOT_FOUND` |
| 全仓是否还有同类写法 | `grep -rn "createRequire\|siq-workbench" apps/web/src apps/web/dev` | 仅剩本次新写的说明性注释，无代码 |

即：原测试之所以能在本机通过，唯一原因是 `/home/maoyd/siq/siq-workbench` 这个兄弟仓恰好存在于同一台机器上。独立检出 `siq-agent-security` 后，`createRequire` 的目标文件不存在，该文件无法收集执行。

同时确认本仓其余 DOM 测试**从未**使用这种写法：`EnvironmentsPage.test.tsx` 与 `OverviewPage.test.tsx` 各自内联一份最小 DOM shim（`FakeElement` 等），`RuntimeBindingsPage.test.tsx` 从本仓 `./runtimeBindingPageDomShim` 导入——均只引本仓文件，无任何外部路径。本次重写使审计测试回到同一约定。

## 3. 替代机制

### 3.1 选择

复用本仓已验证模式（`src/pages/runtimeBindingPageDomShim.ts` + `RuntimeBindingsPage.test.tsx`）的必要部分，新增**审计测试专用**辅助 `src/test-support/auditDomHarness.ts`。没有引入通用 DOM 框架，没有新增通用选择器引擎之外的抽象，只实现当前审计测试真正用到的表面。

`restoreAuditDom()` 中全局属性按「安装前快照」逐个恢复或删除，随后清空文档挂载节点，避免影响同进程后续测试文件。

### 3.2 react-dom 18.3.1 的硬性要求（决定 shim 形态的原因，逐条对应实测）

| # | react-dom 行为 | 对 shim 的硬性要求 |
| --- | --- | --- |
| 1 | `canUseDOM` 在**模块加载期**求值 | DOM 全局必须先于 react-dom 加载就位；测试文件里 harness 的 `import` 排在 `react-dom/client` 之前（ESM 按源码顺序执行） |
| 2 | `isEventSupported('input')` 走 `'on' + 'input' in document` | `document` 用 Proxy，`has` 陷阱对任意 `on*` 键返回真，否则走 IE 兼容路径、受控文本 change 永不触发 |
| 3 | `getActiveElementDeep` 执行 `element instanceof win.HTMLIFrameElement` | `window.HTMLIFrameElement` 必须有构造器（首版缺失，见 §6 失败记录） |
| 4 | `trackValueOnNode` 要求 `node.constructor.prototype.value` 具备 get/set，且 `node.hasOwnProperty('value')` 为假 | `value` 必须是**原型访问器**，不能是实例自有属性 |
| 5 | `isTextInputElement` 按 `nodeName` + `supportedInputTypes[elem.type]` 判定 | `INPUT` 元素需有 `nodeName`，且 `type` 默认 `text` |
| 6 | `setTextContent` 读写 `firstChild` / `lastChild` | 元素需提供 `firstChild` / `lastChild` |
| 7 | React 17+ 把委托监听器挂在 `createRoot` 容器上 | 事件必须真实冒泡到容器：`dispatchDomEvent` 沿 `parentNode` 链逐级调用监听器并更新 `currentTarget`，尊重 `bubbles` 与 `stopPropagation` |
| 8 | 受控 input 的 `updateValueIfChanged` 依赖实例级值跟踪器 | 必须用**原型 setter** 写值绕过跟踪器 setter（等价于真实用户输入），否则 `onChange` 不触发 |

### 3.3 行为保真边界（本次实际做到的）

- **真实挂载**：`createRoot(container)` 渲染真实的 `AuditPage`，经 `@/components/ConsoleContext` 合成身份、`@/api/client` 隔离 API 返回；**没有**用源码字符串检查，**没有**在测试里复制状态机。
- **受控输入真实触发 handler**：`fireInput` 经原型 setter 写值并冒泡派发 `input`，事件由 React 委托监听器进入组件的 `onChange`；断言里 `query.request_id` 等于键入值，只有真实 handler 更新 draft 才可能成立。
- **查询/点击/提交保留行为语义**：`submit` 在表单上派发（组件 `handleSubmit` 真实执行 `preventDefault`）、`click` 在按钮上派发、翻页与重试沿用组件自身路径。
- **恢复**：`afterEach` 卸载 root、移除挂载节点、`vi.clearAllMocks()`；`afterAll` 调 `restoreAuditDom()` 恢复全部被覆盖的全局。本测试不使用假计时器（`flush()` 用真实宏任务），故无计时器需还原。
- **不做的事情**：不 mock 被测组件、不 mock 权限判定、不 mock `auditSearch` / `auditCorrelation` / `AuditSearchResults`。

## 4. 保留用例映射（逐项核对，不凑新增数量）

交付者对改前副本的机械比较记录如下：断言表达式仅有访问路径替换（`window.document.getElementById(x) as HTMLInputElement` → `auditDomHarness` 的 `inputById(x)`；`window.document.querySelectorAll` → `auditDocument.querySelectorAll`）。这不表示 shim 与 jsdom 的 DOM 语义完整等价；当前文件为未跟踪成果，不能用相对 HEAD 的 git diff 独立重建该改前副本：

```text
断言语句  expect( 计数：原 66 / 新 66
断言目标与期望值 diff：仅 4 处（共 7 行）访问路径差异，无删除、无跳过、无弱化
```

| # | 用例 | 保护的回归 |
| --- | --- | --- |
| 1 | 身份未 ready / 核对失败 / 无 audit 权限时零审计请求，且文案如实区分 | 权限与身份未确认时**零业务查询**；三种文案如实区分（不把「核对失败」说成「正在核对」） |
| 2 | A→B 键碰撞修复：切条件确实发出 B 查询，A 迟到响应不覆盖 B 结果 | 特殊字符条件不碰撞；A 迟到响应不覆盖 B；B 查询确实发出 |
| 3 | 查询同请求：只带 `request_id`、清空其余条件、表单同步、同条件重复不发请求 | 关联查询参数准确；未提交草稿在同条件关联时被正确同步；同条件不重复发请求 |
| 4 | 查询同对象：`resource_type` + `resource_id` 一起查询；缺失标识行无关联动作 | 同对象关联参数；缺失标识不产生关联动作 |
| 5 | 分页沿用同一新条件；加载更多失败保留记录并可同游标重试 | 分页沿用条件；分页失败保留已加载记录、错误提示不冒充全量成功；同游标重试 |
| 6 | 断连无关联动作；XSS 文本按文本渲染不产生元素；全程仅 GET | 断连时无关联动作；后端内容按文本处理；仅 GET、不访问浏览器敏感存储 |
| 7 | 身份变化 tenant / actor-type / permission 清除旧草稿与已应用条件（`it.each` ×3） | 租户变更、操作者身份类型变更、权限核对失败恢复三种情况下，旧草稿/旧结果/旧查询状态全部清除 |
| 8 | 身份切换：旧身份结果不残留 | 组合身份 key 变化使结果组件重建，旧身份结果不残留 |

> 用例 6 的**标题**由「XSS 文本按文本渲染不执行」改为「…不产生元素」。断言本体（`querySelectorAll('img').length === 0`、`textContent` 含原值）**未变**，也没有增删。改名理由：本 shim 不托管 HTML 解析与脚本执行环境，它实际能证明的是「React 没有把该字符串产出为元素」，说成「不执行」属于把浏览器执行能力伪装成 shim 已验证——这正是任务书要求避免的。能力边界见 §7。

## 5. 验证命令与结果

### 5.1 指定命令

```bash
cd apps/web && npm test -- src/pages/AuditPage.test.tsx \
  src/components/audit-search/auditSearch.test.ts \
  src/components/audit-search/auditCorrelation.test.ts
```

结果：`Test Files 3 passed (3)` / `Tests 21 passed (21)`。

其中 `AuditPage.test.tsx` 自身：`Tests 10 passed (10)`（7 个单例 + 1 个 `it.each` × 3），66 条断言语句全部执行通过。

### 5.2 与已有 DOM shim 页面测试同跑（确认无全局污染，未跑全部前端测试）

```bash
npm test -- src/pages/RuntimeBindingsPage.test.tsx src/pages/AuditPage.test.tsx \
  src/components/audit-search/auditSearch.test.ts src/components/audit-search/auditCorrelation.test.ts
```

结果：`Test Files 4 passed (4)` / `Tests 37 passed (37)`。

补充两项更强的污染检验（均通过）：

| 检验 | 命令 | 结果 |
| --- | --- | --- |
| 反序同跑（审计先、shim 测试后） | `npm test -- src/pages/AuditPage.test.tsx src/pages/RuntimeBindingsPage.test.tsx` | `2 passed (2)` / `26 passed (26)` |
| **同上下文**同跑（禁用隔离与文件并行，全局污染最强场景） | `npx vitest run --no-isolate --no-file-parallelism src/pages/AuditPage.test.tsx src/pages/RuntimeBindingsPage.test.tsx` | `2 passed (2)` / `26 passed (26)` |

### 5.3 正式模式构建（不绕过 tsc、不覆盖既有 dist）

```bash
OUT=$(mktemp -d /tmp/cl01-audit-build-XXXXXX)
VITE_DEV_MODE=false npm run build -- --outDir "$OUT"
```

- **构建目录：`/tmp/cl01-audit-build-6fB1Xp`**（独立 mktemp 目录）
- 脚本实际执行为 `tsc -b && vite build --outDir /tmp/cl01-audit-build-6fB1Xp`，**未使用任何跳过 tsc 的手段**
- 结果：`tsc -b` 通过；`vite build` `✓ built in 990ms`；产物 `index-BWTjrQFD.js` 492.66 kB（gzip 146.27 kB）、`index-LdaVZ--3.css` 310.77 kB（gzip 116.35 kB）、`index.html`
- 既有 `dist/` 未被改动：mtime 仍为 `2026-09-25 15:25:13`
- 测试专用代码未进入产物：在产物 JS 中 `grep` `AuditDomEvent|auditDomHarness|restoreAuditDom` 无匹配

### 5.4 依赖检查（针对本次改动/新增文件）

| 检查项 | 结果 |
| --- | --- |
| 指向兄弟项目的 `createRequire` | 无（仅剩说明性注释） |
| `node:module` / `require.resolve` / 父级 `node_modules` 兜底 | 无 |
| `/home/...` 绝对路径依赖 | 无 |
| 运行期安装逻辑（`npm install` / `child_process`） | 无 |
| 新增依赖 / 锁文件改动 | 无 |

## 6. 失败记录（保留过程，说明门禁真实有效）

首次 `tsc -b` 失败，暴露一处 shim 类型缺陷：

```text
src/test-support/auditDomHarness.ts(259,41): error TS2339: Property 'attributes' does not exist on type 'AuditNode'.
src/test-support/auditDomHarness.ts(262,23): error TS2339: Property 'tagName' does not exist on type 'AuditNode'.
```

原因：诊断用 `innerHTML` getter 用 `node.nodeType === 3` 做判别，而两个类的 `nodeType` 都是 `number`，联合类型不收敛。改为 `node instanceof AuditText` 后通过。**注意 `vitest` 不做类型检查，此缺陷只有构建门禁能发现**——这同时说明本次 `tsc -b` 确实是有效门禁、新增文件已被类型检查覆盖。

另有一次测试运行失败：全部用例报 `TypeError: Right-hand side of 'instanceof' is not an object`（`getActiveElementDeep`）+ 级联 `Should not already be working.`。原因是 shim 首版未提供 `window.HTMLIFrameElement`，补上构造器后 10/10 通过。

## 7. 能力边界（明确不覆盖，不伪装为已验证）

以下能力本 shim **不具备**，相关结论仍沿用既有隔离浏览器证据边界，不由本次测试承担：

1. **布局与视觉**：无 `getComputedStyle`、无盒模型、无滚动，不验证任何可见/不可见、焦点可见性、CSS 生效情况。
2. **真实 HTML 解析与脚本执行**：`innerHTML` 只作诊断用途、不解析。用例 6 只证明 React 未把字符串产出为元素，**不证明浏览器不会执行脚本**。
3. **原生表单语义**：不实现原生提交/导航、`FormData`、文件上传。
4. **事件模型简化**：不支持捕获阶段、被动监听、真实的事件重排时序；非冒泡事件仍会到达 `ownerDocument`（简化处理）。本测试未依赖这些细节。
5. **浏览器存储**：shim **未提供** `localStorage` / `sessionStorage` / `document.cookie`。因此「不访问浏览器敏感存储」在本环境的证据是：只有 `getListPage` 被 mock 暴露、实际只调用 `/audit-events` 一种路径；且若组件真去访问上述存储会直接抛错而非静默通过。这弱于真实浏览器下的等价证明，仅作为负向护栏。
6. **网络层**：`getListPage` 被整体替换为受控 Promise，故「仅 GET」是**调用契约层**的证据（mock 面只暴露 GET 列表方法 + 实际 path 断言），不是真实 HTTP 方法记录。

## 8. 未完成项 / 本次未做的验证

1. **未在全新机器执行 `npm ci`**：本次只在本机现有 `node_modules` 上验证。因此**不宣称已完成干净机器验证**；但已从依赖层面消除阻断（本仓可解析到的 jsdom 为零，测试文件不再引用任何本仓外路径）。剩余不确定性只在本仓既有依赖能否顺利安装，与本任务无关。
2. **未纳入 CI / 门禁**：`vitest.config.ts` 等全局配置在禁止改动范围内，未新增任何门禁条目。
3. **未做新的浏览器层验证**：本次无产品 UI 变更，按要求未新增浏览器脚本或截图。CL-06 轮次的「隔离模拟浏览器 9/9」属该轮证据，**不作为本轮执行结果**。
4. **未统一其他页面测试的内联 shim**：`EnvironmentsPage.test.tsx`、`OverviewPage.test.tsx`、`RuntimeBindingsPage.test.tsx` 等各自内联一份 `FakeElement`，存在重复。抽取为公共 shim 会改动任务书禁止修改的文件，且可能影响他人未提交成果，故未做。
5. **未关闭 CL-01 整体**，未提交、未推送、未部署。

## 9. 声明

- 未修改产品代码（`AuditPage.tsx`、身份/权限实现、共享 client、全局配置、`package.json`、锁文件、其他页面测试、浏览器脚本均未动）。
- 未安装任何依赖，未从兄弟仓复制 `node_modules`，未使用绝对路径或环境变量重新定位外部 jsdom。
- 未删除测试、未跳过用例、未改弱断言；用例数与断言数与原文件一致（10 用例执行 / 66 条断言）。
- **本记录只关闭「审计测试外部依赖」这一项阻断，不关闭 CL-01 整体。**
