# CL-06-CHANGE-EXECUTION-EVIDENCE-CLOSEOUT 交付记录

日期：2026-09-26
范围声明：本记录只覆盖总任务书（`docs/development/cl06-deepseek-change-execution-evidence-closeout-taskbook.md`）
CL-06 的 **CL-06-CHANGE-EXECUTION-EVIDENCE-CLOSEOUT** 子任务——既有“变更执行记录”链路的关联、权限、证据投影与前后端解析收口。
不代表 CL-06、完整审计链、保留治理或项目整体完成。

> 仅完成 CL-06-CHANGE-EXECUTION-EVIDENCE-CLOSEOUT。未提交、未推送、未部署；未新增业务能力，不代表完整审计链、保留治理、CL-06 或整体项目完成。

## 9. 主开发者验收修复（2026-09-26）

复核接受本交付的四项修复。新增一个前端负例发现日期校验仍接受
`2026-09-23Z` 等不完整时间戳；修复前聚焦文件 **1 failed / 4 passed**。
补完整 UTC 日期时间格式检查，再复用原 UTC 回历校验；保留后端秒精度和微秒格式，
不改变 wire 字段或状态枚举。新增用例同时覆盖日期后直接 Z、空格分隔及省略秒。

本轮实跑：

```bash
# apps/control-api
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_change_execution.py app/tests/test_change_execution_evidence_boundaries.py \
  app/tests/test_deployment_verify.py app/tests/test_deployment_verify_boundaries.py
uv run --no-sync ruff check app/routers/change_execution.py app/tests/test_change_execution_evidence_boundaries.py
# apps/web
npm test -- src/api/changeExecution.test.ts
VITE_DEV_MODE=false npm run build -- --outDir /tmp/siq-change-execution-review-zoW0Vt
```

结果：后端 **60 passed**、前端 **5 passed**；Ruff、正式模式标准构建、
`git diff --check` 通过。构建目录由 mktemp 独占创建，未覆盖 dist。后端仅既有
Starlette/httpx 弃用警告，未安装依赖、未跑全仓或浏览器。§6 临时跨端样本已由
交付者删除，因此本轮未重放该证据，也不将其计入主开发者重新执行结果。

待裁决项处理：

- 保留 `enforcement_verified`：适配器部署合同明确列为合法保留值，不能仅因暂缺
  生产者就删除合同映射；修正文内“全部为真实产出值”的过强注释。没有新增生产者，
  不表示当前后端具备行为验证能力。
- 非字符串 level 的 `none` 兼容行为与回滚优先提示本轮保持；两者不输出绿色成功，
  回滚说明明确要求核对当前执行端，不能据此推断当前配置已验证。
- `ui/verification.ts` 为共享的另一消费链，本轮未改；其保留态映射仍须对应所有者
  核对来源和合同，不能用本轮通过宣称所有页面的证据语义均已收口。

仅修改本任务前端解析及测试、后端解释注释和本交接记录；业务权限、共享 UI、
执行链、schema 均未改。未提交、未推送、未部署。该子项通过上述定向验收，
CL-06 完整审计链和保留治理仍未完成。

## 1. 实际修改文件与修改前状态

开始前逐一核对：任务书所列五个文件在工作树中**均无未提交改动**（`git status --short -- <五个文件>` 输出为空，均为 HEAD 状态），可独占修改。未触碰任何他人未跟踪文件。

| 文件 | 修改前 | 修改后 |
| --- | --- | --- |
| `apps/control-api/app/routers/change_execution.py` | HEAD（干净） | 已修改（+12/−7，见 §4） |
| `apps/control-api/app/tests/test_change_execution.py` | HEAD（干净） | **未修改**（仅被新文件导入其辅助函数） |
| `apps/web/src/api/changeExecution.ts` | HEAD（干净） | 已修改（+13/−4，见 §4） |
| `apps/web/src/api/changeExecution.test.ts` | HEAD（干净） | 已修改（+21，新增负例） |
| `apps/control-api/app/tests/test_change_execution_evidence_boundaries.py` | 不存在 | 新增（7 个边界测试） |
| `docs/development/enterprise-change-execution-evidence-closeout-handoff.md` | 不存在 | 新增（本记录） |

默认只读文件 `apps/web/src/components/ChangeExecutionDialog.tsx`、`packages/contracts/change-execution.v1.schema.json`
**未修改**。响应字段与枚举未新增/删除/改名（仅修正取值来源）。未触碰 models/schemas/迁移/鉴权/审计实现/其他开发线文件。

## 2. A–D 结论

| 工作包 | 结论 |
| --- | --- |
| A 后端对象关联与权限边界 | **正确**（新增 5 个边界测试全部通过，无需改代码） |
| B 执行证据投影与真实来源一致 | **已修复**（2 个真实缺陷，见 §4） |
| C 前端解析与证据说明收口 | **已修复**（2 个真实缺陷，见 §4） |
| D 前后端闭环核对与交接 | **正确**（真实后端样本 3 组，经真实前端解析器消费通过，见 §6） |

