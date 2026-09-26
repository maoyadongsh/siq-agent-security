# ENT-018-BINDINGS-UI 子任务交付记录：运行时绑定列表可视化与登记表单可靠性优化

日期：2026-09-25
范围：仅 ENT-018-BINDINGS-UI 子任务（`/runtime-bindings` 页的列表筛选/详情可视化与登记表单可靠性）。
**未提交、未部署，待主开发者复核。**

## 1. 实际修改/新增文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `apps/web/src/pages/RuntimeBindingsPage.tsx` | 修改 | 列表 AND 组合筛选（仅已加载记录）；区分 首次加载/成功空/筛选无匹配/首次失败/加载更多失败；登记表单按需加载环境/资产/实例，逐项表达 未加载/加载中/成功空/成功有数据/失败+针对性重试；资产切换用请求序号（seq）防竞态；登记前派生校验；保留原登记/吊销 API 载荷与失败语义、吊销确认模态、busy 防重复提交 |
| `apps/web/src/components/runtime-binding-explorer/runtimeBindingExplorer.ts` | 新增 | 纯函数：`filterBindings`（AND 组合+文本搜索）、`listBindingBackends`/`listBindingEnvironments`（仅已加载数据推导）、`statusTagClass`（`Object.hasOwn` 防原型继承）、`textOrMissing`、选项状态 `optionHasId`、实例请求竞态模型 `beginInstanceRequest`/`invalidateInstanceRequest`/`applyInstanceResponse`/`instanceBelongsToCurrentAgent` |
| `apps/web/src/components/runtime-binding-explorer/RuntimeBindingFilters.tsx` | 新增 | 筛选条：状态/后端/环境下拉 + 文本搜索 + 清除筛选；`role="group"` 与可达性标签 |
| `apps/web/src/components/runtime-binding-explorer/RuntimeBindingItem.tsx` | 新增 | 单条绑定原生 `details/summary`（键盘可展开）；只展示后端已有字段，缺失显示「未提供」；**不展开/不序列化/不复制 attestation，不渲染 tenant_id**；active/revoked 语义说明；`renderActions` 由页面注入（返回 null 时不渲染操作区） |
| `apps/web/src/components/runtime-binding-explorer/RuntimeBindingList.tsx` | 新增 | 列表容器：`role="list"`、8 列表头（`aria-hidden`）、行 `role="listitem"` |
| `apps/web/src/components/runtime-binding-explorer/runtime-binding-explorer.css` | 新增 | 仅 `rb-explorer-` 前缀局部样式（筛选条/列表/详情网格/表单提示/1024px 以下折叠）；未改共享全局 CSS |
| `apps/web/src/components/runtime-binding-explorer/runtimeBindingExplorer.test.ts` | 新增 | 17 项单元测试（AND 筛选/清除/已加载计数、同名不合并、未知枚举+原型名安全、缺失字段、选项状态、实例请求竞态纯模型） |
| `apps/web/src/components/runtime-binding-explorer/RuntimeBindingItem.test.tsx` | 新增 | 10 项组件测试（`renderToStaticMarkup`：字段原文/未提供、attestation 不展开、无 tenant_id、原型名安全、active/revoked 语义、XSS 转义、renderActions 契约、筛选条推导） |
| `apps/web/src/pages/RuntimeBindingsPage.test.tsx` | 新增 | 14 项页面行为测试（最小 DOM shim + react-dom/client 真实渲染；mock `@/api/client` 全量；列表状态区分、表单选项状态、资产切换竞态 A→B 乱序、登记/吊销载荷与失败语义） |
| `apps/web/src/pages/runtimeBindingPageDomShim.ts` | 新增 | 页面测试专用最小 DOM shim（node 环境无 jsdom/testing-library 且本任务不安装依赖）；必须在 react/react-dom 之前 import（react-dom 模块加载期计算 `canUseDOM`/`isInputEventSupported`） |
| `scripts/enterprise-experience/runtime-binding-explorer-browser-smoke.py` | 新增 | 隔离浏览器验收脚本（127.0.0.1 静态服务 + 拦截 mock API + 全合成 fixture，VITE_DEV_MODE 模拟身份构建，仅测试用途、不可发布）；两阶段：只读（断言 0 业务写）+ 业务回归（登记/吊销全 mock，记录 path/method/payload） |
| `docs/development/enterprise-runtime-binding-ui-handoff.md` | 新增 | 本交付记录 |

