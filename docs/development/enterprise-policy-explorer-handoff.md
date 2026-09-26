# ENT-018-POLICIES-UI 策略中心只读筛选、详情与分页 — 交付记录

日期：2026-09-25　执行者：Kimi Code（前端）　状态：**未提交、未部署，待主开发者复核**

## 0. 范围声明

仅完成 ENT-018-POLICIES-UI：策略中心列表展示与交互优化。未实现策略编辑器、审批、部署、权限收窄/撤销/批量执行；未改动策略创建业务逻辑。不声明 ENT-018 整体、策略生效能力或项目整体完成。

## 1. 实际修改 / 新增文件

修改（1 个，允许清单内）：
- `apps/web/src/pages/PoliciesPage.tsx` — 接入筛选/列表组件与分页 UI；创建表单与 `onCreate` 业务逻辑保持原语义；页面侧派生"加载更多重试成功清除错误"。

新增：
- `apps/web/src/components/policy-explorer/policyExplorer.ts` — 纯函数：档位标签（原型安全查表）、`extractAgentIds` 白名单提取、状态枚举提取、AND 组合筛选。
- `apps/web/src/components/policy-explorer/PolicyExplorerFilters.tsx` — 档位/状态/未覆盖项/搜索/清除。
- `apps/web/src/components/policy-explorer/PolicyExplorerItem.tsx` — 原生 details/summary 详情。
- `apps/web/src/components/policy-explorer/PolicyExplorerList.tsx`、`policy-explorer.css`（`policy-explorer-` 前缀）。
- `apps/web/src/components/policy-explorer/policyExplorer.test.ts`、`PolicyExplorerItem.test.tsx`、`apps/web/src/pages/PoliciesPage.test.tsx`。
- `scripts/enterprise-experience/policy-explorer-browser-smoke.py`。
- `docs/evidence/enterprise-auto-onboarding-20260925/policy-explorer-ui/`（截图 + result.json）。
- 本交付记录。

## 2. 筛选、分页和详情行为

- AND 筛选：期望档位（audit_only/warn/block）、策略状态（选项动态取自已加载记录真实值，含未知枚举）、后端未覆盖项（全部/有报告项/报告列表为空）、文本搜索（名称/策略 ID/目标资产 ID，小写+去空白）；一键清除。
- 计数行：`匹配 X 条 / 已加载 Y 条；筛选仅覆盖已加载记录，不代表组织全量`，有后续分页时追加说明；接入 useApiList 的 coverageText/hasMore/loadingMore/loadMore，未修改共享 hook。
- 状态区分：加载中（不显示伪零）、成功空列表、筛选无匹配（附清除按钮）、首次失败（DisconnectedNotice）、加载更多失败（保留记录 + role=alert 错误）、重试成功清除错误（页面侧按"加载尝试"派生：loadingMore 升起记录起点，结束时记录数增长或 listMeta.truncated=false 判定成功）。
- 详情（details/summary，键盘可开合，焦点可见 outline）：策略 ID、名称、版本、期望档位、后端状态原文、目标资产 ID 列表、未覆盖项列表、更新时间；ID 仅文本标识无链接。

## 3. 「期望策略」与「实际生效」的语义边界

- block 档位原实现用 `state-tag effective`（生效绿）展示，已取消：改为中性 `state-tag` + 文字「期望：阻断/告警/仅审计」，不出现的 effective/已生效标签。
- 详情固定说明：「这里展示期望策略；实际生效情况需结合审批、部署及独立后端读回核对。不因状态、档位、版本或未覆盖项为空而推断已部署、已生效或已保护。」
- 未覆盖项空列表文案：「本条响应未列出未覆盖项，不等于全部支持或已验证兼容」。
- PolicyRow 仅列表投影字段：未新增网络规则/审批人/部署效果等猜测数据，未额外调用详情/部署/扫描接口。

## 4. selector 展示白名单与异常处理

