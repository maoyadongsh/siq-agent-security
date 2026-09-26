# CL-03-SNAPSHOT-COMPARISON-UI 交接记录（2026-09-26）

资产详情「角色配置历史」新增「与最新技能观察对照」交互：用户显式选择一条已保存
配置观察，查看该快照与设备最新已记录技能安装观察的对照。
本记录仅声明 CL-03-SNAPSHOT-COMPARISON-UI 子任务的实际完成情况，不代表 CL-03、
ENT-018、角色—技能精确关联或整个项目已完成。**未提交、未推送、未部署，待主开发者复核。**

## 1. 实际修改与新增文件

新增：

- `apps/web/src/api/roleSkillSnapshotComparison.ts` —
  `GET /api/v1/agents/{asset_id}/configuration-observations/{observation_id}/skill-installation-sources`
  只读客户端 + 严格响应核验（schema `enterprise-role-skill-snapshot-comparison/v1`）。
- `apps/web/src/api/roleSkillSnapshotComparison.test.ts` — 24 条解析/请求测试。
- `apps/web/src/components/role-skill-snapshot-comparison/SnapshotComparisonPanel.tsx`
  — 对照面板组件（`SnapshotComparisonDetails` + `ComparisonPage` + 默认导出）。
- `apps/web/src/components/role-skill-snapshot-comparison/snapshot-comparison.css`
  — 新样式，全部 `role-skill-snapshot-` 前缀。
- `scripts/enterprise-experience/role-skill-snapshot-comparison-browser-smoke.py`
  — 隔离模拟浏览器冒烟（Playwright + ThreadingHTTPServer，仅 loopback）。

修改（最小接入）：

- `apps/web/src/components/inventory/RoleConfigurationHistoryPanel.tsx` —
  `ConfigurationHistoryDetails` 新增 `onCompare`/`comparisonOpen` 可选 props，
  每行渲染「与最新技能观察对照」按钮；`HistoryPanel` 持有 `selection` 状态，
  刷新/翻页/身份变化时清除选择；选中时渲染 `SnapshotComparisonPanel`。
  默认导出（身份/权限门控 + key）未改动。
- `apps/web/src/components/inventory/RoleConfigurationHistoryPanel.test.tsx` —
  保留原有 5 条 SSR 测试；新增 13 条交互测试（最小 DOM shim + react-dom/client）。

