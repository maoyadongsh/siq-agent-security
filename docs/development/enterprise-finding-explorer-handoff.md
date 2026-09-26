# ENT-018-FINDINGS-UI 风险中心只读筛选与详情 — 交付记录

日期：2026-09-25　执行者：Kimi Code（前端）　状态：**未提交、未部署，待主开发者复核**

## 0. 范围声明

仅完成 ENT-018-FINDINGS-UI：企业风险中心的只读组合筛选、风险详情与加载/失败/空态优化。不负责检测规则、后端状态机、批量处置、自动修复，不声明 ENT-018 整体或项目完成。未删除、弱化或绕过任何已有防攻击能力；确认/解决处置能力完整保留。

## 1. 实际修改 / 新增文件

修改（1 个，允许清单内）：
- `apps/web/src/pages/FindingsPage.tsx` — 接入筛选/列表组件；加载态不再渲染列表；断连时演示占位只读展示且不出处置按钮；处置 handler 与 API 调用逐字保留。

新增（均在允许清单内）：
- `apps/web/src/components/finding-explorer/findingExplorer.ts` — 纯函数：级别/状态中文标签（含"不等于"语义限定）、终态判定、AND 组合筛选、域枚举。
- `apps/web/src/components/finding-explorer/FindingExplorerFilters.tsx` — 级别/状态/域下拉 + 文本搜索 + 清除筛选。
- `apps/web/src/components/finding-explorer/FindingExplorerItem.tsx` — 原生 `details/summary` 详情；操作行位于折叠区外始终可见；级别/状态沿用全局 `.tag` 色系。
- `apps/web/src/components/finding-explorer/FindingExplorerList.tsx` — 列表容器（桌面网格 / ≤1024px 卡片）。
- `apps/web/src/components/finding-explorer/finding-explorer.css` — `finding-explorer-` 前缀局部样式。
- `apps/web/src/components/finding-explorer/findingExplorer.test.ts`、`FindingExplorerItem.test.tsx`。
- `apps/web/src/pages/FindingsPage.test.tsx` — 加载态不出现示例数据/处置按钮。
- `scripts/enterprise-experience/finding-explorer-browser-smoke.py`。
- `docs/evidence/enterprise-auto-onboarding-20260925/finding-explorer-ui/`（截图 + result.json）。
- 本交付记录。

未修改任何共享文件（SimpleTable/FormDialog/PageHeader/DisconnectedNotice/useApiList/全局 CSS/api/types/Layout/App 等均未动）。`apps/web/src/local/pages/FindingsPage.tsx` 的未提交修改属于其他开发者，未触碰。

## 2. 筛选、详情与状态展示规则

- 筛选：级别 AND 处置状态 AND 风险域 AND 文本搜索（风险 ID/规则 ID/关联资产 ID/风险描述/修复建议，小写化 + 去首尾空白）；一键清除；不自动拉取分页。
- 计数行：`匹配 X 条 / 已加载 Y 条；筛选仅覆盖已加载记录，不代表组织全量`；有后续分页时追加说明；不从列表长度推导组织总风险数。
- 详情（原生 details/summary，键盘 Enter 开合）：风险 ID、规则 ID/v 版本、级别（中文+原始值）、风险域、关联资产 ID、风险描述、修复建议、处置状态（含语义限定）、负责人标识、首次/最近观察时间、到期时间、证据 ID；缺失一律"未提供"；证据/资产 ID 仅文本标识，无猜测链接；不展开 risk_acceptance JSON。
- 文案边界：确认≠解决、解决≠独立验证阻断生效、risk_accepted≠风险消除、零条风险≠系统安全；未知枚举值原样显示、不丢记录、不冒充已解决。
- 状态区分：首次加载（提示文案，不渲染列表）/ 后端空列表 / 筛选无匹配（附清除按钮）/ 断连（DisconnectedNotice）/ 加载更多失败（保留数据 + role=alert 错误 + 重试）。

## 3. 原有处置逻辑的保留方式

- `handleAcknowledge` / `handleResolveSubmit` / `runAction` / FormDialog 配置逐字保留；API 仍为 `POST /findings/{id}/acknowledge` 与 `POST /findings/{id}/resolve`（body `{evidence_ref}`），未增删字段。
- 按钮经 `renderActions` 回调注入新列表项的操作区（折叠区之外，始终可见）；busy 禁用、必填校验、危险按钮、错误提示、成功刷新、终态（resolved/risk_accepted 显示"已终态"无按钮）全部保留。
- 断连与演示占位态不注入 renderActions：占位数据明确标注"非真实已发现风险"且无处置入口。
- 解决弹窗恢复逻辑未改：打开重置字段、必填内联报错、失败不关弹窗、成功才关闭。

