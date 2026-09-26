# GLM：周期发现计划可视化查看与撤销闭环

任务编号：CL-02-SCHEDULE-MANAGEMENT。项目：`/home/maoyd/siq/siq-agent-security`。

直接实现、验证、交付。这是既有企业自动接入周期调度的管理缺口收口，不是再次整理文档，不引入新的扫描/授权机制。用户要求减少重复测试、禁止范围外功能扩展；保持当前前端风格与全部防御能力。

## 1. 当前事实与目标

已存在 `DiscoveryScheduleRecord`、组织创建/撤销 POST、设备确认与 tick。组织路由在 `apps/control-api/app/routers/discovery_schedules.py`，目前无管理列表 GET。环境页面已有环境选择、接入与设备生命周期面板，但没有周期计划管理面板。

完成用户旅程：选环境 → 按需查看周期计划 → 看清待确认/已确认、窗口和预约预算 → 明确确认撤销 → 核对后端返回。必须区分「计划 active」与「设备在线/正在扫描/防护生效」。本任务不创建计划、不替设备确认，不处理确认日志换代，不新增暂停/恢复功能。

## 2. 开始前

完整阅读工作区、仓库及相关目录 AGENTS.md，工作区 VIBECODING_SCIENTIFIC_METHOD.md、本任务书及总任务书安全不变量。

前端使用 `/home/maoyd/.agents/skills/vercel-react-best-practices/SKILL.md`，按实际涉及的派生状态、请求清理规则阅读对应条目。沿用已有 card/btn/tag/对话框设计与字体、配色、间距，不引入 UI 依赖。

检查 git status、允许文件现有内容与 diff。未提交和未跟踪文件都可能是其他人的成果，禁止覆盖、清理、还原。允许文件出现并行修改时保留并最小接入；无法安全合并先报告具体冲突。

必须阅读（除白名单外均只读）：

- packages/contracts/enterprise-discovery-schedule.v1.md
- apps/control-api/app/routers/discovery_schedules.py
- apps/control-api/app/discovery_schedule.py、models.py 的两张 schedule 表
- apps/control-api/app/security.py、routers/environments.py、routers/device_lifecycle.py
- 既有 schedule 创建/撤销/确认测试与 conftest.py
- apps/web/src/pages/EnvironmentsPage.tsx
- apps/web/src/components/ConsoleContext.tsx、api/consoleContext.ts、api/client.ts
- apps/web/src/components/device-lifecycle/ 下相关面板、既有确认对话框

## 3. 文件所有权

允许修改：

- apps/control-api/app/routers/discovery_schedules.py：只增 GET 与必要私有投影辅助；原两个 POST 的权限、载荷、事务和审计语义不变。
- apps/web/src/pages/EnvironmentsPage.tsx：仅导入并挂载独立面板，保留原页面所有逻辑。

允许新增：

- packages/contracts/enterprise-discovery-schedule-management.v1.md
- apps/control-api/app/tests/test_discovery_schedule_management.py
- apps/web/src/api/discoveryScheduleManagement.ts 及对应测试
- apps/web/src/components/discovery-schedule-management/ 下组件、纯函数、专用 CSS、定向测试
- scripts/enterprise-experience/discovery-schedule-management-browser-smoke.py
- docs/development/enterprise-discovery-schedule-management-handoff.md

