# Qwen3.8：审计关联检索与查询上下文隔离收口

任务编号：CL-06-AUDIT-CORRELATION-UI。项目：`/home/maoyd/siq/siq-agent-security`。

直接实现并验证，不只输出方案。本任务收口 ENT-019 既有审计精确检索的可达性和查询隔离，不新增审计图、导出、保留政策、后端接口或业务写操作。保持现有界面风格、防御能力及权限边界。

## 1. 当前事实与交付目标

现有 AuditPage 已有七字段精确查询、草稿/已应用条件分离、GET 分页与权限门禁。AuditSearchResults 中 request_id/resource_id 目前只是文本，操作者需手工复制再查询。后端已支持对应精确参数，无须改后端。

已发现的真实代码风险：auditFiltersKey 用未经转义的 `key=value` 和 `&` 拼接，以下两组不同条件会生成相同 key：

- A：request_id=`a&resource_id=b`，resource_id=`c`。
- B：request_id=`a`，resource_id=`b&resource_id=c`。

其他五字段均为空。当前结果组件只在挂载时请求，依赖 key 重建；key 碰撞可能使页面已应用条件变化但仍保留旧查询结果。上述表达式已由主开发者在 Node 复现；你必须通过真实产品函数及组件回归验证，而不是复制函数写自证测试。身份键也使用分隔符拼接，应统一使用无歧义元组序列化。

完成用户旅程：查看真实审计事件 → 点击“查询同请求”或“查询同对象” → 表单和已应用条件同步 → 服务端精确查询与分页 → 清空恢复一般查询；查询切换、身份变化和迟到响应不能串结果。只证明标识关联，不声称完整因果链或效果已验证。

## 2. 开始前与所有权

完整阅读工作区/仓库/相关下级 AGENTS.md、工作区 VIBECODING_SCIENTIFIC_METHOD.md、总任务书安全不变量、CL-06 收口要求。

必须使用 `/home/maoyd/.agents/skills/vercel-react-best-practices/SKILL.md`，阅读实际相关的派生状态、事件处理和 effect 依赖规则。动作由事件处理触发，简单派生值不要另存 state/effect；不增加依赖或另建缓存框架。

检查 git status 和目标文件 diff。当前既有/未跟踪改动均须保留；发现同文件在途冲突先报告。主开发者负责 Edge 周期归档恢复；GLM 负责 discovery_schedules.py 与 EnvironmentsPage 的周期管理，禁止触碰。