## 4. 视觉风格保持

复用既有设计令牌（--siq-primary/--card/--border/--text-secondary 等）、`.tag` 状态色系、`.btn-sm/.btn` 按钮、`mono`、`muted-text`、`list-coverage`、`list-more`；无新 UI 依赖；焦点可见（`:focus-visible` 描边）；状态除颜色外均有文本标签；长标识 `overflow-wrap:anywhere` 换行。断点 ≤1024px 卡片布局（1024/768/375 实测无溢出），桌面 1280/1440 保留对齐网格便于比较。

## 5. 测试命令与实际结果

```
cd /home/maoyd/siq/siq-agent-security/apps/web
npm test            # Test Files 75 passed (75)，Tests 491 passed (491)（含本次新增 3 个测试文件、19 项）
npx tsc -b          # 通过
git diff --check    # 干净；新增未跟踪文件已单独查行尾空白
```

构建：**标准 `npm run build` 当前因并行开发者（Qwen）未完成的 `OverviewPage.tsx` 第 30 行 `import './enterprise-overview/overview.css'`（应为 `@/components/...`）而失败**，该文件在禁止修改清单内，未触碰。验证构建改用临时配置 `/tmp/siq-fx-vite.config.mjs`（仅把该 specifier 映射到真实文件 `src/components/enterprise-overview/overview.css`，不改工作树）：
```
npx vite build --config /tmp/siq-fx-vite.config.mjs --outDir /tmp/siq-finding-explorer-kimi-build-jIGQNM   # 通过
```

## 6. 浏览器验收结果与截图

```
python3 scripts/enterprise-experience/finding-explorer-browser-smoke.py \
  --web /tmp/siq-finding-explorer-kimi-build-jIGQNM \
  --out-dir docs/evidence/enterprise-auto-onboarding-20260925/finding-explorer-ui
# passed: true，14/14 检查通过；临时服务与浏览器均已在 finally 中停止
```

截图（已逐一查看，内容可见待验项）：
- `/home/maoyd/siq/siq-agent-security/docs/evidence/enterprise-auto-onboarding-20260925/finding-explorer-ui/desktop-1280.png`（筛选条 + 网格列表 + 已展开的 R-D 详情）
- `.../mobile-375.png`（卡片布局，无溢出）
- `.../mid-768.png`（中等宽度卡片布局）
- `.../resolve-dialog.png`（解决确认弹窗：必填证据、危险确认按钮）
- `.../result.json`（检查项与模拟写请求记录）

## 7. 模拟请求的准确说明

- 阶段 A（只读）：断言业务写请求为 **0**（`a_readonly_zero_writes`）。
- 阶段 B（处置回归）：共 3 次模拟写请求，全部被 Playwright 拦截、未出本机：
  1. `POST /api/v1/findings/fnd-1/resolve`，body 恰为 `{"evidence_ref": "repair-ticket:SEC-123"}`（合成成功）；
  2. `POST /api/v1/findings/fnd-1/acknowledge`，body `{}`（合成成功并触发刷新）；
  3. `POST /api/v1/findings/fnd-3/acknowledge`（合成 500 失败，页面保持错误提示、记录仍显示 open）。
- 未填写证据提交与取消弹窗均断言 0 写请求。真实业务写请求始终为零；本测试不构成生产验收。

## 8. 未完成项、范围外发现与验证限制

- 标准 `npm run build` 被 Qwen 的 OverviewPage 未完成 import 阻断（见第 5 节）；待其修复后可直接复跑标准构建，本任务代码自身 tsc/vite 均通过。
- 共享 hook 既有问题（沿用上一任务记录，仍未改）：`useApiList.ts:74-90` 加载更多失败后 error 滞留至下次成功；`useApiList.ts:70` reload 期间旧 rows 保留——本页以 loading 分支兜底，其他页面若直接渲染 rows 可能把旧记录当当前结果。
- 375/768/1024/1280/1440 五视口同时校验了 `document.documentElement` 与 `.content` 的 scrollWidth/clientWidth，未用 overflow:hidden 伪装。
- 浏览器冒烟为合成 fixture，不证明后端授权、检测有效性或生产环境状态。
- 移动端卡片断点取 1024px（覆盖 768/1024 平板档）；如需 1024 显示完整表格可后续调优。

## 9. 复核提示