`extractAgentIds` 只读 selector 自身 `agent_ids`（`Object.hasOwn` 判定，原型链继承值不算）；仅字符串数组才展示：缺失/null/非对象 →「未提供」，非字符串数组 →「格式异常」，空数组 →「空列表（不代表全部资产）」。不遍历/序列化整个 selector，labels/system_ref 等不展示、不进入搜索（有单测锁定）。重复 ID 用 `index:id` 作 key，无 React key 警告（浏览器断言 console 无 same-key 错误）。标签查表 `safeLookup` 原型安全：`__proto__`/`constructor`/`toString` 原样显示不崩溃（单测+浏览器均验证）。

## 5. 创建策略流程保持

表单字段、默认档位 block、必填（名称+目标资产）、`onCreate` 载荷（`{name, selector:{agent_ids:[id]}, network?, enforcement_mode}`，端点为空时 network 键不出现，含 binary_paths/purpose 固定字段）、creating 禁用、成功后重置/关闭/刷新、失败报错不关表单——全部逐字保留，浏览器回归逐条断言（见第 10 节）。

## 6. 前端风格保持

复用设计令牌与既有类（`state-tag`、`btn-sm/btn-primary`、`form-box`、`list-coverage`、`list-more`、`sync-err`、`muted-text`）；新 CSS 全部 `policy-explorer-` 前缀；无新依赖；断点 ≤1024px 卡片布局，桌面 1280/1440 对齐网格。

## 7. 测试命令、数量、失败及修复

```
cd /home/maoyd/siq/siq-agent-security/apps/web
npm test
```

- 我的文件：`npx vitest run src/components/policy-explorer src/pages/PoliciesPage.test.tsx` → 3 文件 15 项全部通过。
- 全量 `npm test`：691 项中 677 通过，**14 项失败全部位于 Claude Code 正在开发的 `RuntimeBindingsPage.test.tsx` 与 `runtime-binding-explorer/`**（其进行中改动，禁止触碰，未介入）。执行前我的基线（564 项）全绿；我的文件无新增失败。
- 开发中修复记录：初版 3 项失败（测试断言误伤否定语义句中的「已生效/全部支持」字样；漏 import MODE_LABELS），已修正断言为检查肯定性标签缺失；1 项 tsc 未使用导入已清理。

## 8. 标准构建结果

任务指定命令：
```
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false \
  npm run build -- --outDir /tmp/siq-policy-explorer-build
```
**当前工作树下无法完整通过**：`tsc -b` 阶段报错全部位于其他开发者进行中文件（`RuntimeBindingsPage.tsx`/`RuntimeBindingsPage.test.tsx` 7 处 TS 错误）；vite 阶段另有 Qwen 的 `OverviewPage.tsx` 第 30 行暂不可解析的 `./enterprise-overview/overview.css` import。两者均在禁止修改清单内，未触碰。
- 我的文件 `tsc` 无任何错误（单独 grep 确认）。
- 验证构建：`npx vite build --config /tmp/siq-fx-vite.config.mjs --outDir /tmp/siq-policy-explorer-build` 通过（临时配置仅把 Qwen 的 CSS specifier 映射到真实文件，不改工作树；产物仅测试用、不可发布、未部署）。

## 9. 浏览器报告与截图

```
python3 scripts/enterprise-experience/policy-explorer-browser-smoke.py \
  --web /tmp/siq-policy-explorer-build \
  --out-dir docs/evidence/enterprise-auto-onboarding-20260925/policy-explorer-ui
# passed: true，14/14 检查通过；临时服务与浏览器均在 finally 中停止
```
截图（已实际查看）：
- `/home/maoyd/siq/siq-agent-security/docs/evidence/enterprise-auto-onboarding-20260925/policy-explorer-ui/desktop-1280-detail.png`（含展开详情）
- `.../mobile-375.png`（卡片布局无溢出）
- `.../result.json`

## 10. 模拟写请求记录

阶段 A 只读：业务写请求 **0**（断言通过）。阶段 B 创建回归共 3 次 POST，全部被 Playwright mock 拦截，无真实创建：
1. `POST /api/v1/policies`，载荷 `{name:'财务智能体网络策略 v2', selector:{agent_ids:['agt-finance-02']}, network:[{endpoint:'api.example.com:443', effect:'allow', binary_paths:['/usr/bin/curl'], purpose:'web-created'}], enforcement_mode:'block'}`（合成成功，表单关闭并刷新）；
2. `POST /api/v1/policies`，载荷无 `network` 键（端点留空原语义）；
3. `POST /api/v1/policies`（合成 500，表单保持打开并显示错误）。

