# ENT-014-UI 权限事实可视化与筛选 — 交付记录

日期：2026-09-25　执行者：Kimi Code（前端）　状态：**未提交、未部署，待主开发者复核**

## 1. 任务范围与非目标

范围：ENT-014 的前端子任务 ENT-014-UI —— 既有权限事实（`PermissionFactRow`）的可视化展示与组合筛选。

非目标（未实现，属于整个 ENT-014 或后续任务）：
- 批量授权、策略发布、运行时绑定、任何后端能力；
- OpenShell 同步限定目标、外部沙箱导入归属验证等后端语义；
- 本记录不声明 ENT-014、批量权限治理或项目整体完成。

## 2. 开始时仓库状态

- 分支 `main`，HEAD `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`（`main...origin/main`）。
- 工作树存在大量其他开发者改动（Codex 安装接入/发行、Claude 企业导航等，约 200+ 文件）。
- 本任务涉及的 `apps/web/src/pages/PermissionsPage.tsx` 开始时**无未提交修改**（`git diff --stat` 为空）。
- `apps/web/src/components/permission-facts/`、`scripts/enterprise-experience/permission-facts-browser-smoke.py` 开始时不存在。
- 未清理、还原、覆盖或提交任何他人改动。

## 3. 实际修改 / 新增文件清单

修改（1 个，任务书允许）：
- `apps/web/src/pages/PermissionsPage.tsx` — 接入新组件；保留 OpenShell 同步、漂移检查、声明 vs 有效 Diff 三个操作（请求与语义未动）。

新增（均在允许清单内）：
- `apps/web/src/components/permission-facts/permissionFacts.ts` — 纯函数：五态解释/计数、authority/domain 枚举、AND 组合筛选、有效期判定（显式 `now` 参数、时间戳比较）。
- `apps/web/src/components/permission-facts/PermissionFactsOverview.tsx` — 五态概览卡片（仅 connected 时渲染）。
- `apps/web/src/components/permission-facts/PermissionFactsFilters.tsx` — authority 按钮 + 状态/权限域下拉 + 文本搜索 + 清除筛选（含 `DOMAIN_LABELS`）。
- `apps/web/src/components/permission-facts/PermissionFactItem.tsx` — 原生 `details/summary` 详情（键盘可展开）。
- `apps/web/src/components/permission-facts/PermissionFactsList.tsx` — 列表容器；60s 定时刷新有效期提示并在卸载时清理计时器。
- `apps/web/src/components/permission-facts/permission-facts.css` — `pf-` 前缀局部样式（桌面网格列表 / ≤720px 卡片）。
- `apps/web/src/components/permission-facts/permissionFacts.test.ts`、`PermissionFactItem.test.tsx`。
- `scripts/enterprise-experience/permission-facts-browser-smoke.py` — 独立 fixture 浏览器冒烟。
- `docs/evidence/enterprise-auto-onboarding-20260925/permission-facts-ui/` — 截图与 `result.json`。
- 本交付记录。

未修改任何共享模块（Layout/SimpleTable/api/hooks/ui/全局 CSS/后端等均保持原样）。

## 4. 展示与筛选规则

- 概览：声明/推断/观测/生效/未知五卡片，计数**仅统计已加载记录**，文案明示"不代表组织全量"；仅 `status === 'connected'` 时渲染；加载中显示"正在加载…"而非一组 0；断连走既有 `DisconnectedNotice`。
- 筛选：authority（按钮，沿用原有交互）AND 状态 AND 权限域 AND 文本搜索（主体 ID/动作/资源类型/资源值/来源，大小写不敏感）；「清除筛选」一键复位；不自动拉取全部分页。
- 计数行：`匹配 X 条 / 已加载 Y 条`，并保留既有 `coverageText` 分页说明；`hasMore` 时追加"筛选仅覆盖已加载数据"。
- 空态区分四种：后端成功空列表 / 筛选无匹配（附清除按钮）/ 首次加载 / 加载失败；加载更多失败时保留已有数据并 `role="alert"` 显示错误，重试可恢复。
- 详情：原生 `details/summary`（键盘 Enter 可开合），展示主体类型+ID、环境 ID（缺失显示"未提供"）、域/动作/资源、allow/deny、原始 state+中文解释、authority+revision、valid_from/valid_until、evidence_ids（仅标识文本，无猜测链接）。