未提交、未推送、未部署；以上改动待主开发者复核后再决定是否入库。

## 10. 主开发者验收与修复（2026-09-25）

结论：本次风险中心筛选与详情子任务通过源码及隔离模拟 UI 验收；不代表 ENT-018 整体、后端授权或生产验收完成。用户明确要求验收并直接修复问题。本轮未提交、未推送、未部署，未读取秘密或调用真实业务接口。

### 已复现并修复

- 未知枚举恰为 `__proto__`、`constructor`、`toString` 时，普通对象查表会读取原型属性；其中 `__proto__` 导致 React 报 `Objects are not valid as a React child`。先补测试复现 4 项失败，再将标签及 CSS 类查表限定为自身属性；未知值仍按纯文本展示。没有改变风险状态机或业务接口。
- 原浏览器短标识夹具通过，但新增 200 字符规则、资产、负责人、风险域、证据标识并展开详情后，375px 的 `.content` 横向溢出。修复专用 CSS 的表单收缩、网格最小宽度和标签/详情换行；未使用隐藏溢出掩盖内容。
- 浏览器脚本补充未知枚举、长标识、展开详情的五视口检查、分页重试后错误清除、无页面权限不加载风险、身份失败及重新核对权限。新增拒绝场景最初误把合同要求恒为 true 的 workspace/settings 设为 false，触发协议拒绝而非页面拒绝；已修正合成身份夹具，未修改身份校验实现。

React 技能用于检查筛选派生状态和条件渲染；保留渲染时计算筛选结果，不新增同步 effect 或依赖。样式继续复用暖纸底、墨蓝、深金、现有字体、语义标签、按钮和 FormDialog；不改共享 CSS。

### 本轮修改文件

- `apps/web/src/components/finding-explorer/findingExplorer.ts`
- `apps/web/src/components/finding-explorer/FindingExplorerItem.tsx`
- `apps/web/src/components/finding-explorer/finding-explorer.css`
- `apps/web/src/components/finding-explorer/findingExplorer.test.ts`
- `apps/web/src/components/finding-explorer/FindingExplorerItem.test.tsx`
- `scripts/enterprise-experience/finding-explorer-browser-smoke.py`
- 本交付记录。

本轮未修改 FindingsPage 的处置 handler、App 路由、ConsoleContext、共享 hook、后端或其他开发者负责的总览/审计文件。

### 独立验证结果

在 `apps/web` 执行：

```bash
npm test
npm test -- src/components/finding-explorer src/pages/FindingsPage.test.tsx
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-findings-review-standard-20260925
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=true VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-findings-review-mock-only-20260925
```

- 全量：78 文件 / 524 项通过；风险中心定向：3 文件 / 18 项通过（本轮新增 4 项）。以上为本次实跑数字，不沿用原交付的增量计数。
- 标准 `tsc -b && vite build` 通过，无临时 import 映射；第 5/8 节的总览构建阻塞为交付时历史状态，当前已不存在，本轮未改总览文件。
- 第二份构建仅用于模拟身份验收，不可发布；两份构建均为独立临时目录，未覆盖运行服务产物。
- `git diff --check` 通过；新增文件另检查行尾空白。
- 当前共享 hook 已在成功加载时清除 error；本轮浏览器验证分页失败后的成功重试不残留警告，第 8 节不应再解释为当前缺陷。reload 保留 rows 的实现不变，风险页 loading 分支不展示旧行。

在仓库根目录执行：

```bash
python3 scripts/enterprise-experience/finding-explorer-browser-smoke.py --web /tmp/siq-findings-review-mock-only-20260925 --out-dir /tmp/siq-findings-review-accepted-evidence-20260925
```

结果：16/16 通过；只读阶段零写，处置阶段仍为 3 次逐条记录的拦截模拟 POST，解决载荷仍恰为 `{evidence_ref}`；无未捕获异常，临时服务已停止。375/768/1024/1280/1440 下同时检查文档与 `.content` 宽度，包含长文本展开详情。

最终证据位于 `/tmp/siq-findings-review-accepted-evidence-20260925/`：`result.json`、`desktop-1280.png`、`mobile-375.png`、`mid-768.png`、`resolve-dialog.png`。四张截图已实际查看，确认桌面/移动布局及既有设计风格。临时目录可能被系统清理；原交付仓库内证据仍保留且未覆盖。

限制：本轮是源码与合成 API 浏览器验收，不证明真实 IAM 授权、真实风险处置审计或检测/防御效果；未部署，无生产状态变更。