## 11. 未完成项、已知限制与范围外问题

- 标准 `npm run build` 被 Claude Code（RuntimeBindingsPage tsc 错误）与 Qwen（OverviewPage CSS import）进行中改动阻断，待其完成后可直接复跑标准命令；本任务代码自身 tsc/vite 均通过。
- 共享 hook 范围外问题（沿用前两次记录）：`useApiList.ts` append 成功后不清除 error —— 本页以渲染期派生逻辑实现"重试成功清除错误"，未改共享 hook；根治需主开发者处理。
- 空最终页（成功但 0 条）会被本页派生逻辑视为"疑似失败"而不主动清除错误提示；fixture 未覆盖此边界，如实记录。
- 浏览器冒烟为合成 fixture，不证明后端授权或生产状态；模拟身份构建仅测试用。

## 12. 复核提示

未提交、未推送、未部署；待主开发者复核。

## 13. 主开发者复核与修复（2026-09-25）

本节是上述交付快照的增量复核，当前结论以本节为准：策略中心专项检查通过，整合构建尚未通过，不构成生产验收。

- 实际复现：分页请求失败后，创建策略成功并刷新列表，页面仍显示旧分页错误。新增浏览器断言在修复前失败（应为 0 个 alert，实际为 1）。
- 原因与修复：当前共享 `useApiList` 已在成功/刷新时清除错误，原交付对 hook 的判断已过时。按 React 技能避免重复派生状态的规则，删除 `PoliciesPage.tsx` 自行缓存的分页错误及加载长度状态，直接显示 hook 的 `error`。未改共享 hook、创建 handler、载荷、CSS 或权限判断。第 2、11 节的旧派生机制及其空最终页限制不再适用于当前实现。
- 回归脚本 `scripts/enterprise-experience/policy-explorer-browser-smoke.py` 新增“分页失败→创建成功→刷新清除旧错误”，沿用原有模拟创建，不增加业务写操作。
- 专项单测：`npm test -- src/components/policy-explorer src/pages/PoliciesPage.test.tsx`，3 文件、15 项通过。
- 全量测试：`npm test`，92 文件中 90 通过、2 失败；691 项中 677 通过、14 失败，失败位于并行开发的 `RuntimeBindingsPage.test.tsx` 与 `RuntimeBindingItem.test.tsx`，未覆盖修改这些文件。
- 标准构建复跑：`env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-policy-review-final-standard-20260925`，仍因运行时绑定页面及其测试的 7 处 TS 错误失败。第 8、11 节所述 Overview CSS 问题未在本轮 Vite 构建重现，不再列为当前已确认阻断项。
- 隔离模拟构建：`env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=true VITE_DEMO_PLACEHOLDERS=false ./node_modules/.bin/vite build --outDir /tmp/siq-policy-review-fixed-mock-20260925` 成功；使用项目原 Vite 配置，跳过类型构建，仅用于模拟验收，不可发布。
- 浏览器：`python3 scripts/enterprise-experience/policy-explorer-browser-smoke.py --web /tmp/siq-policy-review-fixed-mock-20260925 --out-dir /tmp/siq-policy-review-fixed-evidence-20260925`，15/15 通过。只读阶段零写请求，原有 3 次创建 POST 全部由 mock 拦截，未连接真实业务；无未捕获异常，临时服务已停止。
- 截图已实际查看：`/tmp/siq-policy-review-fixed-evidence-20260925/desktop-1280-detail.png`、`mobile-375.png`；报告同目录 `result.json`。保留现有米白、深蓝、金色设计语言，桌面详情与移动卡片可读；五视口无横向溢出检查通过。
- `git diff --check` 通过。未提交、未推送、未部署；仅完成本策略中心子任务专项复核，不代表 ENT-018 整体或项目完成。