未修改：后端路由、共享 CSS、共享 API client、package.json/锁文件、
AgentDetailPage.tsx、App.tsx、framework-tree/**、local/**、deployment-postgres-check.py。

## 2. 语义与固定文案

- 固定说明（`PAGE_NOTE`）：「对照已保存配置与最新已记录技能观察，不是配置时刻的
  安装还原；目录来源匹配不代表角色已加载技能，也不代表权限已生效。」
- `snapshot_unavailable`：「该快照不可对照：已保存配置或目录来源声明尚不可核对。
  不回退最新配置、其他设备或其他快照，也不代表未安装技能。」
- 空页：「当前页没有安装记录；不代表设备未安装技能或已完成全部扫描。」
- 覆盖范围：「该快照设备安装记录的分页，不虚构组织总数。」
- 403：「当前账号无权读取该快照的技能对照，请重新核对组织权限。」
- 404：「该配置观察不可读取或不存在，不能据此判断跨租户记录是否存在。」
- 其他错误：「快照技能对照读取失败，不能据此判断没有技能观察。」
- 不渲染异常原文（无 `dangerouslySetInnerHTML`，无 raw exception body）。

## 3. 交互与状态

- 每行独立「与最新技能观察对照」按钮；点击前零对照请求（有测试断言）。
- 单选：同一时间仅一个快照选中；「关闭对照」清除选择。
- 选择清除时机：刷新配置历史、历史翻页（上/下页）、身份/租户/资产变化
  （`HistoryPanel` key 含 tenant/actor/assetId）。
- 八态区分：未选中、首次加载（role=status）、成功有数据、成功空页、
  snapshot_unavailable、首次读取失败（role=alert + 重试）、分页失败（保留已成功页
  + 同游标重试）、403/404（安全提示，不渲染异常原文）。
- 分页：显式「下一页对照」按钮，cursor=installation ID；失败保留已成功页，
  重试使用同一快照与失败游标；不重复安装位置（解析层拒绝非升序/重复 ID）。
- 竞态保护：`requestSeq` ref + `active` flag（effect cleanup）；
  A→B 迟到成功/失败不覆盖 B；旧分页不污染新快照（单测 + 浏览器均覆盖）。

## 4. 权限、身份与安全性

- 使用既有 `useConsoleContext`；要求 `access.agents && access.environments` 双权限。
  身份加载中/失败/权限不足：不挂载面板、不发请求（有测试断言零请求）。
- 不传 tenant_id 或身份覆盖参数；路径 ID 经 `encodeURIComponent`。
- 响应核验：精确键集、schema/asset/basis/coverage/runtime/effective 固定值、
  `isConfigurationSnapshot` + observation_id 匹配、status/data 一致性
  （unavailable ⇒ items 空 + next_cursor null；historical_comparison ⇒
  recorded_snapshot + 两个已声明 roots）、逐条 installation 校验
  （ID 升序、matched_sources ⊆ 声明 roots、relationship_status 一致性、
  isSkillObservation）、next_cursor === 末项 ID。
- 不使用 localStorage/sessionStorage；不自动循环拉取全部页；只读 GET。
- 后端文本一律纯文本渲染（React text nodes，无 dangerouslySetInnerHTML）。

## 5. 风格复用

复用现有类：`card`、`btn`、`kv-list`、`mono`。新 CSS 全部
`role-skill-snapshot-` 前缀，引用既有 CSS 变量（--border、--table-row-hover 等），
未改任何共享全局样式。交互用原生 button + details/summary（可键盘操作）；
焦点可见；加载/失败用 role=status/role=alert。≤640px 时 kv-list 切换为 block 布局。

## 6. 实际测试命令与结果

- `cd apps/web && npm test`：105 文件 / 918 用例全部通过
  （基线 884 + 本任务新增 34 条：24 API + 10 组件交互）。
- 标准构建：
  `env -u VITE_APP -u SIQ_AS_WEB_BASE VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false \
  npm run build -- --outDir <mktemp-dir>`：成功（tsc -b && vite build，exit 0）。
- 模拟构建（仅模拟验收，不可发布）：
  `VITE_DEV_MODE=true VITE_DEMO_PLACEHOLDERS=false ./node_modules/.bin/vite build \
  --outDir <mktemp-dir>`：成功。
- 浏览器冒烟（仅模拟验收，不可发布）：
  `uv run --no-project --with playwright python \
  scripts/enterprise-experience/role-skill-snapshot-comparison-browser-smoke.py \
  --web <mock-dir> --out <out-dir>`。
  14 项检查全过：
  1. 点击前零对照请求
  2. 键盘可操作 + 焦点可见
  3. 选中快照数据展示
  4. 分页下一页同快照
  5. 分页失败保留已成功页 + 同游标重试
  6. A→B 迟到成功不覆盖
  7. snapshot_unavailable 不回退
  8. 空页不代表未安装
  9. 403/404 安全提示不渲染异常原文
  10. 关闭/刷新清除选择
  11. XSS 仅作为纯文本
  12. 375/768/1280 无横向溢出
  13. 双权限拒绝零请求
  14. 零写请求/零外部网络/零未捕获异常
- `git diff --check`：通过（无空白错误）。

## 7. 浏览器报告与截图

目录（本地证据，未提交）：

- `report.json` — 14 项检查清单、违规与错误（均空）、对照请求 (observation, cursor) 序列。
- `snapshot-comparison-1280.png` — 桌面 1280px，已实际查看：固定说明、kv-list、
  安装位置、分页按钮均正确渲染。
- `snapshot-comparison-768.png` — 平板 768px，已实际查看：无横向溢出。
- `snapshot-comparison-375.png` — 移动 375px，已实际查看：kv-list 切换为 block 布局，
  长 ID 换行，无横向溢出。

以上为合成 fixture + Playwright 拦截的隔离模拟验收，不证明真实控制面、IAM 或生产
环境行为；未连接任何真实业务数据。

## 8. 未完成项与范围外问题

- 本任务只读展示：不含纳管、授权、扫描、运行时绑定或任何治理写操作。
- 角色—技能精确关联仍是 CL-03/ENT-018 后续事项；本视图只展示目录来源匹配关系，
  不证明角色已加载技能或权限已生效。
- 后端路由 `role_skill_sources.py:141`（`snapshot_skill_sources`）与合同
  `enterprise-role-skill-snapshot-comparison.v1.md` 一致：schema_version/asset_id/
  configuration_observation/status/comparison_basis/coverage/items/next_cursor/
  runtime_status/effective_permissions 十字段、cursor=installation ID、
  limit 1..100 默认 50、404（tenant/asset/observation 作用域）先于 403
  （agent:read/env:read）、no-store、共享 `installation_source_page` 辅助函数。
  未发现差异。
- `RoleConfigurationHistoryPanel.tsx` 和 `.test.tsx` 为未跟踪文件（非本任务创建，
  由前序 ENT-018 子任务创建），本任务在其基础上修改；若主开发者有并行改动，
  需合并复核。
- 浏览器冒烟使用 `uv run --no-project --with playwright`（未修改项目依赖）；
  若 CI 环境无 uv，需安装 playwright Python 包。

## 9. 合同与实现一致性核对

- `GET /api/v1/agents/{asset_id}/configuration-observations/{observation_id}/skill-installation-sources`
  实现（`apps/control-api/app/routers/role_skill_sources.py:141`，未跟踪文件，
  主开发线在收口）与合同 `packages/contracts/enterprise-role-skill-snapshot-comparison.v1.md`
  一致：
  - 响应十字段精确匹配，无多余/缺失字段。
  - `status` 仅 `historical_comparison` / `snapshot_unavailable` 两值。
  - `snapshot_unavailable`：items=[]、next_cursor=null、不回退最新配置/其他设备/其他快照。
  - `historical_comparison`：configuration_observation 必须为 recorded_snapshot 且
    skill_source_roots 为 declared（两个有效 roots）。
  - 分页规则与 `enterprise-role-skill-sources-view/v1` 共享：cursor=installation ID、
    limit 1..100 默认 50、items 按 installation_id 升序、next_cursor=末项 ID 或 null。
  - 404（作用域不匹配）先于 403（权限不足）；no-store 缓存头。
  - `outside_declared_sources` 始终携带已验证 observation；`unresolved` 无 matches/observation。
  - 未发现差异。
- 后端测试 `apps/control-api/app/tests/test_role_skill_snapshot_comparison.py`
  （未跟踪文件）覆盖 no-fallback、unavailable、403/404/422 行为，与前端解析器一致。

**未提交、未推送、未部署，待主开发者复核。**

## 10. 主开发者独立复核（2026-09-26）

复核合同、请求校验、身份门控、选中状态重置、迟到响应隔离及真实截图后，接受并修复两项 UI 问题：

1. 分页失败后重试缺少加载状态：延迟 Promise 回归断言在旧实现失败，修复为点击重试时设置 pending；保留已成功页，并显示“正在读取下一页对照”。修改面板组件及既有交互测试，未放宽原断言。
2. 移动端局部 `.role-skill-snapshot-kv` 与共享 `.kv-list` 优先级相同，构建后的样式顺序使单列规则未生效。375px 原截图实为窄双列。改用面板限定的 `.role-skill-snapshot-panel .kv-list`，涵盖快照和展开的技能详情，移动端为单列并保留字段间距；未修改共享 CSS。浏览器新增 computedStyle 布局断言，展开技能详情核对溢出。截图使用同宽较高视口，避免控制台内部滚动容器裁切详情；溢出检查仍在 1000px 高视口执行。

按照 React 技能的交互状态建议在事件处理器中补齐 pending；没有增加 effect、依赖、业务请求或改变权限语义。

本轮实际验证：

- `cd apps/web && npm test`：105 文件、918 用例全部通过。日志 `/tmp/siq-snapshot-review-tests-20260926.log`。
- `VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false npm run build -- --outDir /tmp/siq-snapshot-review-build-b1OXrl`：标准 tsc + Vite 构建通过，执行时清除 VITE_APP、SIQ_AS_WEB_BASE 覆盖；日志 `/tmp/siq-snapshot-review-build-20260926.log`。
- 模拟构建 `/tmp/siq-snapshot-review-mock-mgiJrj` 仅用于隔离浏览器验收，不可发布。
- `python3 scripts/enterprise-experience/role-skill-snapshot-comparison-browser-smoke.py --web /tmp/siq-snapshot-review-mock-mgiJrj --out /tmp/siq-snapshot-review-browser-20260926-r3`：14/14，通过；无写请求、外部网络或未捕获异常。
- 最终报告和三张截图在 `/tmp/siq-snapshot-review-browser-20260926-r3/`，桌面、平板、移动布局已实际查看；颜色、按钮和信息字段沿用现有设计。
- `git diff --check` 与脚本 Ruff 通过。

结论仅覆盖此只读 UI 子任务的源码与模拟回归；没有重做真实 IAM/控制面/设备端到端验收，不证明运行时加载或权限生效。不关闭 CL-03、ENT-018 或整体项目。未提交、未推送、未部署。