## 3. 证据字段 → 真实生产者 → 后端投影 → 前端说明

后端投影代码：`app/routers/change_execution.py::_deployment`。前端说明：`apps/web/src/api/changeExecution.ts::executionEvidence`。

### 部署记录

| 线字段 | 真实生产者（`deployment.verification` / 列） | 投影 | 前端说明 |
| --- | --- | --- | --- |
| `id`/`environment_id`/`binding_id`/`target`/`created_at`/`status` | Deployment 列（`policies.create_deployment`、`deployment_submission`、`batch_execution`、`environments`） | 原值（`status` 仅受 32 字符上限） | `deploymentStatus` 未知值 → “状态待核对” |
| `verification_level` | `policies.py:653` 写 `report.level`（生产仅 `readback_verified`（→config_readback）/`failed`）；`policies.py:694` 失败路径沿用既有 `level` 或缺失；`batch_execution.py:29`、`deployment_submission.py:237` 写 `level="failed"`；`stale`/`expired` 布尔 | 别名表 `readback_verified→config_readback`、`enforcement_verified→behavior_enforced`、`failed/error→failed`、`stale/expired→stale`；缺失→`none`；未识别→`unknown` | 无生产者或未知 → `unknown`（warn）；`config_readback` → “配置已读回，行为未验证” |
| `independent_result` | `deployment_verify.py:164` 写 `independent_attestation={result: verified\|mismatch\|unreachable\|no_receipt}` | 合同 result 直取；缺键→`not_checked`；存在但读不出→`unknown` | 仅证明**最近一次独立读回**，非当前运行状态 |
| `backend_mutated` | `policies.py:697`（`receipt.result == "applied"`）；`batch_execution.py:29`、`deployment_submission.py:237`（`False`） | 仅接受 `bool`，否则 `null` | 失败说明据其区分“已有改后端的证据”/“失败不证明没变化” |
| `error_digest` | `verification.apply_failed.error_digest`（`policies.py:694` 的 `error_reference`）；回退 `receipt.error_digest`（`policies.py:690`） | 仅接受 64 位 hex，否则 `null` | 仅在详情中展示 |

### 审计记录

| 线字段 | 真实生产者（AuditEvent） | 投影 | 前端说明 |
| --- | --- | --- | --- |
| `id`/`action`/`actor_id`/`resource_id`/`created_at` | `outbox.audit` 各调用点（`change.approve`、`deployment.create`、`deployment.verify`、`deployment.fail`、`deployment.receipt_verify`、`deployment.rollback*` 等） | 原值 | `auditAction` 未知 action → “其他审计操作” |
| `review_digest` | `policies.py:363/407`（审批/驳回时 `summary.review_digest`） | 仅接受 64 位 hex，否则 `null` | 有则展示 |
| `error_digest` | `policies.py:716`（部署失败）、`deployment_verify.py`（`error_reference`） | 仅接受 64 位 hex，否则 `null` | 有则展示 |

### 字段生产者归属小结（工作包 B 必答项）

- **确有生产者**：`status`、`verification_level`（`readback_verified`/`failed`）、`independent_result`、`backend_mutated`、`error_digest`、`review_digest`。
- **仅兼容历史值 / 缺当前生产者**：`enforcement_verified`（适配器合同保留名，`contracts.py:61` 明确“当前无后端可产出”）；`level="stale"/"expired"` 依赖 `stale`/`expired` 布尔，当前亦无生产者。
- **无生产者且已停止映射**：`behavior_verified`（详见 §4-B1）。
- **只能证明“过去某次读回”、不能证明当前运行状态**：`verification_level=config_readback`/`stale`、`independent_result=verified`。前端文案已如实标注（“历史读回证明当时配置一致，尚未证明实际工具调用受到拦截”；stale → “验证证据已过期”）。
- **`effective` 不代表行为已验证**：`deploymentStatus('effective')` 仅为“后端标记已生效”；`executionEvidence` 只有在 `verification_level === 'behavior_enforced'` 时才给 `ok`，且文案限定为“仅代表该次验证及其覆盖范围，不是持续保护保证”。

## 4. 真实缺陷的修复前后证据

先加聚焦负例 → 在**未修复实现**上运行并记录实际行为 → 最小修复 → 复跑。

### B1（后端）保留态 `behavior_verified` 被升级为行为证据

- 复现：`test_change_execution_evidence_boundaries.py::test_reserved_behavior_verified_level_is_not_upgraded`
  播种 `verification={"level": "behavior_verified"}` → 实际得到 `verification_level == "behavior_enforced"`（断言 `== "unknown"` 失败）。