## 5. 语义边界（重要）

- declared = 仅声明允许，≠ 实际使用；observed = 运行观察，≠ 策略允许；effective = 后端事实层级，**≠ 已通过行为阻断验证**；页面任何位置不出现"全面保护""阻断已验证"结论。
- authority 与 state 互不推导；`authority=openshell` 不升级为 effective；有纯函数测试锁定。
- 有效期判定仅展示层：`assessValidity(row, now)` 显式接收时间戳；pending/expired 文案含"按当前设备时间判断，未经服务端核验"；within 文案明示"不代表当前执行端仍有效或已核验"；缺边界显示"未提供，不推断为永久有效"；日期无效或起止矛盾显示"有效期信息异常"。
- 过期/异常记录使用红系警示样式（`pf-item-expired`），不使用无保留绿色；状态同时有文字标签，不仅靠颜色区分。
- 后端文本一律按普通文本渲染；无 `dangerouslySetInnerHTML`；XSS fixture 断言通过。
- 不展示 `delegated_user` / `conditions` 原始 JSON；若未来需要，属于另行授权的范围扩展。
- 只读展示与筛选不产生任何 POST/PUT/PATCH/DELETE（浏览器冒烟断言 `writes == 0`）；未向 localStorage/sessionStorage 写入任何内容。

## 6. 测试命令与实际结果

```
cd /home/maoyd/siq/siq-agent-security/apps/web
npm test
# Test Files 71 passed (71)，Tests 464 passed (464)（含本次新增 2 个测试文件、21 项测试）

BUILD_DIR=$(mktemp -d /tmp/siq-permission-facts-kimi-build-XXXXXX)   # 实际 /tmp/siq-permission-facts-kimi-build-7RI1rl
npm run build -- --outDir "$BUILD_DIR"   # tsc -b + vite build 通过

git diff --check   # 干净；新增未跟踪文件已单独做行尾空白检查
```

纯函数测试覆盖：五态分组计数（键齐全、未知归入 unknown）、effective 与 authority 互不推导、AND 组合筛选、空列表/无匹配、相同 subject_id 不合并、边界相等/未来/过期/带时区/无效日期/缺边界/起止矛盾、不修改输入数组与后端 state。组件测试覆盖：五态文案与"不代表组织全量"、过期 effective 文案、revision/证据/缺失字段、XSS 仅文本、不展开 delegated_user/conditions、原生 details/summary。

浏览器冒烟（全 fixture，仅 127.0.0.1，独立临时 HTTP 服务）：
```
python3 scripts/enterprise-experience/permission-facts-browser-smoke.py \
  --web /tmp/siq-permission-facts-kimi-build-7RI1rl \
  --out-dir docs/evidence/enterprise-auto-onboarding-20260925/permission-facts-ui
```
结果 `passed: true`，11 项检查全过：加载不显示零值、五态与过期 effective 文案、键盘展开详情（revision/证据）、XSS 仅文本与缺失字段、加载更多失败保留数据并报错、重试成功、组合筛选与清除、375px 无横向溢出、空列表与断连区分、无写请求与无未捕获异常。测试进程（临时 HTTP 服务与浏览器）已随脚本结束停止。

## 7. 截图与结果路径

- `docs/evidence/enterprise-auto-onboarding-20260925/permission-facts-ui/desktop.png`（1280px，已查看：概览卡片、筛选条、网格列表正常）
- `docs/evidence/enterprise-auto-onboarding-20260925/permission-facts-ui/mobile.png`（375px，已查看：卡片布局、无横向溢出）
- `docs/evidence/enterprise-auto-onboarding-20260925/permission-facts-ui/result.json`

## 8. 模拟依赖、未运行验证与已知限制

