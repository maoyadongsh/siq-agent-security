# CL-05-RECEIPT-VERIFIER-CLOSEOUT 交付记录

任务：独立回执验证的目标一致性与异常输入收口。
范围：仅 `apps/control-api/app/deployment_verify.py` 与对应测试；不新增接口、巡检、
自动修复或策略发布能力。本记录只声明本子任务完成，**不**声明 CL-05、完整独立效果
证明或整体项目完成。

状态：**未提交、未部署**，待主开发者复核。

---

## 1. 实际修改与新增文件

| 文件 | 变更 |
| --- | --- |
| `apps/control-api/app/deployment_verify.py` | 修改（收口逻辑） |
| `apps/control-api/app/tests/test_deployment_verify_boundaries.py` | 新增（28 个用例） |

未修改 `app/tests/test_deployment_verify.py`（原有 8 个用例全部保留、原样通过）。
未触碰 `routers/policies.py`、适配器、`models.py`、`schemas.py`、迁移、共享审计/
权限/错误处理、前端、Edge、Connector、安装器、依赖、README、总任务书。

## 2. 所依据的类型与语义合同（先核对，后修改）

- `PolicySnapshot.target: str`、`PolicySnapshot.revision: str`
  （`adapters/openshell/contracts.py`）。真实后端 `cli_backend.read_effective_policy`
  回显请求 `target`，`client.py` 与 `fake_backend.py` 同样回显。
- CLI 路径 revision 的合法值域由 `policy_safety._REVISION_RE = [1-9][0-9]*` 约束：
  **正整数字符串**（`validate_revision`）；`_parse_set_receipt`/`parse_policy_output`
  只产出该形态，且非空、非零。
  此约束不能泛化为全部适配器的公共值域：fake 后端无快照时使用 `"0"`。
  本验证器保留有界非空字符串逐字比较，不新加正整数或非零限制。
- 回执侧 `DeploymentReceipt.backend_revision: str`（适配器产出，经 `validate_revision`）；
  Edge 侧 `EdgeReceiptVerification.backend_revision: str | None, max_length=128`
  （`schemas.py:121`）。
- `Deployment.target: String(128)`、`Deployment.receipt/verification: JSON`
  （`models.py:518-537`）；`deployment.receipt` 亦可被置为 `error_reference()` 的错误
  字典（`routers/policies.py:680`），Edge 通道写入 `body.verification` 的字典
  （`routers/environments.py:579`）。
- 结果语义为既有四态 `verified / mismatch / unreachable / no_receipt`
  （`docs/agent-security-round4-20260820.md` §2），消费方
  `routers/change_execution.py:33,90-98` 仅投影这四态，未知值降级为 `unknown`。
  **未新增结果枚举、响应字段或 verifier 版本。**

结论：比较阶段只接受合同类型 `str` 的非空 revision；`deployment.target` 与读回
`snapshot.target` 均为 `str`，逐字比较即可，不做归一。

## 3. 风险点核对结果（真实函数 + 合成部署行复现）

复现方式：新增边界用例先对**修复前**源码运行，记录失败即复现；修复后再运行应通过。
修复前边界文件 22/28 失败，修复后 28/28 通过。

| # | 风险点 | 修复前观测 | 结论 |
| --- | --- | --- | --- |
| 1 | receipt 为字符串/数组/数字/布尔等非对象 | 未处理 `AttributeError: 'X' object has no attribute 'get'`（`deployment_verify.py:46`） | 已复现 |
| 2 | `backend_revision` 为 `""`/空白/布尔/数字/数组/对象/超长 | 经 `str()` 变成可比较值并**继续构造、访问后端**（`_forbid_backend` 哨兵暴露）；空白串甚至判 `verified` | 已复现 |
| 3 | 异常 `snapshot.revision` 与异常回执经 `str()` 相等 | `revision=7`（int）→ `str(7)="7"` 与回执 `"7"` 相等 → **`verified`** | 已复现 |
| 4 | `snapshot.target != deployment.target` 但 revision 相等 | **返回 `verified`**（`assert 'verified' != 'verified'`） | 已复现（高危） |
| 5 | receipt 带 `target` 且与部署目标冲突 | **返回 `verified`**；合同此前未处理该字段 | 已复现 |
| 6 | `verification` 列为非对象 | 未处理 `ValueError: dictionary update sequence ...`（`deployment_verify.py:78`） | 已复现 |
| 7 | 后端返回非预期结构（非 snapshot / 非 str 字段） | `AttributeError: 'object' object has no attribute 'revision'`，或 `str()` 归一后给出确定结论（`verified`/`mismatch`） | 已复现 |
| 8 | 后端抛非 `AdapterError` 异常 | 原本即向上抛出、不吞异常（无回归） | 已有保护 |
| 9 | 合法同目标同 revision → `verified` | 既有用例通过 | 已有保护 |
| 10 | 合法 revision 不一致 → `mismatch` + Finding 幂等 + outbox | 既有用例通过 | 已有保护 |

