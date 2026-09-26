# 企业主线合并后剩余开发收口任务书（2026-09-26）

> 执行对象：另一开发窗口中的资深全栈工程师 / 智能体安全工程师
>
> 仓库：`/home/maoyd/siq/siq-agent-security`
>
> 基线：`main` / `origin/main` = `2ab1ce2546b616675757ebc59244086aa094bbc0`
>
> 目标：只关闭当前仍可独立开发的两个真实缺口，并同步合同和操作者文档；禁止扩展功能面。

## 1. 任务性质与完成边界

本任务不是新一轮产品扩展，也不是重复全仓审计。当前大量企业端、个人端、Edge、Connector、合同、测试和交付工具已经汇总提交并推送到 `main`。本轮只处理以下三个工作包：

1. **F01：Edge 无需预先知道 schedule ID 即可发现本设备待确认的周期发现计划。**
2. **F02：OCSF 导出明确声明本次结果是否因 `limit` 被截断。**
3. **F03：同步上述两项的合同、CLI 帮助和操作者文档，并形成一份交接记录。**

以下结果必须同时成立，才能声明本任务完成：

- 新增能力仍是只读发现或诚实声明，不自动授权、不自动确认、不自动执行；
- 设备侧周期确认仍要求现有的独立本机确认；
- OCSF 导出正文、媒体类型、排序、租户隔离和审计事务语义不回归；
- 聚焦测试和受影响模块的标准验证通过；
- 没有越过第 8 节列出的产品决策、真实环境授权与发行门禁；
- 交付结论只声明 F01/F02/F03，不宣称企业主线、CL-01～CL-08 或正式发行全部完成。

## 2. 开始前必须执行

### 2.1 阅读约束

完整阅读：

- `/home/maoyd/siq/AGENTS.md`
- `/home/maoyd/siq/siq-agent-security/AGENTS.md`
- `docs/development/enterprise-comprehensive-acceptance-review-20260926.md`
- `docs/development/main-branch-integration-20260926.md`
- `docs/development/deepseek-enterprise-mainline-closeout-handoff-20260926.md`
- `packages/contracts/enterprise-discovery-schedule.v1.md`
- `packages/contracts/enterprise-discovery-schedule-pending-list.v1.md`

若实际修改 React 文件，必须先完整阅读：

- `/home/maoyd/.agents/skills/vercel-react-best-practices/SKILL.md`

本任务正常情况下不需要修改 React；不要为了“顺便展示”而扩展前端。

### 2.2 核对基线与工作树

执行：

