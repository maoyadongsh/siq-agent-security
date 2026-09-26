# CL-06-CHANGE-EXECUTION-EVIDENCE-CLOSEOUT 开发任务书

分配对象：DeepSeek。日期：2026-09-26。

你是本项目负责企业安全控制面的资深全栈工程师。请直接完成本任务的核查、必要修复和验证，不要只给方案。

## 一、任务与目标

任务编号：**CL-06-CHANGE-EXECUTION-EVIDENCE-CLOSEOUT**。

项目目录：

```text
/home/maoyd/siq/siq-agent-security
```

本任务负责既有“变更执行记录”链路的完整收口：

```text
当前租户的变更
→ 对应部署记录
→ 对应审计事件
→ 有限、脱敏的后端投影
→ 前端严格解析
→ 执行证据标签与说明
```

用户要求加速收尾、禁止扩展功能。因此：

- 不新建页面、路由、导航或第二套审计系统。
- 不增加权限、执行按钮、后台任务或新的业务操作。
- 不为增加工作量寻找无关问题。
- 对确实存在的问题，先复现，再最小修复。
- 对已经正确的行为，复用现有测试，不强行改代码。

完成目标：现有执行记录链路在租户隔离、权限、记录关联、截断提示、异常证据和前后端语义方面可靠一致，不把登记状态、配置读回或未经核验的标签解释为实际行为防护。

## 二、开始前必须阅读

### 1. 工作区及项目规则

```text
/home/maoyd/siq/AGENTS.md
/home/maoyd/siq/VIBECODING_SCIENTIFIC_METHOD.md
/home/maoyd/siq/siq-agent-security/AGENTS.md
```

定位并阅读适用的下级 AGENTS.md。

### 2. 任务背景与安全边界

```text
docs/development/enterprise-auto-onboarding-closeout-20260926.md
docs/development/enterprise-permission-coverage-closeout.md
packages/contracts/change-execution.v1.schema.json
```

重点理解 CL-06，以及“配置读回≠行为验证”“精确查询≠完整审计链”。

### 3. 当前实现

```text
apps/control-api/app/routers/change_execution.py
apps/control-api/app/tests/test_change_execution.py
apps/web/src/api/changeExecution.ts
apps/web/src/api/changeExecution.test.ts
apps/web/src/components/ChangeExecutionDialog.tsx
```

### 4. 只读追踪必要的事实生产者

- Deployment、ChangeRequest、AuditEvent、Environment 模型。
- 部署验证、独立回执验证、失败、回滚所写入的字段。
- 对应审计 action、resource_type、resource_id、summary 的真实生产者。
- 前端 `readChangeExecution`、`parseChangeExecution`、`executionEvidence` 的调用者。

不要依靠字段名称推断事实；需要找到实际生产代码或明确声明没有生产者。

### 5. 检查工作树与并行归属

检查 git status 与目标文件 diff。当前仓库有大量其他开发线成果。未跟踪文件同样属于他人，不能覆盖、删除、还原或提交。

主开发者分配时检查的四个主要文件未显示未提交改动；这只是当时状态，不代表执行时仍然空闲，必须重新核对。

## 三、文件所有权与允许范围

允许修改：

```text
apps/control-api/app/routers/change_execution.py
apps/control-api/app/tests/test_change_execution.py
apps/web/src/api/changeExecution.ts
apps/web/src/api/changeExecution.test.ts
```

允许新增：

```text
apps/control-api/app/tests/test_change_execution_evidence_boundaries.py
docs/development/enterprise-change-execution-evidence-closeout-handoff.md
```

如果确有必要，可在前述两个产品文件内部新增私有纯函数，避免另建通用框架。

默认只读、禁止修改：

```text
apps/web/src/components/ChangeExecutionDialog.tsx
packages/contracts/change-execution.v1.schema.json
```

禁止修改：

- models.py、schemas.py、迁移、共享鉴权及审计实现。
- policies.py、deployment_verify.py、drift.py。
- binding_identity.py、binding_evidence_readiness.py。
- deployment_preview.py、deployment_impact.py。
- 部署提交、批次预约和批次执行模块。
- AuditPage、ChangesPage、共享客户端、共享组件、全局 CSS。
- Edge、Connector、安装器、发行脚本。
- package.json、锁文件、公共任务书及进度台账。
- 其他开发线交接文件。