必读：AuditPage.tsx、components/audit-search/**、ConsoleContext.tsx、api/consoleContext.ts、api/client.ts、api/listMeta.ts、api/types.ts 的 AuditEvent、SimpleTable.tsx；后端 routers/audit.py 与 enterprise-audit-query.v1.md 仅用于核对合同。查找已有审计测试和隔离冒烟方式，优先复用，不重复建立测试框架。

## 3. 文件白名单

允许修改：

- apps/web/src/pages/AuditPage.tsx
- apps/web/src/components/audit-search/auditSearch.ts
- apps/web/src/components/audit-search/AuditSearchResults.tsx
- apps/web/src/components/audit-search/audit-search.css（仅必要局部规则）

允许新增：

- apps/web/src/components/audit-search/auditCorrelation.ts 及对应测试（如确需独立纯函数模块）
- 上述组件目录下本任务专用 `*.test.ts` / `*.test.tsx`
- apps/web/src/pages/AuditPage.test.tsx（若已存在则先保留并增量补充）
- scripts/enterprise-experience/audit-correlation-browser-smoke.py
- docs/development/enterprise-audit-correlation-ui-handoff.md

除此之外不修改。尤其禁止改后端、Edge、Connector、App.tsx 路由、个人端、ConsoleContext、共享 client/hook/Table/CSS、其他页面、依赖/锁文件、README、公共台账与总任务书。确有额外必需改动先报告文件和原因，不擅自扩展。

## 4. 实现要求

### A. 先修复查询键与身份隔离

1. 先用真实 auditFiltersKey 写负例证明 A/B 碰撞，再改为固定字段顺序的 JSON 元组序列化等无歧义编码；不同查询必须不同 key，相同查询保持相同 key。
2. 租户/操作者与查询组合键也按明确元组序列化，不再拼接 #/|/&。不要把令牌或完整身份响应放入 key。
3. 保留结果组件的卸载清理/requestSeq 机制；A→B 迟到成功/错误、分页响应不能覆盖 B。
4. 身份变更或权限重核对时，不展示旧身份的结果、连接成功、错误或未提交草稿；身份未 ready/失败/无 audit 权限时零审计请求。沿用 ConsoleContext，不推断管理员，不模拟权限通过。
5. 页面加载失败与权限加载失败应分别如实提示；不要把身份加载失败一直描述成“正在核对”。保留已有权限重核对入口，不改共享机制。

### B. 从真实事件发起精确关联查询

1. 仅在真实 connected 结果中，对有效 request_id 显示原生按钮“查询同请求”；动作设置全新条件：只保留该 request_id，其他六字段为空。不得偷偷与上次条件 AND，造成误以为无关联记录。
2. “查询同对象”只在 resource_id 与 resource_type 均为有效非空字符串、长度符合现有合同的真实事件中显示；设置 resource_id + resource_type，其他五字段清空。对象类型必须一起查询，避免跨类型同名 ID 混淆。
3. 按下按钮即为显式查询操作：同步 draft 和 applied，清除旧分页/提示，从第一页 GET；同条件重复点击遵循原有“不重复请求”的行为并给提示。
4. 明确说明关联操作会替换当前查询条件；保留清空与手动修改/提交能力。不增加 URL 参数、路由、新窗口、后台预取或自动轮询。
5. 原值逐字保留：不 trim、不 lowercase、不截断，空格、中文、&、+、#、引号都只是匹配数据。复用既有长度规则与请求编码，不直接拼 API URL。
6. 缺失、空值、异常类型、超长值不生成可操作按钮，不回退查询全量；保持文本/未提供提示。不读取 summary 递归猜测关联，不展开任意后端 JSON、URL、文件路径或 HTML。
7. 演示占位、断连、初次加载、身份失效时不能展示可用关联动作。分页失败仍可展示此前真实记录及错误，但不得把错误描述成全量加载成功。
8. request_id 相同仅表示标识相等，resource_type+resource_id 相同仅表示对象标识匹配；不是独立效果证明、完整调用链或因果排序。原 allow/deny 语义说明保留。

### C. 风格、辅助功能与安全

- 复用现有 card/btn-sm/字体/间距/色彩，新增样式限 audit-search- 或 audit-correlation- 前缀。不要重做全页视觉。
- 保留 ID 原文；按钮的可访问名称能区分操作及所选行。键盘 Enter/Space 可操作，焦点可见；条件更新后的焦点变化须合理，不无限跳焦点。
- 375px 与桌面无新增文档级横向溢出；长标识正确换行，不遮挡操作按钮。保留表格原有响应式行为。
- 全程仅既有 GET，不添加 POST/PUT/PATCH/DELETE；不写 localStorage/sessionStorage/IndexedDB，不持久化查询或身份。
- 所有后端字符串按文本渲染；不使用 dangerouslySetInnerHTML、eval、动态脚本或外部跳转。

## 5. 最小充分验证

不凑测试数量、不跑全仓全量。至少用集中定向用例验证：

- A/B 键碰撞修复；真实组件从 A 切 B 确实发出 B 查询并丢弃 A 迟到响应。
- 两类关联按钮的准确参数、清空其余条件、表单同步、同条件重复不发请求。
- 特殊字符原值往返一致；对象类型 AND 对象 ID；缺失/超长/异常值无动作。
- 身份切换、权限失效/加载失败零审计请求且无旧记录/草稿/连接状态泄漏。
- 分页沿用同一新条件；加载更多失败保留记录、同游标重试；清空回首屏。
- 演示占位无动作，XSS 文本不执行，全程无业务写请求。

只运行相关 Vitest；标准 `VITE_DEV_MODE=false npm run build -- --outDir <mktemp独立目录>` 一次；git diff --check。使用已安装依赖，不安装或联网同步。

一次隔离浏览器冒烟足够：所有 API 拦截合成响应，仅回环静态服务；验证上述主要旅程、键盘、375/1280、零业务写/未捕获异常。若需 VITE_DEV_MODE=true，另用独立目录并标明仅模拟不可发布。保存两张关键截图及结构化报告，实际查看截图。标准构建被其他线阻断时如实记录，不绕过文件/改配置伪造通过。

## 6. 禁止操作与交付

不读取 admin-password.private、真实 .env、密码、令牌、私钥或设备种子。不调用真实控制面、不注册/扫描/上传/修改数据库或操作 systemctl。不启动或部署生产服务，不提交、推送、建分支、发布、签发，不清理/还原工作树。

交接文件记录：真实修改文件、碰撞复现前后、关联参数与身份隔离机制、保留的权限语义、精确测试/构建命令和结果、截图/报告路径、未运行项及范围外问题。

只有关联交互、隔离修复与定向验证均完成，才声明 CL-06-AUDIT-CORRELATION-UI 完成。未提交、未部署、待主开发者复核；不宣称 CL-06/ENT-019 整体完成，更不把本任务当作审计导出、保留治理或完整运行效果链已经实现。