未修改（任务禁止清单）：`App.tsx`、`Layout.tsx`、`enterpriseNav.ts`；总览/安全/权限/资产/技能/审计页；`components/onboarding/**`、`EnvironmentsPage.tsx`；`api/client.ts`、`api/types.ts`、`api/consoleContext.ts`；`ConsoleContext.tsx`、`useApiList.ts`；`ConfirmDialog.tsx`、共享表格/共享全局 CSS；`local/**`；后端/DB/Edge/Connector/安装器/安全规则；批量预览/预约/执行文件；`package.json`/锁文件；共享进度台账/任务书。未安装任何新依赖。工作树中其他开发者的未提交改动一律未触碰，按当前状态对待。

## 2. 列表与表单状态矩阵

列表（`useApiList` 集成，不绕过共享 hook）：

| 状态 | 展示 | 关键断言 |
| --- | --- | --- |
| 首次加载 | 「正在加载运行时绑定…加载完成前不展示列表或计数。零条绑定不代表当前系统安全。」 | 不显示伪空/伪零 |
| 成功空 | 「后端成功返回空列表：当前没有已登记的运行时绑定。零条绑定不等于当前系统安全。」+ 匹配 0 条/已加载 0 条 | 明确成功空，不冒充失败 |
| 成功有数据 | 筛选条 + 「匹配 X 条 / 已加载 Y 条；筛选仅覆盖已加载记录，不代表组织全量。」+ `coverageText` + 列表 | 计数仅覆盖已加载记录 |
| 筛选无匹配 | 「当前筛选条件下无匹配项（已加载 N 条中 0 条匹配）」+ 清除筛选按钮 | 提供清除入口 |
| 首次失败 | `DisconnectedNotice`（未连接 + 重试连接） | 错误+重试，不冒充空 |
| 加载更多失败 | 保留已加载数据 + 「{error}（已保留此前成功加载的数据，不代表全部加载成功）」+ 加载更多按钮 | 显式不完整，可重试 |
| 重试成功 | 清除错误、恢复/追加数据 | 错误清除 |

表单（按需加载，打开表单才请求环境/资产；筛选/展开不触发额外请求）：

| 选项 | idle | loading | 成功空 | 成功有数据 | 失败 |
| --- | --- | --- | --- | --- | --- |
| 环境 | 下拉禁用「未加载」 | 禁用「加载中…」 | 「后端成功返回空列表：当前没有可用环境。」 | 可选 | 「环境加载失败：{msg}」+ 重试 |
| 资产 | 同上 | 同上 | 「…当前没有可绑定的已纳管资产。」 | 仅已纳管资产可选 | 「资产加载失败：{msg}」+ 重试 |
| 实例 | 禁用「先选择资产」 | 禁用「加载中…」 | 「该资产暂无已发现的运行时实例，无法登记绑定。」 | 仅当前资产本次结果可选 | 「实例加载失败：{msg}」+ 重试（针对性，nonce 重拉） |

登记按钮：`canCreate = !optionsLoading && formValidationError === null`；校验为渲染期派生（非 state），失败时按钮禁用并显示原因。

## 3. 请求竞态如何消除

- **实例级联（资产切换）**：`instanceRef` 为权威序号来源，`instanceState` 为镜像（`commitInstance` 同步两者）。每次开始/失效请求 `seq+1`；`applyInstanceResponse` 仅当 `responseSeq === state.seq` 时应用，旧序号（成功或失败）一律忽略。effect 清理置 `active=false`，卸载/切换后迟到响应不写状态。
- **A→B 乱序**：选 A（seq=1）→ 立即选 B（seq=2，A 在途）→ B 先返回（seq=2 应用）→ A 后返回（seq=1 忽略）。最终为 B。A 旧请求失败同样被忽略，不覆盖 B 成功。
- **清空资产/关闭表单/卸载**：`invalidateInstanceRequest`（seq+1、回到 idle）使在途实例响应失效；环境/资产用 `envGenRef`/`agentGenRef` 递增同理，关闭表单时递增并重置为 idle，在途响应被忽略。
- **针对性重试**：实例重试先 `invalidateInstanceRequest` 再递增 `instanceNonce`（agentId 不变也能重新触发加载 effect）。
- 纯模型（`beginInstanceRequest`/`applyInstanceResponse`/`invalidateInstanceRequest`）有 17 项单测覆盖上述全部路径；页面级有 3 项竞态行为测试（A→B 乱序、A 旧失败不覆盖 B、清空资产旧结果失效）。