```bash
cd /home/maoyd/siq/siq-agent-security
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

预期起点是干净的 `main`，且本地与远端均为：

```text
2ab1ce2546b616675757ebc59244086aa094bbc0
```

若 HEAD 已前移，不得 reset 或覆盖新成果。先逐项阅读新提交，确认本任务是否已被其他窗口实现；已完成的工作不得重复实现。若工作树已有改动，先识别归属并避开，不得清理、还原或代为提交。

### 2.3 读取当前实现与测试

至少阅读：

- `apps/control-api/app/main.py`
- `apps/control-api/app/routers/discovery_schedule_pending.py`
- `apps/control-api/app/routers/discovery_schedule_confirmation.py`
- `apps/control-api/app/routers/export.py`
- `apps/control-api/app/tests/test_discovery_schedule_pending.py`
- `apps/control-api/app/tests/test_discovery_schedule_confirmation.py`
- `apps/control-api/app/tests/test_ocsf_export.py`
- `apps/control-api/app/tests/test_ocsf_export_closeout.py`
- `edge/agent/discovery_schedule_fetch_linux.go`
- `edge/agent/discovery_schedule_fetch_linux_test.go`
- `edge/agent/confirm_schedule_linux.go`
- `edge/agent/confirm_schedule_linux_test.go`
- `edge/agent/setup_enterprise_linux.go`
- `edge/agent/setup_enterprise_linux_test.go`
- `edge/agent/main.go`
- `README.md`
- `README.en.md`
- `docs/operations/enterprise-production-runbook-v1.md`（如路径已变化，用 `rg --files` 定位当前文件）

同时用 `rg` 核对所有生产者和消费者，不要假设任务书列出的文件名就是唯一入口。

## 3. 已完成事项：禁止重复开发

以下能力已经在主线存在，本任务不得重新设计或另造平行实现：

- 企业四入口导航、权限事实、风险、策略、运行时绑定、环境接入和审计查询 UI；
- OpenClaw / Hermes 原生采集协议及其负向边界；
- 周期计划创建、管理、确认、tick、撤销、退休与恢复；
- 设备侧待确认周期计划列表端点 `GET /edge/v1/discovery-schedules`；
- 部署预览、影响、执行期绑定身份复验和回执核验；
- 批量部署后端合同与只读草稿 UI；
- 审计精确查询、关联查询和 OCSF 基础 NDJSON 导出；
- PostgreSQL 迁移 / 事务聚焦验收、企业浏览器 30/30 验收；
- 主线汇总、导入闭包检查、正式构建和远端推送。

尤其注意：`packages/contracts/enterprise-discovery-schedule-pending-list.v1.md` 末尾仍可能保留“尚未在 `app/main.py` 注册”的历史文字，但当前 `apps/control-api/app/main.py` 已经注册该路由。F03 必须修正文档状态，不得因此再注册一次或新增第二个路由。

## 4. F01：Edge 待确认周期计划自动发现

### 4.1 用户问题

服务端已经允许已注册设备只读枚举自己的 `pending_confirmation` 周期计划，但 Linux Edge CLI 仍只有：

```text
confirm-discovery-schedule --schedule-id ID
```

操作者必须从组织端复制 ID，破坏“安装后自然接入当前环境”的体验。需要补充一个**发现待办**入口，但不能把发现等同于授权或自动替用户选择计划。

### 4.2 必须实现的 CLI 行为

在既有 `confirm-discovery-schedule` 命令上新增：

```text
--discover
```

来源参数必须保持严格互斥：

```text
--intent FILE | --schedule-id ID | --discover | --resume
```

规则：

1. `--discover` 使用当前本地设备身份和控制面地址，调用现有只读端点：

   ```text
   GET /edge/v1/discovery-schedules?limit=...
   ```

2. 发现阶段只允许 GET；不得创建日志、签名、确认、tick、扫描任务、权限或其他业务写入。
3. 列表为 0 条：输出固定、诚实、可操作的提示，说明“当前设备没有待确认计划；请在组织端为该设备创建计划后重试”。纯只读 `--discover` 查询可返回成功；若调用同时带确认选项，则必须失败，因为没有发生确认。两种路径均不得声称设备已完成周期接入。
4. 列表恰好 1 条，且所有页均无 `integrity_failed`：进入现有预览路径，完整展示设备、租户、环境、范围、周期、预算、有效期和意图摘要。
5. 列表多于 1 条：不得自动挑选。输出有界的候选 `schedule_id`、`intent_digest`、状态和周期时间，要求操作者用 `--schedule-id` 明确选择；本次不确认、不写日志。
6. 任意一页出现 `integrity_failed`：失败关闭。只允许输出受控的 schedule ID 和固定错误原因，不输出不可信 intent、路径、异常正文或凭据；不得因同时存在一个合法项目就继续自动选择。
7. 无确认参数时仍是预览。真正确认仍必须满足现有二选一：

   ```text
   --interactive
   --confirm-intent-sha256 <64 位小写十六进制摘要>
   ```

8. 交互确认必须是真实终端，默认取消；管道输入不算同意。
9. `--resume` 继续只重发原有持久请求，不重新发现、不重新签名、不续签。
10. 不新增“默认确认”“首条即确认”“安装范围确认复用为周期确认”等捷径。

### 4.3 客户端解析与网络边界

新增一个 Linux 内部只读客户端，例如：

- `edge/agent/discovery_schedule_list_linux.go`
- 对应 `*_test.go`

非 Linux 如编译确需桩文件，可增加最小 `*_other.go`，不得假装其他平台已原生验收。

必须满足：

- 复用 `Client` 的已验证设备身份、Bearer 凭据、控制面 origin 和版本头；
- 禁止重定向；
- 使用 `http.NewRequestWithContext`，取消后不得继续成功返回；
- 每页设置明确的响应字节上限；超限失败关闭；
- JSON 顶层及 item 字段采用精确字段集，不接受额外字段；
- `schema_version` 必须等于 `enterprise-discovery-schedule-pending-list/v1`；
- `evaluated_at` 必须为合法 UTC 时间；
- `schedule_id`、`intent_digest`、`revision`、`status` 逐项严格校验；
- 每个 intent 继续复用现有 `parseDiscoverySchedule`、摘要和设备身份核验；不得复制一套宽松解析器；
- `next_cursor` 为空才结束；条目 ID 必须严格升序且大于请求 cursor，非空 `next_cursor` 必须等于本页最后一个条目 ID；重复、回退、跳跃、空页伪造推进或循环游标均失败关闭；
- 设置总页数和总条目上限，超过即明确报告“结果过多，需组织端整理或使用明确 ID”，不得无限分页；
- 任何页面失败均不把已加载部分当作完整列表；
- 不把服务端错误正文、URL 中潜在敏感查询、Bearer、设备 secret 写入日志或终端。

客户端发现结果只在内存中使用，不落 `localStorage`、普通文件或新的状态文件。只有进入既有显式确认流程后，才允许沿用既有私密 journal 语义。

### 4.4 `setup-enterprise` 的最小衔接

不要让首次注册流程等待组织管理员创建计划，也不要在同一命令里无限轮询。组织侧计划必须在设备身份存在后创建，这个时序不能用假数据绕过。

本轮只做以下最小衔接：

- `setup-enterprise --help`、README 和 runbook 应告诉新设备操作者：注册和服务配置完成后，可在组织端创建周期计划，再执行 `confirm-discovery-schedule --discover --interactive`；不得为此给冻结的 `enterprise-setup/v1` NDJSON 新增未升版 phase；
- 已注册设备仍可在 `setup-enterprise` 中使用现有 `--schedule-id` / `--resume-schedule`；
- 不要求给 `setup-enterprise` 新增 `--discover-schedule`。如实现者认为必须新增，先在交接记录中给出必要性与状态机证明，并停止等待主开发者确认，不得自行扩展。

### 4.5 F01 允许修改范围

主要允许：

- `edge/agent/discovery_schedule_list_linux.go`（新增）
- `edge/agent/discovery_schedule_list_linux_test.go`（新增）
- `edge/agent/discovery_schedule_fetch_linux.go`（仅复用所需的小型提取）
- `edge/agent/confirm_schedule_linux.go`
- `edge/agent/confirm_schedule_linux_test.go`
- `edge/agent/setup_enterprise_linux.go`（仅帮助提示，不改变进度 wire）
- `edge/agent/setup_enterprise_linux_test.go`
- `edge/agent/main.go`（仅 usage 文案）
- `packages/contracts/enterprise-discovery-schedule-pending-list.v1.md`
- `packages/contracts/enterprise-discovery-schedule.v1.md`（只追加本次 CLI 增量，不改旧语义）

不得修改服务端计划创建、确认、tick、撤销、退休或调度算法，除非测试证明服务端现有响应违反已冻结合同；若发现此类问题，先记录并停止扩大范围。

### 4.6 F01 必须测试

至少覆盖：

- 0 条、1 条、多条计划；
- 多页恰好 1 条、多页多条；
- `integrity_failed` 单独出现、与合法 item 同页出现；
- 顶层和 item 额外字段拒绝；
- schema、时间、ID、digest、revision、status、intent 绑定异常拒绝；
- 响应超限、非法 JSON、尾随 JSON、重定向、401/404/409/500、网络失败；
- 游标不前进、循环、非法形态、页数 / 条目上限；
- context 在请求前取消、请求中取消、响应后取消；
- 发现阶段零 POST、零本地 journal 写入；
- 单项预览不确认；精确摘要和真实终端确认继续走既有确认路径；
- 多项永不自动确认；
- `--discover` 与其他来源参数冲突时在网络请求前拒绝；
- 帮助内容明确“发现不等于授权、确认不授予业务权限”。

优先扩充现有测试夹具，不新建庞大的平行测试框架。

## 5. F02：OCSF 导出截断声明

### 5.1 现有缺口

`GET /api/v1/export/ocsf` 当前按 `limit` 查询并返回 NDJSON，但调用方无法区分：

- 本次已经返回全部匹配事件；
- 仍有更多事件，只是被 `limit` 截断。

这会诱使调用方把有限窗口误当作完整审计归档。本轮只补“截断事实”，不新增删除、归档、游标或全量导出工作流。

### 5.2 冻结后的响应语义

在现有成功响应上新增精确响应头：

```text
X-SIQ-Export-Truncated: 0 | 1
```

实现规则：

1. 查询 `limit + 1` 条；
2. 正文最多返回前 `limit` 条；
3. 查到第 `limit + 1` 条时头值为 `1`，否则为 `0`；
4. 审计 summary 中的 `count` 必须是实际返回条数，不是探测条数；
5. 不把额外探测行写入正文、日志、审计或错误；
6. 保留 `Cache-Control: no-store`；
7. 保留 `application/x-ndjson`、每行一个完整 JSON、末尾换行和空结果空正文；
8. 保留时间升序再按 ID 的稳定排序、租户隔离、权限与参数校验；
9. 审计写入或提交失败时继续失败关闭，不返回看似成功的正文；
10. 不宣称该接口是完整归档，不增加 `published`、`verified` 或类似状态。

### 5.3 合同文件

先用 `rg --files packages/contracts | rg -i 'ocsf|export'` 确认是否已有公共合同：

- 若已有匹配合同，按仓库版本规则更新或升版；
- 若没有，新增 `packages/contracts/enterprise-ocsf-export.v1.md`，记录端点、认证、参数、排序、NDJSON、`no-store`、截断头、导出审计和非归档边界。

不得仅改实现而不冻结消费语义。

### 5.4 F02 允许修改范围

- `apps/control-api/app/routers/export.py`
- `apps/control-api/app/tests/test_ocsf_export.py`
- `apps/control-api/app/tests/test_ocsf_export_closeout.py`
- 新增一个聚焦测试文件（只有现有文件不适合承载时）
- 对应 `packages/contracts/` 合同
- F03 中的操作者文档

不得修改 OCSF 映射字段、Finding / AuditEvent 模型、数据库迁移、权限名或共享审计实现。

### 5.5 F02 必须测试

至少覆盖：

- 空结果：正文为空，`X-SIQ-Export-Truncated: 0`；
- 少于 limit、恰好 limit：均为 `0`；
- limit + 1 及更多：正文只有 limit 行，头为 `1`；
- 同时间戳按 ID 稳定排序；
- detection finding 与 API activity 两类均符合；
- 跨租户同标识 / 同时间戳隔离；
- 401/403、非法 class、非法 limit、非法和极端 since 在导出和成功审计前拒绝；
- `since` 时区归一不回归；
- 导出审计 `count` 等于返回行数，summary 不含正文；
- 审计或 commit 失败时无成功正文、无半提交；
- `Cache-Control: no-store`、媒体类型和 NDJSON 行完整性不回归。

## 6. F03：合同和操作者文档同步

只同步本次真实变化：

1. 修正 pending-list 合同中“尚未注册路由”的过期描述，改为当前主线已注册；
2. 记录 Edge `--discover` 的只读发现、零 / 单 / 多候选行为和独立确认边界；
3. README 中给出最短可执行的两阶段命令示例：

   ```bash
   edge-agent confirm-discovery-schedule --discover
   edge-agent confirm-discovery-schedule --discover --interactive
   ```

   第一条是只读预览，第二条才可能在明确 yes 后确认；两者均不授予智能体业务权限。
4. 英文 README 与中文事实一致；不要求逐字翻译，但安全结论不能不同；
5. runbook 说明 0 条、多条、完整性失败和恢复日志的排障方式；
6. OCSF 文档说明 `X-SIQ-Export-Truncated=1` 代表还有更多匹配记录，本接口不是完整归档；
7. 新增交接文件：

   `docs/development/enterprise-post-merge-remaining-closeout-handoff-20260926.md`

交接文件必须包含：实际文件、行为变化、安全不变量、测试命令与数量、未执行检查、外部门禁、未完成项和“未提交、未推送、未部署，待主开发者复核”（除非该窗口另获明确提交/推送授权）。

## 7. 安全不变量

本任务所有实现必须同时遵守：

- `tenant_id`、环境和设备只来自验证身份，不接受客户端覆盖；
- UI / CLI 可见性不是授权；服务端权限与设备凭据校验不得弱化；
- 周期列表只枚举当前设备自身的 `pending_confirmation`；
- “发现”“预览”“已注册”“服务 active”均不等于扫描成功、运行时绑定或防护生效；
- `effective`、`readback_verified`、`enforcement_verified` 不得互相推导；
- 未知、缺失、截断和完整性失败必须诚实显示，不能转成空、0 或成功；
- 密钥、令牌、设备 secret、私钥、原始配置和错误正文不得进入日志、审计、文档或测试快照；
- 不把令牌写入 `localStorage` / `sessionStorage`；
- 取消、预览和发现阶段均为零业务写入；
- 高风险写操作的审计失败必须失败关闭；
- context 取消后不得返回成功；
- 不通过删除测试、放宽解析、`String()` / `str()` 归一、trim 或大小写转换掩盖合同违约。

## 8. 明确禁止实施的剩余事项

以下是真实剩余门槛，但**不属于本任务开发授权**：

### 8.1 共享运行时影响与批量执行

当前冻结结论仍是：

- `shared_runtime_occupants = unknown`
- `skill_isolation = not_established`
- `execution_confirmation_supported = false`

因此不得：

- 把 `binding_evidence_readiness.py` 或 `evidence_topology.py` 随意公开成新 HTTP API；
- 把内部只读投影描述成完整运行时证据；
- 在前端调用 `executeBatchDraft`；
- 新增批量执行 / 回滚按钮；
- 将 `execution_confirmation_supported` 改为 true；
- 用“只有一条绑定”推断沙箱独占。

这些动作需要先冻结独占性标准、证据有效期、公开 wire 合同和用户措辞。

### 8.2 审计保留与删除

当前决策是只记录保留 / 删除治理缺口，不实现删除或归档执行。不得新增定时删除、TTL、清表、归档迁移或“已满足合规”声明。

### 8.3 真实 OpenShell 行为探针

`enforcement_verified` 仍无可信生产者。获取该证据需要在受控 canary 上执行 `sandbox upload` + `sandbox exec`，且策略写入为整段替换，会产生旧规则暂时消失的窗口。

本任务书不是这类写入型探针的授权。不得：

- 启停真实网关或沙箱；
- 执行 `policy set`、upload、exec；
- 修改真实 OpenShell 策略；
- 把只读结构核查提升为行为阻断证据。

若确有必要，必须停止并向用户单独说明目标 canary、备份 / 回滚、占用确认、精确写入窗口和证据脱敏方案，取得一次性明确授权后另开任务。

### 8.4 发行、签发和部署

不得创建正式安装包、签名、标签、发布、部署或重启生产服务。受控签发入口、正式发布身份和部署窗口仍是外部门禁。

## 9. 禁止操作

- 不读取 IDE 中打开的 `admin-password.private`；
- 不读取或输出真实 `.env`、密码、令牌、私钥、设备种子；
- 不扫描真实用户目录；
- 不连接或修改现有生产 / 开发数据库；
- 不注册真实设备，不提交真实采集任务；
- 不安装新依赖，不修改 lockfile；
- 不运行 `git reset --hard`、`git checkout --`、`git clean`；
- 不覆盖其他窗口成果；
- 不做无关重构、全仓格式化或导航 / UI 新功能；
- 未获该窗口用户明确授权时，不创建提交、分支、推送或 PR。

## 10. 验证计划

坚持“聚焦优先、一次全量”的收口原则。不要为已证明的无关模块重复新增测试。

### 10.1 F01 聚焦验证

在 `edge/agent` 执行：

```bash
GOPROXY=off go test -race -count=1 -run 'Test.*(DiscoverySchedule|ConfirmSchedule|SetupEnterprise)' ./...
GOPROXY=off go vet ./...
gofmt -l .
```

`gofmt -l .` 对本任务修改文件必须无输出。若全目录出现他人既有输出，精确记录，不得顺手格式化无关文件。

### 10.2 F02 聚焦验证

在 `apps/control-api` 执行：

```bash
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_ocsf_export.py \
  app/tests/test_ocsf_export_closeout.py

uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_discovery_schedule_pending.py \
  app/tests/test_discovery_schedule_confirmation.py

uv run --no-sync ruff check \
  app/routers/export.py \
  app/routers/discovery_schedule_pending.py \
  app/tests/test_ocsf_export.py \
  app/tests/test_ocsf_export_closeout.py
```

若实际新增测试文件，将其加入命令。不要通过 `-k` 排除失败用例来宣称通过。

### 10.3 受影响模块全量

产品代码完成并通过聚焦检查后，只运行一次：

```bash
cd /home/maoyd/siq/siq-agent-security/edge/agent
GOPROXY=off go test -race -count=1 ./...
GOPROXY=off go vet ./...

cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run --no-sync pytest -q
uv run --no-sync ruff check app
```

本任务默认不改 Web，因此不要求重跑全部前端测试或浏览器 smoke。若实现者自行触碰 Web，必须解释必要性，并补：

```bash
cd /home/maoyd/siq/siq-agent-security/apps/web
npm test
npm run build -- --outDir "$(mktemp -d /tmp/siq-remaining-closeout-web-XXXXXX)"
```

正式构建必须 `VITE_DEV_MODE=false`，不得部署模拟身份构建。

### 10.4 合同和仓库检查

```bash
cd /home/maoyd/siq/siq-agent-security
git diff --check
git status --short
```

若仓库已有合同扫描器和导入闭包脚本，使用当前主线记录中的原命令再跑一次。不要凭记忆虚构命令；从 `docs/development/main-branch-integration-20260926.md` 或 `scripts/` 中定位真实入口。

### 10.5 不需要执行的验证

除非代码实际触及相关边界，否则本任务不需要：

- 一次性 PostgreSQL 容器；
- 企业前端 30/30 浏览器旅程；
- OpenClaw / Hermes 原生采集全量；
- Windows / macOS 原生验收；
- 真实 OpenShell；
- 正式安装包生成或签名。

## 11. 验收判定

### 11.1 可判定完成

只有以下全部成立时，才可写“F01/F02/F03 完成”：

- `--discover` 能安全处理零 / 单 / 多待办，并保留独立确认；
- 列表解析、分页、字节 / 页数 / 条目预算和取消均失败关闭；
- 发现与预览阶段零业务写；
- OCSF 截断头在所有成功响应上准确；
- OCSF 正文、审计、租户、权限和失败关闭语义不回归；
- 合同、README 中英文和 runbook 与实现一致；
- 聚焦与受影响模块全量验证通过；
- `git diff --check` 通过；
- 没有读取秘密、执行真实行为探针、发布或部署。

### 11.2 必须如实标为未完成

以下仍应列为外部 / 决策门槛：

- 新注册设备仍需组织端在注册后创建周期计划；本轮不自动创建计划；
- 共享运行时占用、Skill 独立隔离和完整影响证据仍未知；
- 企业批量执行 / 回滚 UI 仍不开放；
- `enforcement_verified` 仍需另行授权的真实行为探针；
- 审计保留 / 删除规则尚未形成执行治理；
- 正式签发、发行、部署和真实设备验收未完成。

## 12. 交付格式

最终回复必须简洁但可核验，包含：

1. 实际修改 / 新增文件；
2. F01 的零 / 单 / 多候选行为与确认边界；
3. F02 截断头的准确语义；
4. 精确测试命令、通过数量、失败数量和未运行项；
5. 安全不变量核对；
6. 未完成项和外部门禁；
7. Git 状态；
8. 明确声明：

   > 仅完成企业主线合并后的 F01/F02/F03 收口，不代表 CL-01～CL-08、真实 OpenShell 行为验证或正式发行全部完成。

若发现不在允许范围内的真实高危缺陷，只做最小复现和证据记录，停止扩展修改并交回主开发者裁决。

## 13. 工作量预估

在主线保持稳定、依赖已就绪的前提下：

| 工作包 | 预计净开发时间 |
| --- | ---: |
| F01 客户端、CLI、负向测试 | 1.0～1.5 个工程日 |
| F02 导出截断合同与测试 | 0.25～0.5 个工程日 |
| F03 文档、全量回归、交接 | 0.5 个工程日 |
| 合计 | 1.75～2.5 个工程日 |

若出现并发工作树冲突、主线前移或已有测试基线失败，应先归因，不把排障时间伪装成上述功能开发完成度。