未验证项：真实 OpenShell 网关上"错误目标"是否可能在真实适配器返回（当前 CLI/HTTP/
fake 后端均回显请求 target，故该分支为纵深防御，本任务未在真实网关复现）。

## 4. 修复前后对照（重点：错误目标是否曾被判 verified）

- **修复前**：读回目标与部署目标不一致、但 revision 相同时，`verify_deployment_receipt`
  返回 **`verified`**；回执自述 `target` 与部署目标冲突、但 revision 相同时同样返回
  **`verified`**。即"错误目标仅凭 revision 相同被判通过"确实存在并可复现。
- **修复后**：两种错误目标均返回 `mismatch`（走既有 Finding/outbox 处置），绝不 `verified`。

## 5. 最小修复与合法旧行为兼容

修复只收窄"什么算可用证据 / 什么算一致"，不新增状态：

1. `_receipt_expected_revision`：receipt 非对象，或 `backend_revision` 非 `str`、
   为空、超 128 字符、或全空白 → 视为无可用证据（`None`）→ `no_receipt`，
   **在访问后端前止步**。不再 `str()` 归一（布尔/数字/数组/对象不会被"修正"）。
2. `_readback_conforms`：`snapshot` 的 `target`/`revision` 必须是 `str`，且 `revision`
   ≤128 字符；否则该读回不可信 → `unreachable`（fail-closed），不崩溃、不泄漏原值。
3. 目标一致：仅当 `snapshot.target == deployment.target` **且**
   `receipt.target`（缺省即兼容）与部署目标不冲突 **且** `revision` 逐字相等 → `verified`。
4. `verification` 列非对象时不 `dict()` 崩溃，也不回显原文；确为对象时保留其既有键。

兼容性：
- 既有 8 个用例（`verified`/`mismatch`/`unreachable`/`no_receipt`、Finding 幂等、
  跨租户 404、无权限 403、非 openshell-cli 409、audit 错误脱敏）原样通过。
- 旧回执合法地**不带** `target` 时保持兼容（`test_receipt_target_matching_deployment_still_verified`
  及既有 `verified` 用例覆盖）。
- 合法历史类型（`str` revision）不受影响；所有现存生产者均产出 `str`，
  无已被接受的历史非 `str` 形态（已用 `rg` 核对其全部产出点）。
- 未 trim 归一：`"7"` 与 `" 7 "` 仍是两个不同标识，不相等。`strip()` 仅用于判断
  "全空白 = 无证据"，返回比较用的仍是**原样**字符串。

## 6. 审计 / 事务 / 状态 / 脱敏的保留

- **不自行 commit**：`verify_deployment_receipt` 仍由调用方（`policies.py` 端点）提交。
- **状态不动**：不改 `deployment.status`；`verified` 不会把 failed/sent/pending
  改成 effective。
- **Finding 幂等不变**：`_record_mismatch` 仍按 `rule_id + resource_ref + open`
  upsert，未改并发去重机制、未加数据库约束；outbox 事件
  `policy.deployment.receipt_mismatch.v1` 的 payload 键集合不变
  （`deployment_id / expected_revision / actual_revision`）。
- **审计同事务**：attestation、Finding、outbox、审计仍在同一事务；审计失败整体
  回滚（`test_audit_failure_leaves_no_attestation` 断言不留孤立"验证通过"）。
- **脱敏与长度**：错误只落 `error_reference`（class 名 + sha256 摘要，不落原文）；
  写入 attestation/审计的 revision 受 128 字符上限约束；不变目标值不写入任何 sink。
  非 `AdapterError` 异常不被吞掉伪装正常（仍向上抛出，不提交）。
- **鉴权语义不动**：先对象定位 404、后权限 403 的顺序由路由保持（既有用例通过）；
  本模块内部检查不被描述为可替代路由鉴权；`tenant_id` 仍来自已验证调用链。

## 7. 精确验证命令与结果

工作目录 `apps/control-api`。

