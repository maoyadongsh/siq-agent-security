# CL-06-AUDIT-CORRELATION-UI 交付记录：审计关联检索与查询上下文隔离收口

日期：2026-09-26
范围声明：本记录只覆盖任务书 `docs/development/cl06-qwen-audit-correlation-taskbook.md` 中的 **CL-06-AUDIT-CORRELATION-UI 子任务**（审计关联检索与查询上下文隔离收口）。**不代表 CL-06、ENT-019 或项目整体完成**，也不把本任务当作审计导出、保留治理或完整运行效果链已经实现。

**状态：未提交、未部署，待主开发者复核。**

## 1. 实际修改与新增文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `apps/web/src/components/audit-search/auditSearch.ts` | 修改 | `auditFiltersKey` 改为固定字段顺序 JSON 元组序列化（消除 `&`/`=` 跨字段碰撞）；新增 `identityKey`（租户+操作者无歧义元组序列化） |
| `apps/web/src/components/audit-search/auditCorrelation.ts` | 新增 | 关联操作纯函数层：`auditCorrelationActions` / `auditCorrelationFilters`，缺失/空/异常/超长值返回 null，原值逐字保留 |
| `apps/web/src/components/audit-search/AuditSearchResults.tsx` | 修改 | 真实 connected 结果追加「关联查询」列（原生按钮）；演示占位/断连/加载态不渲染关联按钮；保留 requestSeq/卸载清理 |
| `apps/web/src/components/audit-search/audit-search.css` | 修改 | 仅新增 `audit-correlation-` 前缀局部规则（按钮组换行、375px 纵向排列） |
| `apps/web/src/pages/AuditPage.tsx` | 修改 | 身份键改用 `identityKey`；新增 `handleCorrelate`（同步草稿+已应用、整体替换条件、从第一页重查）；身份核对失败文案如实区分（不再一直「正在核对」） |
| `apps/web/src/components/audit-search/auditSearch.test.ts` | 新增 | 键编码定向测试（含旧实现 A/B 碰撞负例复现） |
| `apps/web/src/components/audit-search/auditCorrelation.test.ts` | 新增 | 关联操作纯函数定向测试 |
| `apps/web/src/pages/AuditPage.test.tsx` | 新增 | 组件级定向测试（真实产品组件 + mock API） |
| `scripts/enterprise-experience/audit-correlation-browser-smoke.py` | 新增 | 全 API 拦截合成响应的浏览器冒烟（仅回环静态服务） |
| `docs/development/enterprise-audit-correlation-ui-handoff.md` | 新增 | 本交付记录 |

**未修改任何其他文件。** 尤其未触碰：后端 `routers/audit.py`、Edge、Connector、`App.tsx` 路由、`ConsoleContext`、共享 `client.ts`/`listMeta.ts`/`SimpleTable.tsx`/全局 CSS、其他页面、依赖/锁文件、README、公共台账与总任务书。

开始前 `git status` 显示工作树存在大量他人/在途改动（主开发者 Edge 周期归档恢复、GLM `discovery_schedules.py` 与 `EnvironmentsPage` 周期管理、ENT-018 前端等）。本任务仅在上表白名单文件内改动；`AuditPage.tsx` 与 `audit-search/` 目录本身是 ENT-019 既有未提交成果，本任务在其上增量修改并全部保留。未发现同文件在途冲突。

## 2. 缺陷复现（碰撞）

**旧实现**（修复前 `auditFiltersKey`）：

```ts
AUDIT_FILTER_FIELDS.map(({ key }) => `${key}=${filters[key]}`).join('&')
```

两组不同条件生成相同 key（已用 Node 与真实函数复现）：

- A：`request_id="a&resource_id=b"`，`resource_id="c"`
- B：`request_id="a"`，`resource_id="b&resource_id=c"`

旧 key 均为 `request_id=a&resource_id=b&resource_id=c&actor_id=&actor_type=&action=&resource_type=&decision=`（碰撞成立），但 `auditFiltersEqual(A,B)===false`（条件本身不同）。后果：已应用条件从 A 变到 B 时组合 key 不变，结果组件不卸载重建，旧查询（A）结果滞留、B 查询不发出。

身份键旧实现 `${tenant.id}#${actor.id}` 同样碰撞：`identityKey('t#1','a') === identityKey('t','1#a')`。

**修复**：`auditFiltersKey` 改为 `JSON.stringify(AUDIT_FILTER_FIELDS.map(({key}) => filters[key]))`（固定字段顺序元组，JSON 完整转义，值边界无歧义）；`identityKey` 改为 `JSON.stringify([tenantId, actorId])`。组合键仍为 `${identityPart}|${auditFiltersKey(applied)}`，但两段各自无歧义，不再依赖分隔符隔离。相同条件保持相同 key（重复提交不重建组件、不重复请求），不同条件必不同 key。

