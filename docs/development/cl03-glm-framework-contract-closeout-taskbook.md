# GLM：框架来源协议兼容文档收口

任务编号：CL-03-FRAMEWORK-CONTRACT-DOCS。
项目：`/home/maoyd/siq/siq-agent-security`。

请直接完成文件交付，不只输出方案。本次是文档任务，不是上一轮首扫取消修复的重复；两者分别交付。用户要求禁止扩展功能、减少测试、加快收口。

## 1. 目标

主线已实现 Hermes 来源 v2 入库和读取、OpenClaw v1 兼容，以及按页面内容返回 framework-role-inventory/v1 或 v2。需要为清单 v2 补独立合同说明，并在旧合同中加入准确的版本导航。

只记录已经实现的行为，不设计新 API、不改变旧合同的历史语义、不宣称技能安装/加载或生效权限已完成。若实现不一致，记录问题交主开发者，不自行修改源码或编造规范掩盖差异。

## 2. 必须阅读

- 工作区 `/home/maoyd/siq/AGENTS.md`、仓库及相关目录 AGENTS.md（若有）。
- `packages/contracts/enterprise-framework-source.v1.md`
- `packages/contracts/enterprise-framework-source.v2.md`（只读，主线所有）
- `packages/contracts/enterprise-framework-role-inventory.v1.md`
- `apps/control-api/app/framework_source.py`
- `apps/control-api/app/framework_source_view.py`
- `apps/control-api/app/routers/framework_inventory.py`
- `apps/web/src/api/frameworkSource.ts`
- `apps/web/src/api/frameworkRoleInventory.ts`
- 对应定向测试和开发台账 Batch172/173（只读，辨别实现与验证边界）。

先执行 git status，核对目标文档现有内容和 diff。不要覆盖或还原任何在途成果；未跟踪文件同样归原作者所有。

## 3. 文件白名单

允许新增：

- `packages/contracts/enterprise-framework-role-inventory.v2.md`
- `docs/development/enterprise-framework-contract-docs-handoff.md`

允许最小修改，仅添加版本导航/兼容说明，不重写旧正文：

- `packages/contracts/enterprise-framework-role-inventory.v1.md`
- `packages/contracts/enterprise-framework-source.v1.md`

其他文件只读。不要修改 source.v2 合同、主线代码、README、总任务书、公共台账、前端、后端、Edge、Connector、依赖及其他交接文件。若允许新增的文件已经出现，先检查是否有他人在途内容，不能覆盖。

## 4. 交付内容

### A. 独立清单 v2 文档

依据代码逐项说明：

1. 保持现有 GET URL、双读权限、认证租户来源、no-store；不增加业务写请求。
2. 顶层精确字段及分页规则：schema_version、coverage、items、next_cursor，cursor/limit/排序和已有过滤。
3. v2 项目字段与 v1 保持一致；嵌套来源只接受明确的 source-view/v1 或 source-view/v2，不接受任意版本。
4. source-view/v1 成功来源与 OpenClaw 配对，source-view/v2 成功来源与 Hermes 配对；缺失/不可核对来源仍为 null，不能造节点。
5. 当前服务端按页面内容选版本：含 source-view/v2 则清单 v2，否则 v1；同一分页旅程可能先 v1 后 v2，客户端须逐页验证。不要误写为所有请求恒 v2。
6. v1 客户端可能拒绝 v2，不能称为对旧客户端完全无感兼容；生产者/消费者应配套交付。不能强制把 Hermes 改成 OpenClaw、删掉版本校验或自动降级来“兼容”。
7. 分组仍以认证上下文+环境+设备+framework+instance_key，跨框架同摘要不能合并。同名角色不表示同一实体。
8. 所有历史、范围、未确认边界保留：page_of_tenant_assets 不是全量；runtime_status=unverified、skill_relationship_status=unresolved、effective_permissions=null；Hermes profile 来源不证明技能加载或进程存活。

给出一个最小纯合成响应示例（不复制真实资产/设备/配置/证据）。示例须满足当前解析器字段、标识和时间格式。可只展示一项 Hermes；无需巨大混合数据或新测试脚本。

### B. 旧合同导航

在两个 v1 文档中加短小清楚的说明：v1 的既有 OpenClaw 语义不变；Hermes/混合页扩展见新文档与 source.v2。旧正文不替换为新版本，不用“已全面支持”措辞。

### C. 状态与证据

说明本任务仅核对文档与当前源码，不证明部署、浏览器验收、跨语言原生旅程或正式发行。不要把主线历史测试数量合并成自己的通过数量。

## 5. 验证预算

仅做相关 Markdown 本地链接/相对路径检查、示例字段人工对照及 git diff --check；新文件单独查空白。不跑 npm test、pytest、Go 测试、浏览器或构建，不安装依赖，不添加自动化框架。

可以用现有解析代码辅助检查纯合成示例，但不得因此启动服务、读 .env 或执行真实业务请求；不是必须项。

若发现代码与本任务说明不一致，以实际代码与已接受合同为证据列出冲突；不擅自改变规则。缺少行为证据则明确“未验证”。

## 6. 禁止操作

不读取 admin-password.private、真实 .env、密码、令牌、私钥、设备种子。不扫描真实目录、不注册、上传、签发、启停或部署服务。不提交、建分支、推送、打标签或发 PR。不清理工作树、不格式化无关文件。

## 7. 交付

指定 handoff 简洁记录：实际文件、源码对应位置、版本映射、兼容限制、检查结果、未完成项。最终明确未提交、未部署，仅文档收口完成，不代表 CL-03 或整体项目完成。