```
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_deployment_verify.py \
  app/tests/test_deployment_verify_boundaries.py --tb=short
# 36 passed

uv run --no-sync pytest -o addopts='' -q app/tests/test_change_execution.py --tb=short
# 8 passed（唯一其他消费者：只读投影，attestation 形状未变）

uv run --no-sync ruff check app/deployment_verify.py \
  app/tests/test_deployment_verify_boundaries.py
# All checks passed!

git -C /home/maoyd/siq/siq-agent-security diff --check -- apps/control-api/app/deployment_verify.py
# 退出码 0
grep -nP '[ \t]+$' apps/control-api/app/tests/test_deployment_verify_boundaries.py
# 无输出（无尾随空白）
```

- 修复前对照：对 HEAD 版 `deployment_verify.py` 单跑边界文件 → 22 failed / 6 passed。
- 未运行：前端构建、浏览器、Go 全量、后端全量（按任务要求不跑）；未联网同步、
  未安装依赖；未连接真实 OpenShell/网关/生产库，未执行真实部署/发布/权限变更。

## 8. 范围外问题（只记录，未改动）

- `app/drift.py:61` 使用 `(dep.receipt or {}).get("backend_revision")`：若 `receipt`
  是真理值非对象会抛 `AttributeError`，与本次修复前同源。**未修改**（不在允许清单内）。
- 既有四态枚举无法区分"revision 不一致"与"目标不一致"：本次将错目标映射为既有
  `mismatch`（触发 Finding 处置，不新增状态）。若需独立表达"目标不一致"，需要新增
  结果枚举/字段，属公共合同变更，**未擅自扩展**，留待主开发者决定。
- 结构违约读回（非 `PolicySnapshot`/非 `str` 字段）本次映射为既有 `unreachable`
  （"无法取得可信独立读回"，fail-closed、无 Finding、不改状态）。是否单列更精确
  状态同属合同问题，未擅自新增。
- `docs/agent-security-round4-20260820.md` §3 建议在 `test_e2e_fresh_deploy.py`
  补一条"创建部署 → receipt-verify"断言：属扩展测试范围，**未做**。

## 9. 交付状态

- 未提交、未推送、未建分支/PR、未签发/发布、未部署、未重启服务。
- 工作树其他未提交/未跟踪成果未触碰。
- 本记录只声明本子任务（回执验证器边界收口）完成；不宣称 CL-05、完整独立效果
  证明或整体项目完成。待主开发者复核。

## 10. 主开发者验收修复（2026-09-26）

对 DeepSeek 交付追加 8 个负例后，实际得到 **8 failed / 28 passed**，确认仍有：

- 回执显式 `target=[]/null/空串` 被当作合法旧回执缺省处理，继续构造后端；修复为不可用证据，`no_receipt` 且零后端构造。只保留真正缺省 target 的旧回执兼容。
- 独立读回 revision 为空/全空白，或 target 为空/超 128 字符，仍被当作可信 mismatch 并生成 Finding；修复为 `unreachable`，不记录该异常读回的 revision，不产生伪造漂移风险。
- 回执目标冲突的 Finding impact 复制了部署 target 原文，与原交付脱敏声明不符；已改为固定描述，通过 deployment 资源 ID 关联，不重复复制目标。

同时将注入后端选择改为明确 `is not None`，避免 falsey 测试/适配器对象触发默认后端构造。未改路由、适配器、共享审计、models、schemas 或其他开发线文件。

原审计失败测试仅覆盖 verified 路径。本轮参数化补 mismatch，核对 Finding、AuditEvent、OutboxEvent 行数与验证列在审计失败后均回滚。原 8 个 verifier 测试不修改。

实际执行：

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run --no-sync pytest -o addopts='' -q app/tests/test_deployment_verify.py app/tests/test_deployment_verify_boundaries.py app/tests/test_change_execution.py --tb=short
uv run --no-sync ruff check app/deployment_verify.py app/tests/test_deployment_verify_boundaries.py
```

结果 **53 passed**（原验证器 8 + 边界 37 + 只读消费者 8），仅既有 Starlette/httpx 弃用提示；Ruff、git diff --check 和新增文件尾随空白检查通过。未跑无关全量、未联网或连接真实执行后端。

验收结论：本子任务经修复后定向验收通过。错误目标用模拟适配器复现，当前 CLI 仍回显请求 target，不能据此宣称已在生产复现高危攻击；也不证明目标归属或行为阻断。CL-05 不关闭。未提交、未推送、未部署。