## 3. 关联操作机制

- **查询同请求**：仅当该行 `request_id` 为有效非空字符串且长度 ≤64（合同上限）时显示；生成全新条件只保留 `request_id`，其余六字段为空（不与上次条件 AND）。
- **查询同对象**：仅当 `resource_type`（≤32）与 `resource_id`（≤64）均为有效非空字符串时显示；生成条件 `resource_type + resource_id`，其余五字段清空（对象类型必须一起查询，避免跨类型同名 ID 混淆）。
- 按下按钮即显式查询：`handleCorrelate` 同步 `draft` 与 `applied`、清除旧分页/提示、组合 key 变化使旧结果组件卸载、从第一页 GET。同条件重复点击走既有「不重复请求」提示路径。
- 原值逐字保留：不 trim、不 lowercase、不截断；空格/中文/`&`/`+`/`#`/引号都只是匹配数据；复用既有长度规则与 `buildAuditQuery`（经 `URL.searchParams` 编码），不手工拼 API URL。
- 缺失/空值/异常类型/超长值不生成按钮，保持「未提供」/「无可关联标识」文本，不回退查询全量。
- 演示占位、断连、初次加载、身份失效时不渲染关联动作（关联列只在 `status==='connected'` 且传入 `onCorrelate` 时追加）。
- 语义边界：`request_id` 相同仅表示标识相等，`resource_type+resource_id` 相同仅表示对象标识匹配；不是独立效果证明、完整调用链或因果排序。原 allow/deny 语义说明保留。

## 4. 身份与权限隔离

- 结果组件 key = `identityPart | auditFiltersKey(applied)`；身份或条件变化即整体卸载重建，组件内 `requestSeq` 使迟到响应失效（A→B 迟到成功/错误、分页响应不覆盖 B）。
- 身份未 ready / 核对失败 / 无 `audit` 权限时零审计请求、不显示旧身份结果/连接状态/未提交草稿；沿用 `ConsoleContext` 的 `access.audit`，不推断管理员、不模拟权限通过。
- 页面加载失败与权限加载失败分别如实提示：身份核对失败显示「身份与权限核对失败，未发起审计查询；这不是权限已确认，请重试核对」，不再把身份加载失败一直描述成「正在核对」。保留既有权限重核对入口，未改共享机制。
- 身份键只序列化租户/操作者两个 ID，不含令牌或完整身份响应。

## 5. 验证命令与结果

均使用已安装依赖，未安装/联网同步。

**相关 Vitest**（`apps/web/` 下）：

```
./node_modules/.bin/vitest run \
  src/components/audit-search/auditSearch.test.ts \
  src/components/audit-search/auditCorrelation.test.ts \
  src/pages/AuditPage.test.tsx
```

结果：3 文件 18 用例全部通过。覆盖：A/B 键碰撞修复（旧实现负例复现 + 新编码不同 key）、真实组件 A→B 切条件发出 B 查询并丢弃 A 迟到响应、两类关联按钮准确参数/清空其余条件/表单同步/同条件重复不发请求、特殊字符原值往返、对象类型 AND 对象 ID、缺失/超长/异常值无动作、身份未 ready/失败/无权限零审计请求、分页沿用同一条件/加载更多失败保留记录/同游标重试、断连无关联动作、XSS 文本不执行、身份切换不残留旧结果、全程仅 GET。

组件测试环境说明：jsdom 不在本仓依赖（不安装新依赖），经 `createRequire` 复用兄弟项目 `siq-workbench` 已安装副本；React 的 `canUseDOM` 在模块加载时求值，故测试文件在设置 jsdom 全局后**再**动态导入 react/react-dom 与产品组件（顶层 await）。仅测试环境使用，不进入构建产物。

**标准正式模式临时目录构建**（一次）：

```
VITE_DEV_MODE=false npm run build -- --outDir <mktemp独立目录>
```

结果：`tsc -b && vite build` 通过，产物含关联代码（bundle 内出现「查询同请求/查询同对象/audit-correlation-btn」）。临时目录：`/tmp/siq-audit-build-G7YhpS`。

**浏览器冒烟**（一次，全 API 拦截合成响应，仅回环静态服务）：

```
/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/audit-correlation-browser-smoke.py \
  --web <VITE_DEV_MODE=true 独立构建目录> --out-dir <新目录>
```