- 浏览器冒烟使用合成 fixture 与 Playwright 拦截，**不能证明后端授权、真实网关或生产环境已验收**；未使用 VITE_DEV_MODE 构建，无"模拟验收专用"构建产物需处理。
- 构建输出在临时目录 `/tmp/siq-permission-facts-kimi-build-7RI1rl`，未部署、未发布。
- 有效期提示的定时刷新周期为 60s；倒计时精度不按秒。
- 移动端断点取 ≤720px（与设计系统移动档一致），任务要求的 375px 已实测。
- 详情未提供 delegated_user/conditions 展示；如产品需要须另行授权并注意身份信息暴露边界。

## 9. 范围外发现的问题（记录，不自行修复）

- `apps/web/src/hooks/useApiList.ts:74-90`：加载更多失败后 `error` 一直保留，即使后续重试成功也不清除（本页以"已保留此前成功加载的数据"文案兜底；共享 hook 修复交主开发者）。
- `apps/web/src/hooks/useApiList.ts:70`：非 append 的 reload 期间旧 rows 保留在 hook state 中；本页在 `status==='loading'` 时不渲染旧数据，但其他复用该 hook 的页面若直接渲染 rows 可能把旧记录展示成当前结果（共享机制问题，交主开发者）。
- `apps/web/src/pages/PermissionsPage.tsx` 既有操作的小问题（如漂移/Diff 失败写入 `syncError` 共用槽位）保持原样未动。

## 10. 复核提示

未提交、未推送、未部署；以上改动待主开发者复核后再决定是否入库。

## 11. 主开发者初次独立复核（2026-09-25）

状态：**暂不最终验收，待修正中等窗口内容区横向溢出**。不否定原 375px 证据，
也不以已有测试全部通过替代未覆盖视口的验证。

- 当前工作树 Web 全量测试 71 文件 / 464 项通过，日志 `/tmp/siq-permission-review-tests.log`。
- 使用前一导航批次已构建的 `/tmp/siq-nav-codex-review-build-20260925` 复跑隔离浏览器脚本，11/11 通过，结果和已实际查看的截图在 `/tmp/siq-permission-codex-review-20260925/`。这是既有构建的独立复跑，不是本批最新源码重新构建或生产验收。
- 视觉检查：现有米白、深蓝、金色设计语言保留，`pf-` 样式引用现有设计变量；操作处理函数差异未见变更。React 技能复核显示筛选直接派生、定时器有卸载清理。
- 加测内容区尺寸：768px 窗口 `.content.clientWidth=480`、`scrollWidth=965`；1024px 为 736/973；1280px 为 992/992。document 宽度都等于窗口，因此只检查 document 不能发现内部溢出。原因是列表网格固定最小列宽与仅 720px 的卡片断点未考虑桌面侧栏占用宽度。
- 加测脚本以原夹具代码在内存插入三个视口探测，未改交付源文件、未连接真实服务；辅助输出目录 `/tmp/siq-permission-codex-width-probe-20260925/`。下一步应修正局部响应式布局，并将 `.content` 溢出检查纳入持久浏览器脚本后重新构建验收。
- 第 9 节共享 hook 的重试成功后错误不清除问题已对照源码确认；须作为独立共享行为修复保留回归范围，不能以 UI 文案当作已经解决。

本次未修改 Kimi 的实现代码、未提交或部署，ENT-014-UI 尚待上述复核项收口。

## 12. 响应式复核项修正（2026-09-25）

第 11 节的中等窗口溢出已修正：只修改局部 permission-facts.css，使用列表容器
实际宽度决定网格/卡片切换，考虑桌面侧栏占宽；长字段可换行，详情列不超过容器。
不增加窗口监听、React 状态或依赖，不改变字体、配色、业务操作与权限事实语义。