## 4. 登记/吊销 API 与权限边界如何保留

- `api.createRuntimeBinding({ environment_id, agent_instance_id, backend, backend_target_id, attestation? })` 载荷字段不变；`backend` 默认 `openshell-cli`；`backend_version` 仅在填写时以 `attestation.backend_version` 传入。
- `api.revokeRuntimeBinding(id, 'web-console-manual-revoke')` reason 固定不变。
- 成功：关闭表单 + 重置 + `bindings.refresh()`；失败：保留输入 + 明确报错（`ApiError.message`）。
- 吊销：仅 active 行显示吊销按钮；`ConfirmDialog` 危险确认；`busyId` 防重复提交；成功刷新、失败不冒充成功（`actionError`）。
- 前端校验仅避免误操作（选项已成功加载、当前选择属于本次成功结果、实例属于当前资产本次结果），**不替代后端检查**；`BINDABLE_ASSET_STATUS` 集合未改；不猜测/合成实例、不自动选首项。
- 权限边界：`/runtime-bindings` 的访问控制在 `Layout` 层（`routeAccessKey`/`canVisit`，access key `runtime_bindings`），本任务未触碰 `Layout`；无权限时导航不出现入口、直接访问被拒（浏览器验收已验证）。
- 筛选/展开不触发任何业务写；`renderActions` 注入模式保留（业务处理器留在页面）；无批量操作、无新业务 API、无硬编码 admin。

## 5. 样式保留

- 沿用现有暖纸/墨蓝/深金主题变量（`--siq-primary`、`--card`、`--input-border` 等），未引入新设计系统/组件库/图标。
- 全部新样式仅 `rb-explorer-` 前缀 + 专用根类 `rb-explorer-root`；未改共享 CSS。
- 可达性：控件有可达名称（`aria-label`/`role="group"`/`role="list"`/`role="status"`/`role="alert"`）；`details/summary` 键盘可展开；`:focus-visible` 可见焦点环。
- 视口 375/768/1024/1280/1440px 验证 `documentElement` 与 `.content` 的 `scrollWidth - clientWidth ≤ 0`（长 ID/长后端值/展开详情/表单/吊销对话框场景），无 `overflow:hidden` 裁剪伪装。

## 6. 测试命令、实际数量、失败与修复过程

命令：`cd /home/maoyd/siq/siq-agent-security/apps/web && npm test`（vitest run，node 环境）。

本任务新增 41 项测试，全部通过：

| 文件 | 数量 |
| --- | --- |
| `runtimeBindingExplorer.test.ts` | 17 |
| `RuntimeBindingItem.test.tsx` | 10 |
| `RuntimeBindingsPage.test.tsx` | 14 |

全量套件（含工作树中其他开发者的并行改动）：101 文件 / 839 项全部通过。

失败与修复过程（均为测试基础设施/断言问题，非实现缺陷；未删除测试、未放宽安全断言、未跳过失败用例）：

1. **DOM shim 选择器**：初版 `querySelector` 仅支持单类选择器，`.permissions-toolbar button`、`.rb-explorer-field-search input`、`button`（标签）返回 null → 扩展为支持 标签/`.class`/`tag[attr]`/`tag[attr="val"]` 及后代复合选择器。
2. **React 事件委托**：React 18 按 `nodeName` 判断元素类型、按 `supportedInputTypes[elem.type]` 判断文本输入 → shim 补 `nodeName`/`type` getter。
3. **`isInputEventSupported` 模块加载期计算**：react-dom 在模块加载期计算 `canUseDOM`（检查 `window.document`）与 `isInputEventSupported`（`'oninput' in document`）→ 将 shim 抽为独立模块 `runtimeBindingPageDomShim.ts` 并在 react/react-dom 之前 import；window 补 `document`；document 用 Proxy `has` 陷阱对 `on*` 键返回 true。
4. **门户事件**：`ConfirmDialog` 经 `createPortal(document.body)`，委托监听在 body → body 补 `ownerDocument`，click 辅助函数同时派发 container 与 body 监听。
5. **`vi.mock` 提升**：工厂引用顶层 `ApiError` 触发「Cannot access before initialization」→ 改用 `vi.hoisted`。
6. **断言修正**：「已加载 0 条」跨文本节点拆分 → 断言改为匹配实际渲染；「选择不匹配」断言改为首个未通过项（实例）；登记失败 mock 改为抛真实 `ApiError` 实例（页面据 `instanceof ApiError` 展示后端消息）。