使用 `VITE_DEV_MODE=true` 独立构建目录（`/tmp/siq-audit-dev-E1wd6A`），**仅模拟不可发布**。9 项检查全部通过：关联按钮可见、缺失标识行无动作、查询同请求参数与表单同步、同条件重复不发请求、清空恢复一般查询、查询同对象 type+id、键盘 Enter 触发、375px 无文档级横向溢出、零业务写请求且零未捕获异常。

**git diff --check**：通过（exit 0）。

**截图**（已实际查看）：
- 桌面 1280：`/tmp/siq-audit-smoke-run-3785538/desktop-1280.png` — 三行真实结果，行 1/2 显示「查询同请求/查询同对象」按钮，行 3（缺失标识）显示「无可关联标识」，特殊字符原值保留，已应用条件同步。
- 移动 375：`/tmp/siq-audit-smoke-run-3785538/mobile-375.png` — 表单单列纵向排列，无文档级横向溢出，表格沿用既有 `.table-wrap` 横向滚动行为。
- 结构化报告：`/tmp/siq-audit-smoke-run-3785538/report.json`。

## 6. 未运行项与范围外问题

- 未跑全仓全量测试（按任务书最小充分集合原则）。
- 未连接真实控制面、未部署、未提交/推送、未清理工作树。
- 未读取真实密码/.env/令牌/私钥/设备种子。
- 范围外（非本任务、未触碰）：主开发者 Edge 周期归档恢复、GLM `discovery_schedules.py` 与 `EnvironmentsPage` 周期管理、ENT-018 前端子任务等在途改动均保留原状。
- 浏览器冒烟的「权限隔离/身份切换」分支由 Vitest 组件测试覆盖（零审计请求、身份切换不残留旧结果）；冒烟脚本聚焦关联旅程 + 键盘 + 视口 + 零写/零异常。

## 7. 剩余限制

- 关联操作仅证明标识相等/对象标识匹配，不构成完整因果链或防护生效证明（界面文案已明确）。
- 组件级测试依赖兄弟项目 jsdom 副本（绝对路径），若该副本移动需更新 `createRequire` 路径；不影响构建产物。
- 本任务未新增后端接口、审计图、导出、URL 参数、轮询或业务写操作。

## 8. 主开发者复核修复（2026-09-26）

原交付的身份切换测试只核对结果行，并未证明草稿/已应用条件清理。补充真实页面回归后实测 **4 failed / 6 passed**：租户切换、同 ID 的操作者类型切换、权限错误后恢复均保留旧条件；同条件关联时未同步未提交草稿。

本轮修复：

- 以身份状态、audit 权限及租户/actor type/actor ID 的 JSON 元组重建整个查询会话，不仅重建结果组件。草稿、已应用条件、提示及页头连接状态一并隔离。
- identityKey 补 actor type，组合结果键也使用 JSON 元组。
- 同条件关联仍不重复请求，但先将草稿同步为该关联条件。
- 原已定义的 AUDIT_CORRELATION_NOTE 未实际渲染，本轮接入，明确关联会替换旧条件。

按 React 技能使用带 key 的会话边界和事件处理，不增加清理 state 的同步 effect；未改共享 Context/Layout、后端、其他开发线或视觉样式。

实际执行：

```bash
# apps/web
npm test -- src/pages/AuditPage.test.tsx src/components/audit-search/auditSearch.test.ts src/components/audit-search/auditCorrelation.test.ts
VITE_DEV_MODE=false npm run build -- --outDir /tmp/siq-audit-correlation-review-production-20260926 --logLevel error
VITE_DEV_MODE=true npm exec -- vite build --outDir /tmp/siq-audit-correlation-review-SIMULATED-20260926 --logLevel error
# repo root
/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/audit-correlation-browser-smoke.py --web /tmp/siq-audit-correlation-review-SIMULATED-20260926 --out-dir /tmp/siq-audit-correlation-review-final-20260926
```

结果 **3 文件 / 21 passed**；标准 tsc + vite 成功；隔离模拟浏览器 **9/9**、零业务写和未捕获异常；git diff --check 与本次新增测试文件空白检查通过。模拟产物不可发布，截图/报告位于上述 final 目录。身份隔离由组件测试验证，不冒称该浏览器脚本覆盖全部身份切换场景。

尚未关闭的交付限制：AuditPage.test.tsx 通过绝对路径加载兄弟仓 node_modules 中的 jsdom。本轮测试在本机可执行，但不能证明独立检出可复现；未安装新依赖或擅自扩大为测试框架迁移，也未删除/跳过该测试。该限制须在独立源码集成门禁前解决，不能将本次本机功能验证当作所有交付条件已满足。

本轮业务缺陷已修复并定向验证；测试可移植性仍待收口。未提交、未部署，CL-06/ENT-019 未关闭。