禁止改其他文件。特别禁止改 Qwen 所有的 discovery_scheduler.py 及其测试、Edge/Connector、models.py、数据库迁移、既有周期确认合同、App.tsx、个人端、onboarding/**、共享 CSS、共享 client/hook、权限模型、依赖/锁文件、公共台账、README。发现范围外问题仅记录。

## 4. 后端：先写合同，再实现只读投影

在现有路由模块新增：

`GET /api/v1/environments/{environment_id}/discovery-schedules`

要求：

1. 先通过既有环境定位函数确认认证租户内对象，404；再要求 env:read，403。tenant 仅取验证身份，不接受查询覆盖。
2. 按 tenant_id + environment_id 筛选全部查询。不得从猜测的 ID 读取外租户计划或设备。
3. cursor 为严格合法的 eds-32位小写 hex；limit 默认 20、范围 1..100；计划 ID 升序，limit+1，下一游标为最后返回项 ID；空列表 next_cursor=null。不新增全量统计、自动拉全或可变排序。
4. 精确版本 `enterprise-discovery-schedule-management/v1`。顶层字段建议固定 schema_version、environment_id、evaluated_at、can_revoke、items、next_cursor。先冻结该合同后同步消费。
5. can_revoke 只能由当前身份的 env:manage AND edge:manage 派生，不按角色名推断；它是 UI 提示，不替代原 POST 的实时鉴权。
6. 每项只投影白名单：schedule_id、edge_agent_id、status、revision、starts_at、expires_at、interval_seconds、max_runs、reserved_runs、last_reserved_slot、created_at。日期 UTC Z，计数是非负整数。字段来源逐项说明。
7. 不返回 installation_plan、intent 原文、根目录、确认签名、凭据、tenant_id、设备种子或任何敏感配置。不要用 ORM 自动序列化整行。
8. Cache-Control: no-store。GET 无状态修改，不增加调度、任务、确认、审计或 outbox，不调用 reserve/tick。
9. 原始 status 仅 pending_confirmation/active/paused/revoked；时间已过期和预算耗尽是另外的可解释事实，不偷偷回写数据库 status。

不新增详情 API、筛选 API 或导出；当前分页白名单已经足够支持面板。

## 5. 前端：现有环境页面内的独立面板

1. 选中环境后显示「周期发现计划」面板，用户展开/点击查看才 GET；无选择、身份加载失败/待加载、无环境读权限时零请求。默认不增加后台轮询。
2. 沿用 ConsoleContext/client。响应严格验证版本、字段、环境回声、ID、日期、计数、cursor 和排序。异常不回退成空列表或 0；未知状态不能显示成 active。
3. 区分初次未加载、加载、空列表、成功、首次失败、加载更多失败。失败保留已成功页并可同游标重试；刷新从第一页替换，显式加载更多，标明「仅已加载记录」。
4. 环境切换、身份切换/重核对、卸载、刷新后的迟到响应不能覆盖新范围，也不能在新身份下闪现旧数据。取消/序号处理复用现有模式，不修改共享 hook。
5. 状态中文清楚：待设备确认、已确认的计划、已暂停、已撤销。active 明示不是设备在线、采集成功或保护生效。reserved_runs 是已预约轮次，不是成功扫描次数。
6. 用服务端 evaluated_at 判断窗口尚未开始/已过期；不要用前端时钟给出未经标记的事实。不推算「下次必定扫描时间」。max_runs-reserved_runs 只解释为未预约预算，受期限与其他门禁约束。
7. can_revoke=false 不展示撤销操作。已撤销不再展示可点击撤销按钮；其他已有状态允许进入明确确认。失败或加载时不使用未核实的旧权限开放操作。
8. 撤销复用现有 POST `/environments/{environment_id}/discovery-schedules/{schedule_id}/revoke`，载荷严格 `{expected_revision: 当前记录revision}`。禁止夹带 reason、设备确认、租户覆盖或额外字段。
9. 确认对话框展示计划/设备 ID 和后果：「停止该计划后续调度，不保证已派发任务被取消，不撤销智能体业务权限」。原生可访问控件，忙碌防重复，取消零写请求。
10. 409 不自动使用新 revision 重试，提示刷新核对后重新确认；403 不伪装成功；网络/5xx 视为结果未知，不自动重发。提供只读刷新核对。
11. 成功响应须匹配请求计划 ID、版本、status=revoked 等既有合同；只据已核实响应展示成功并刷新。不通过乐观删除隐藏计划，不丢弃审计历史。
12. 375px 与桌面无横向溢出；长 ID 换行；保持当前项目风格、可见键盘焦点、对话框焦点管理和 Escape 行为。专用 CSS 使用 dsm- 前缀，不覆盖共享类选择器。

## 6. 最小充分验证，不刷测试数量

复用现有夹具，优先集中参数化用例。仅对本任务验证：

- 后端：同租户分页/空页，跨租户环境404，有对象无权限403，cursor/limit422，can_revoke 权限组合，白名单无敏感字段，GET 前后状态/任务/审计/outbox不变。
- 保留并运行原 schedule 创建/撤销相关测试，证明原 POST 未被修改。不得为了本任务改旧测试预期。
- 前端：解析与权限门禁，A→B 迟到隔离，分页失败保留与同游标重试，撤销载荷、取消、重复点击、409/403/结果未知、错误响应不误报成功。
- 一次隔离浏览器冒烟：仅 127.0.0.1 静态服务，全部 API 拦截合成响应；只读阶段零业务写；撤销阶段逐条核对 mock POST 的路径/方法/载荷；权限不足、桌面/375px、键盘、无未捕获异常。保存桌面/移动截图并实际查看。
- 仅运行相关 pytest / Vitest、修改文件 Ruff、标准 npm run build 输出 mktemp 独立目录、git diff --check。不要跑全库后端/前端/Go测试，不安装依赖。
- 若冒烟需 VITE_DEV_MODE=true，另用独立构建目录，标明仅模拟不可发布。正式模式构建 VITE_DEV_MODE=false。
- 标准构建遇其他开发线阻断，记录确切错误，不绕过文件伪造通过，不越界修复。

不能删断言、跳过安全负例或放宽解析消除失败。浏览器模拟不证明生产 IAM、真实设备确认或真实扫描停止。

## 7. 禁止真实操作

不读取 admin-password.private、真实 .env、令牌、密码、私钥、种子。不读真实用户配置，不访问真实控制面，不创建/确认/撤销真实计划，不启动真实周期扫描，不改数据库，不操作 systemctl、不部署。不得提交、推送、建分支、签发、发布或清理工作树。

## 8. 交付与完成边界

handoff 记录实际文件、协议字段、权限与租户边界、撤销语义、定向命令/实际结果、截图/报告位置、源码与模拟证据区别、发现的范围外问题。

只有 GET + 企业面板 + 既有撤销完整连接并验证，才声明本子任务完成，不以只完成合同/接口替代前端交付。不要求凑用例数量。

明确未提交、未部署、待主开发者复核；本子任务不代表周期计划创建与设备确认的完整安装旅程完成，不关闭 CL-02 或整体项目。