如果必须修改白名单外文件，先报告原因、具体文件与最小改动，等待主开发者协调；不要自行扩展。

如开始时发现目标文件有新增在途改动，先明确归属。不以时间戳或“我认为不冲突”作为独占依据。

## 四、必须完成的四个工作包

### A. 后端对象关联与权限边界

核对真实端点：

```text
GET /api/v1/change-requests/{cr_id}/execution
```

要求：

1. 保留当前先定位租户对象、再检查权限的顺序。
2. tenant_id 只来自验证身份。
3. 部署记录必须属于当前租户及当前变更，不能只按裸 ID 关联。
4. 审计关联必须同时核对 resource_type 与 resource_id，不能只按相同字符串关联。
5. 同租户其他变更、其他租户同名标识均不能混入。
6. 环境名称继续受既有 env:read 控制；缺权限不得输出名称。
7. 缺 audit:read 时不返回审计正文，也不能借计数或截断标志披露不可访问记录。
8. 缺少或异常关联不得回退为“查全租户”“任选环境”或名称匹配。
9. 成功响应保持 no-store；GET 不产生审计、任务、outbox 或状态写入。

核对 default 与 expanded 的既有限制、稳定排序和截断行为。不要把最多 100/200 条的 expanded 响应称为全量历史，也不要新增分页产品能力。

### B. 执行证据投影与真实来源一致

逐项追踪：

```text
verification_level
independent_result
backend_mutated
error_digest
review_digest
status
```

至少回答：

- 哪些字段确有生产者？
- 哪些只是兼容历史值？
- 哪些缺少当前生产者？
- 哪些状态只能证明过去某次读回，不能证明当前运行状态？

重点核查：

1. 非对象 receipt、verification、summary、independent_attestation 是否能导致崩溃、误判或原文泄漏。
2. 字符串、布尔、数组、对象等异常类型是否被 `str()`、真值转换或默认值错误归一。
3. 摘要是否严格保持既有格式，而非把任意文本当摘要。
4. 独立读回失败、目标/版本不一致、过期证据、回滚记录与历史成功同时存在时，最终说明是否仍诚实。
5. `effective` 本身不得代表行为已验证。
6. 一个写有 `behavior_verified` 或类似名称的历史字段，不能未经生产者与合同核对就升级为可信行为证据。

不得凭感觉删除历史兼容行为。若存在不安全映射，必须给出生产者、合同及负例依据；无法证明时记录争议，不擅自创造认证规则。

维持现有响应字段与枚举。缺证据应使用已有 unknown/none/not_checked 等适用语义，不新增“已安全”“完全保护”等状态。

### C. 前端解析与证据说明收口

核对并必要修复：

```text
parseChangeExecution
readChangeExecution
executionEvidence
deploymentStatus
auditAction
```

要求：

1. 解析失败必须拒绝，不能通过 String() 等转换接受数组或对象冒充枚举。
2. 保留精确字段、版本、请求对象 ID、列表长度、重复 ID、摘要和日期检查。
3. 日期检查不能仅凭 Date.parse 可解析就接受明显不存在的日期；遵循现有合同，避免无依据收窄合法格式。
4. audit_access=denied 时审计数组和截断标志必须一致。
5. 前端字段映射必须与后端真实投影一致。
6. “未知后端值”有安全的显示语义，不产生绿色成功假象或崩溃。
7. 请求 ID 正确编码；不增加 tenant_id 覆盖参数，不写浏览器存储。
8. 证据冲突时展示说明应保守且准确，但不要擅自重新定义部署状态或验证协议。

本轮原则上不修改 React 页面、组件或视觉样式；继续使用当前消费者。

### D. 前后端闭环核对与交接

用隔离合成数据确认真实后端输出可被真实前端解析器消费。

优先复用已有样本和测试机制；如需临时导出样本：