- 生产者/合同依据：全仓检索不存在把 `behavior_verified` 写入 `Deployment.verification.level` 的生产者；
  `packages/contracts/openshell-capability-evidence.v3.md:13`、`openshell-policy-safety.v2.md:143` 明确其为**保留态、无生产者**，
  且属于 OpenShell **诊断**状态（`apps/agentshield/internal/openshell/types.go`），非部署验证合同的 level。
  故 `behavior_verified → behavior_enforced` 属“同名历史字段未经生产者核对即升级为可信行为证据”。
- 修复：从 `change_execution.py` 别名表删除 `"behavior_verified": "behavior_enforced"`，未识别 level 归 `unknown`（枚举不变）。
- 修复后：同一负例通过；`enforcement_verified`（合同内行为 fixture level）映射**保留**，未擅自删除。

### B2（后端）非对象 `independent_attestation` 被冒充为“没有检查”

- 复现：`...::test_present_but_unreadable_attestation_is_unknown_not_absent`
  播种 `{"level":"readback_verified","independent_attestation":"verified"}` → 实际得到 `independent_result == "not_checked"`（断言 `== "unknown"` 失败）。
- 依据：合同生产者 `deployment_verify.py:164` 只写对象；存在但读不出结果的证据不等于“没有做过独立读回”。
- 修复：显式区分“键缺失/为 null → `not_checked`”与“存在但非合同对象/非合同 result → `unknown`”（枚举不变）。
- 修复后：负例通过；既有 4 个参数化证据投影用例（无 attestation → `not_checked`）不受影响。

### C1（前端）`String()` 归一使数组/对象冒充枚举并产生绿色假象

- 复现：`changeExecution.test.ts::rejects array or object lookalikes masquerading as enum values`
  实测 `String(['denied']) === 'denied'`，`String({toString:()=>'allowed'}) === 'allowed'`，
  导致 `audit_access:['denied']`、`verification_level:['behavior_enforced']`、`independent_result:['verified']` 等被接受。
  实测危害：`independent_result:['verified']` + `verification_level:'behavior_enforced'` + `status:'effective'` 会走
  `executionEvidence` 的 `ok` 分支，渲染“已有行为验证记录”绿色标签——非法结构冒充成功。
- 修复：新增 `oneOf()`（`typeof === 'string' && allowed.includes(v)`），替换三处 `String(...).includes(...)`；
  同时补断言：未知 `verification_level` 值不得产生 `ok`。
- 修复后：同一负例通过；合法枚举与 `String` 无关的既有断言全部保持。

### C2（前端）`Date.parse` 滚动接受不存在的日历日期

- 复现：`changeExecution.test.ts::rejects calendar dates that do not exist but Date.parse rolls over`
  实测 `Date.parse('2026-02-30T00:00:00Z')` 与 `Date.parse('2026-02-29T00:00:00Z')` 均返回有限值（滚动到邻近日期），
  原检查只做 `endsWith('Z') && Number.isFinite(Date.parse(v))`，故明显不存在的日期被接受。
- 修复：保留“≤40 字符 + 以 Z 结尾 + `Date.parse` 有限”不变，另加 UTC 回读——把前 10 位 `YYYY-MM-DD` 与
  由时间戳还原的 UTC 年月日比较，滚动日期即不等而拒绝。不额外收窄后端实际输出格式
  （`2026-09-23T00:00:00Z`、`…T00:00:00.123456Z`、闰日 `2024-02-29T00:00:00Z` 均仍被接受，已断言）。
- 修复后：负例通过，正向格式断言通过。

## 5. 所有实际执行命令、数量、失败、警告与未执行项

后端（`cd /home/maoyd/siq/siq-agent-security/apps/control-api`）：

| 命令 | 结果 |
| --- | --- |
| `uv run --no-sync pytest -o addopts='' -q app/tests/test_change_execution.py`（基线） | 8 passed |
| `... app/tests/test_change_execution_evidence_boundaries.py`（未修复，复现） | **2 failed, 5 passed** |
| `... test_change_execution.py test_change_execution_evidence_boundaries.py`（修复后） | 15 passed |
| `... test_deployment_verify.py test_deployment_verify_boundaries.py`（证据生产者，直接相关） | 45 passed |
| `uv run --no-sync ruff check app/routers/change_execution.py app/tests/test_change_execution.py app/tests/test_change_execution_evidence_boundaries.py` | All checks passed |

前端（`cd /home/maoyd/siq/siq-agent-security/apps/web`）：

| 命令 | 结果 |
| --- | --- |
| `./node_modules/.bin/vitest run src/api/changeExecution.test.ts`（基线） | 2 passed |
| 同命令（未修复，复现） | **2 failed, 2 passed** |
| 同命令（修复后） | 4 passed |
| `VITE_DEV_MODE=false ./node_modules/.bin/tsc -b` | 通过 |
| `VITE_DEV_MODE=false ./node_modules/.bin/vite build --outDir /tmp/siq-as-web-build-6zBMYv --emptyOutDir` | 通过（`index.html` + `assets/` + `fonts/`；未覆盖 `dist`） |