重新从当前源码构建至 `/tmp/siq-permission-responsive-build-20260925`，未设置
VITE_DEV_MODE，构建和全量 **71 文件 / 464 项测试通过**，日志分别为
`/tmp/siq-permission-responsive-build.log`、`/tmp/siq-permission-responsive-tests.log`。
浏览器脚本持久补充 375/768/1024/1280/1440px 的 document 与 `.content`
宽度断言；**16/16 通过**，最终结果与截图目录
`/tmp/siq-permission-responsive-evidence-20260925-r2/`。
实际查看桌面、移动和三个直接定位列表的 medium-375/768/1024 截图，卡片与现有
风格一致，无横向遮挡。测试全部隔离 mock，临时服务已停止，非生产验收。

本批 git diff --check 通过，未提交或部署。响应式阻断项已收口；第 9 节共享 hook
错误残留仍待独立修复，不把重试取得数据等同于所有错误展示已恢复正常。

## 13. 共享列表重试错误残留修正（2026-09-25）

主开发者在持续目标授权下独立修改共享 `useApiList.ts`：仅在当前请求序号仍有效且
请求成功时 setError(null)。这是原 Kimi 子任务范围外的后续修复，不记为 Kimi 改动。
请求失败仍保留错误与已有数据，过时响应仍被原序号守卫拒绝；未改变 reload 的旧
rows 保留行为。本权限页 loading 状态不渲染旧记录，其他共享调用方仍需按自身语义复核。

新增浏览器断言先在旧构建失败（重试已返回 7 条，alert 仍有 1 条），日志
`/tmp/siq-pagination-error-before.log`；新构建通过 **17/17**，证据目录
`/tmp/siq-pagination-recovery-evidence-20260925/`。全量 Web **71 文件 / 464 项通过**，
日志 `/tmp/siq-pagination-recovery-tests.log`。独立构建
`/tmp/siq-pagination-recovery-build-20260925`，日志 `/tmp/siq-pagination-recovery-build.log`。
git diff --check 通过，无样式或权限语义变更；全 fixture、无业务写请求、非生产验收。
本批解决第 9 节的重试错误残留，未提交或部署，不声明 ENT-014 或批量治理完成。

## 14. 特殊未知枚举复核修复（2026-09-25）

主开发者验收新增反例：state 为 `__proto__`/`constructor`/`toString` 时，`in` 命中
对象原型，unknown 计数错误；普通映射查表返回对象/函数，SSR 实测出现 React child
异常。新增 6 项负向测试先得到 6 failed / 21 passed，随后改为 Object.hasOwn。

修复涉及 permissionFacts.ts、PermissionFactsFilters.tsx、PermissionFactItem.tsx 及共享
ui/verification.ts 的 permissionStateLabel 一行；相应两个测试文件和浏览器脚本增加
特殊枚举回归。未知状态保留文本并计入 unknown，不改变后端状态、授权或防御判断。
React 技能指导下保留现有派生计算，不增加状态/effect，无样式变更。

全量 `npm test`：79 文件 / 549 项通过。`git diff --check` 通过。
标准构建本轮失败：并行 Kimi 策略组件 `PolicyExplorerItem.tsx:7` 的 modeLabel
未使用导入导致 TS6133；主开发者未修改该并行文件。不能以先前标准构建通过
替代本轮集成验收。

为独立验证当前权限修复，仅执行本地 Vite（跳过 tsc）生成模拟身份夹具：

```bash
# apps/web，仅浏览器夹具，不可发布，不计为标准构建通过
env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=true VITE_DEMO_PLACEHOLDERS=false ./node_modules/.bin/vite build --outDir /tmp/siq-permission-enum-browser-only-20260925
# 仓库根目录
python3 scripts/enterprise-experience/permission-facts-browser-smoke.py --web /tmp/siq-permission-enum-browser-only-20260925 --out-dir /tmp/siq-permission-enum-evidence-20260925
```

浏览器 18/18 通过，包含特殊状态正确计为未知 3 条、详情正常显示、五视口、分页
失败恢复、零写请求及无未捕获异常；临时服务已停止。结果与截图位于上述 out-dir。
原型属性缺陷已修复并通过专项模拟验证；当前全项目标准构建仍待并行策略组件收口
后复跑。未提交、未部署，不宣称生产权限或防御验收完成。
