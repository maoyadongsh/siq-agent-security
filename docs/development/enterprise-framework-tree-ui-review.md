# ENT-018-FRAMEWORK-TREE-UI 主开发者复核

日期：2026-09-25 至 2026-09-26。仅复核框架实例 UI 子任务；未提交、未部署。

## 发现、修复与证据

1. **复合键碰撞（正确性）**：交接文档称 NUL 分隔，实际实例键 `.join('')`、设备键直接拼接。`env-a/bc` 与 `env-ab/c` 在相同实例键下合并为一个环境；实例键不同则第二环境出现空设备列表。新增两项测试准确复现后，将两级键均改为 JSON 数组编码，不改变租户权限或后端。
2. **错误归纳整组证据（审计展示）**：同实例不同角色可有不同配置摘要、证据和观察时间，原分组只保存首条并用作实例证据。新增页面行为测试先失败，修复为每个角色独立展开其来源证据；删除分组上失真的单一证据字段。不同观察不猜测为同一时刻，不新增技能或 effective 权限推导。
3. **详情返回丢失视图（交互）**：将框架视图选择保存在现有 `/agents?view=framework` 中；详情链接/返回只保留 view、environment_id、device_id 白名单，不接受任意重定向或身份参数。支持刷新和前进后退。未修改 App 路由定义，原 assets/candidates 查询行为保留。
4. **截图覆盖不足（验收）**：原脚本只保存折叠态，交接文档另称已看展开态。主开发者脚本新增逐角色证据核对、全层级展开的内容宽度断言及展开截图，避免折叠掩盖长摘要溢出；增加详情返回/刷新/前进后退检查。所有浏览器请求受 loopback GET 限制并禁用 service worker。

按 React 技能保留现有 effect 清理和身份/过滤 key 重挂载；不新增依赖、不重构共享 hook。专用 CSS 只补逐角色证据占满一行，沿用现有暖纸、墨蓝、深金风格及可见焦点。

## 修改范围

- `components/framework-tree/frameworkTree.ts`、分组测试
- `components/framework-tree/FrameworkTreeView.tsx`、行为测试
- `components/framework-tree/framework-tree.css`
- 新增 `components/framework-tree/frameworkTreeNavigation.ts` 及测试
- `pages/AgentsPage.tsx`、`pages/AgentDetailPage.tsx`：仅视图查询及详情返回接入
- `scripts/enterprise-experience/framework-tree-browser-smoke.py`
- 本复核文档（原作者交接历史不覆盖）

上述前端路径均相对 `apps/web/src/`。未修改权限 API、后端、安装器、个人端、共享样式或安全规则；主开发线既有批量操作保留。

## 验证

- `npm test -- src/components/framework-tree/frameworkTree.test.ts`：修复前 9 通过 / 2 失败；同环境/设备拼接碰撞两项均准确失败。
- `npm test -- src/components/framework-tree/FrameworkTreeView.test.tsx`：证据归属负向新增项修复前失败，其余 16 通过。
- 修复后框架组件及 API 聚焦 62 项通过；后续新增导航 2 项。
- 最终 `npm test`：**102 文件 / 846 项通过**（含本轮新增 5 项）。
- 标准 `npm run build -- --outDir /tmp/siq-tree-review-production-final-20260925`：**成功**；显式 `VITE_DEV_MODE=false VITE_DEMO_PLACEHOLDERS=false`，取消 VITE_APP/SIQ_AS_WEB_BASE 覆盖。
- 模拟身份构建 `/tmp/siq-tree-review-mock-final-20260925` 仅用于隔离验收，不可发布。
- 隔离浏览器 r2：**15/15 通过**，`violations=[]`、`errors=[]`，仅 GET；涵盖分组、逐角色来源、分页失败同游标重试、迟到响应、双权限、XSS 纯文本、375/768/1280 展开态宽度、详情返回/刷新/前进后退。
- `ruff check` 浏览器脚本和 `git diff --check` 通过。

浏览器命令：

```bash
/home/maoyd/miniconda3/bin/python scripts/enterprise-experience/framework-tree-browser-smoke.py \
  --web /tmp/siq-tree-review-mock-final-20260925 --out /tmp/siq-tree-review-evidence-r3
```

## 限制与后续

最终 r3 同样 **15/15 通过**。报告 `/tmp/siq-tree-review-evidence-r3/report.json`；该目录包含折叠、展开及独立逐角色证据的桌面/375px 截图。已实际查看展开视图及 `framework-tree-role-evidence-375.png`、`framework-tree-role-evidence-1280.png`，第二份配置证据按角色展示，长摘要正常换行，无裁剪。仅本子任务源码与隔离交互复核通过。

“vitest beforeEach 重置导致 rejection”仅为作者报告，本轮未独立复现库问题，也未据此改动其他测试。角色—技能精确关联与整体自动接入仍未完成。本轮启动的 `roleConfigurationHistory.ts`、`RoleConfigurationHistoryPanel.tsx` 为主线未接入草稿，因用户要求优先验收而暂停；未纳入本次功能通过结论。

本次只证明源码及隔离交互，不证明真实 IAM、生产数据、设备扫描或 OpenShell 防御效果。未提交、未部署。