最后检查：`git diff --check` 干净；新文件 `test_change_execution_evidence_boundaries.py` 无尾随空白。
未产生 `package.json`/锁文件改动（`git status` 中 `package*.json`/锁文件无变化）。

警告：仅既有的 `starlette.testclient`（httpx 弃用）与 `VIRTUAL_ENV` 不匹配提示，与本任务无关。
未执行项：未跑全仓全量测试（按要求减少重复）；未跑浏览器冒烟/截图（未改 UI）；
未连接真实服务或真实数据库（未要求）；未提交/推送/部署（禁止）。

## 6. 前后端样本消费证据（工作包 D）

用隔离合成数据、经**真实端点**导出、由**真实前端解析器**消费（未重写测试专用解析器，未连接真实接口）。

```text
apps/control-api 隔离 TestClient + 测试 SQLite（conftest 既有机制，SIQ_AS_DEV 合成身份）
  → 真实 GET /api/v1/change-requests/{cr_id}/execution（断言 200）
  → 原样导出 JSON 到独立临时目录（仅本任务合成数据）
  → apps/web vitest 导入真实 parseChangeExecution / executionEvidence 读取并断言
```

- 样本目录：`/tmp/siq-as-cl06-samples-XYguBx`（`mktemp -d` 独占创建，仓库外，未覆盖任何现有证据）

| 样本 | 场景 | 身份（权限） | sha256 | bytes |
| --- | --- | --- | --- | --- |
| `normal.json` | 正常：真实部署 + 3 条精确关联审计（含 `deployment.create`） | tenant_a + auditor（policy:read+env:read+audit:read） | `747cecaa…05a24d70` | 1331 |
| `degraded.json` | 降级：failed(mismatch)/rolled_back/保留 level/stale 并存 | 同上 | `2ad4108f…cff0a33` | 2041 |
| `no-audit.json` | 无审计权限：审计正文/计数/截断均不返回 | viewer（policy:read） | `f80b04d4…9e7786f1` | 646 |

前端消费断言（`zz-cl06-sample-consume.tmp.test.ts`，3 tests passed）：三组样本均被真实解析器接受；
`degraded` 中保留 level 行投影为 `unknown` 且 `executionEvidence` 非 `ok`，failed → err，stale → err，
rolled_back → “已记录回滚”；`no-audit` 断言 `denied` + 空数组 + 非截断 + 环境名 null；样本全文不含 `SHOULD-NOT-EXPORT`。
两个临时测试文件（后端导出、前端消费）与临时样本均已在验证后删除，未留在工作树。

后端口径旁证（导出样本实际值）：`degraded` 行依次为
`effective/stale`、`effective/unknown`（保留 level）、`rolled_back/config_readback`、`failed/config_readback+mismatch+backend_mutated=true+error_digest=aa…`；
`no-audit` 为 `denied/[]/false/环境名 null`。

## 7. 已知边界与主开发者需要决定的事项

1. **`enforcement_verified` 别名保留但无当前生产者**：适配器合同将其定义为“行为 fixture 验证通过”的合法 level
   （`contracts.py:61`），故保留映射；若主开发者认为“无生产者即不可映射”，需连同合同一并处理。
2. **`apps/web/src/ui/verification.ts` 仍映射 `behavior_verified → behavior_enforced`**：属另一消费者（DEV13-C），
   不在本任务允许修改范围，未改动。若 B1 结论成立，其所有者需评估是否同样收紧。
3. **非字符串 `level`（对象/数组）投影为 `none`**：现有 `test_change_execution.py` 已锁定该行为，方向保守（非绿色），
   未改动；如需更诚实的 `unknown` 需单独决策并同改该既有用例。
4. **`expanded` 上限 100/200 不是全量历史**：既有窗口，未新增分页能力，前端文案已提示“更早记录仍保留在控制面”。
5. **失败/异常响应（401/403/404）不带 `Cache-Control: no-store`**：任务书只要求成功响应保持 no-store，且全仓一致，未改动；
   如需覆盖错误响应需在中间件层统一决策。
6. **`executionEvidence` 中 `rolled_back` 分支先于 `independent mismatch` 分支**：回滚记录会以 warn 覆盖 mismatch 的 err 显示，
   但仍非绿色且文案要求核对执行端；调整分支优先级属展示口径决策，未擅自改动。

## 8. 声明

> 仅完成 CL-06-CHANGE-EXECUTION-EVIDENCE-CLOSEOUT。未提交、未推送、未部署；未新增业务能力，不代表完整审计链、保留治理、CL-06 或整体项目完成。