- 仅导出本任务合成数据。
- 放独立临时目录，拒绝覆盖现有证据。
- 明确记录后端来源、命令与摘要。
- 使用真实前端解析函数，不重写一份测试专用解析器。
- 不连接真实接口，不读取真实审计数据。
- 不为本任务新建通用测试平台或长期后台服务。

至少核对一组正常结果、一组降级结果和一组无审计权限结果。没有完成实际跨端消费，就不能写“前后端联合验证通过”。

## 五、最小充分验证

用户要求减少重复测试。不要反复跑全仓全量，不规定凑数测试量。

复用既有测试，新增负例仅覆盖真实缺口和关键未覆盖边界。建议按以下场景组合组织：

- 当前租户正常变更与关联部署。
- 跨租户及错误 resource_type 不混入。
- policy:read、audit:read、env:read 分别验证，不能用缺多个权限的身份替代精确断言。
- default/expanded 的边界数量与截断、同时间戳稳定排序。
- 异常证据结构与脱敏。
- 状态冲突与历史成功不冒充当前行为成功。
- 前端非法类型、日期、重复 ID、响应对象不匹配拒绝。
- GET 前后相关记录数量及关键字段不变。

先跑聚焦测试；改到消费者语义，再跑其直接相关测试。

后端示例：

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_change_execution.py \
  app/tests/test_change_execution_evidence_boundaries.py
uv run --no-sync ruff check \
  app/routers/change_execution.py \
  app/tests/test_change_execution.py \
  app/tests/test_change_execution_evidence_boundaries.py
```

如果没有必要新增边界文件，从命令中去掉，不创建空文件凑交付。

前端：

- 使用仓库已有命令，只运行 changeExecution 相关测试。
- 如修改前端产品源码，执行一次标准构建。
- 明确 `VITE_DEV_MODE=false`。
- 输出到 mktemp 创建的独立目录，不覆盖 dist。
- 不安装依赖，不使用替代配置掩盖标准构建失败。

未修改 UI，不要求新增浏览器冒烟脚本或截图。

最后执行：

```bash
git diff --check
```

未跟踪的新文件另做空白检查。测试失败不得通过删断言、跳过安全场景、放宽解析器或修改其他开发线文件消除。

## 六、基线复现与并行安全

发现问题时：

1. 优先先加聚焦负例，在当前未修复实现上运行。
2. 记录失败原因与实际行为。
3. 做最小修复，再跑同一负例及相关回归。

若修复已实施而需要补基线，使用隔离临时副本。禁止把共享工作树临时换回 HEAD 再恢复，尤其禁止覆盖他人未跟踪源码。

不用“旧代码可能如此”冒充实际复现。

## 七、禁止事项

- 不读取 admin-password.private、真实 .env、密码、令牌、私钥、设备种子。
- 不运行真实扫描、真实部署、真实 OpenShell 写入或真实权限操作。
- 不修改生产数据库，不启动或重启生产服务。
- 不新增执行按钮、自动恢复、自动回滚、自动重试业务写。
- 不改变审批、租户隔离或审计事务安全边界。
- 不安装依赖。
- 不创建提交、分支、推送或 PR。
- 不删除、清理、还原其他开发者文件。
- 不以模拟验证宣布生产安全、完整审计归档或整个 CL-06 完成。

## 八、交付要求

写入：

```text
docs/development/enterprise-change-execution-evidence-closeout-handoff.md
```

必须包含：

1. 实际修改文件与修改前状态。
2. A–D 每项结论：正确、已修复、受阻或范围外。
3. 证据字段→真实生产者→后端投影→前端说明的简洁映射。
4. 真实缺陷的修复前后证据；没发现的不能编造。
5. 所有实际执行命令、数量、失败、警告及未执行项。
6. 前后端样本消费证据；如未完成，明确原因。
7. 已知边界及主开发者需要决定的事项。
8. 明确声明：

> 仅完成 CL-06-CHANGE-EXECUTION-EVIDENCE-CLOSEOUT。未提交、未推送、未部署；未新增业务能力，不代表完整审计链、保留治理、CL-06 或整体项目完成。

完成后停止，不继续领取或扩展其他任务。