## 7. 标准构建结果

命令：`env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-runtime-binding-ui-build`

结果：`tsc -b && vite build` 成功（`✓ built in ~1s`），产物含 `index-*.js`（438.67 kB / gzip 133.91 kB）与 `index-*.css`（306.73 kB / gzip 115.75 kB）；`rb-explorer` 样式已打包进 `index-*.css`。构建前修复了两处类型错误：页面未使用的 `hasActiveBindingFilters` 导入（移除）、测试 `defer<T>()` 签名（改为接受可选初值）。

## 8. 浏览器验收报告与截图

命令：`/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/runtime-binding-explorer-browser-smoke.py --output /tmp/siq-runtime-binding-ui-evidence-20260925-run3`

结果：**39/39 检查通过**（`report.json` 中 `passed: true`，`page_errors: []`）。

报告与截图绝对路径：

- 报告：`/tmp/siq-runtime-binding-ui-evidence-20260925-run3/report.json`
- 桌面展开详情截图：`/tmp/siq-runtime-binding-ui-evidence-20260925-run3/bindings-desktop-expanded.png`
- 375px 表单+吊销对话框截图：`/tmp/siq-runtime-binding-ui-evidence-20260925-run3/bindings-375-form-dialog.png`
- 构建日志：`/tmp/siq-runtime-binding-ui-evidence-20260925-run3/build.log`

覆盖：加载/空/失败重试；列表筛选（AND/文本/无匹配/清除）；分页失败+恢复；键盘展开详情；无权限入口不出现+直接访问被拒；环境/资产/实例各自失败+恢复；乱序实例响应（A 慢 B 快，最终 B）；表单清空资产/关闭重开无跨资产残留；登记/吊销回归；五个视口+长文本+展开+表单+对话框无横向溢出；无未捕获异常。

## 9. 模拟写请求的精确描述

阶段一（只读）：0 业务写请求（断言通过）。
阶段二（业务回归，全部 mock，记录 path/method/payload，断言无真实写）：

| # | method | path | payload |
| --- | --- | --- | --- |
| 1 | POST | `/api/v1/runtime-bindings` | `{"environment_id":"env-1","agent_instance_id":"inst-1","backend":"openshell-cli","backend_target_id":"sandbox-finance-01"}`（登记成功） |
| 2 | POST | `/api/v1/runtime-bindings` | `{"environment_id":"env-1","agent_instance_id":"inst-1","backend":"openshell-cli","backend_target_id":"sandbox-finance-02"}`（登记失败，保留输入） |
| 3 | POST | `/api/v1/runtime-bindings/{LONG_ID}/revoke` | `{"reason":"web-console-manual-revoke"}`（吊销成功） |
| 4 | POST | `/api/v1/runtime-bindings/{LONG_ID}/revoke` | `{"reason":"web-console-manual-revoke"}`（吊销失败，不冒充成功） |

`{LONG_ID}` 为合成长绑定 ID（`rb-` + 64 字符）。写请求仅限登记/吊销两类，无其他业务写（断言通过）。未登记/吊销真实绑定、未扫描真实用户目录。

## 10. 未完成项 / 已知限制 / 范围外发现

- **分页限制**：列表接口仅返回受限首页（`x-siq-list-*` 头）；本页不宣称全量、不循环扫描，加载更多经 `loadMore` 游标追加。若后端仅返回首页，页面以 `coverageText` 明确「本页 vs 全量」，不冒充完整列表。
- **模拟验收边界**：浏览器验收为 VITE_DEV_MODE 模拟身份 + 127.0.0.1 隔离 mock + 全合成 fixture，**不证明生产 IAM、目标真实性或防护效果**；VITE_DEV_MODE=true 构建不得部署到真实服务。
- **DOM shim 范围**：`runtimeBindingPageDomShim.ts` 仅覆盖 React 18 渲染/事件委托所需，不承担像素级/键盘/视口断言（这些由隔离浏览器测试覆盖）；如未来引入 jsdom/testing-library 可替换。
- **范围外发现（未处理，仅记录）**：工作树存在其他开发者的并行未提交改动（含 `packages/contracts/enterprise-runtime-binding-identity.v1.md` 等，时间戳早于本任务）；本任务一律未触碰。
- 未提交、未部署。

## 11. 状态声明

**未提交、未部署，待主开发者复核。** 本记录仅声明 ENT-018-BINDINGS-UI 子任务状态，不代表 ENT-018 整体、runtime-security 或整个项目已完成。
