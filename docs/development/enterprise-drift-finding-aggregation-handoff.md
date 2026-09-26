# 同一部署漂移风险聚合与展示一致性修复交接（CL-05-DRIFT-FINDING-AGGREGATION）

日期：2026-09-26
状态：子任务完成（**未提交、未推送、未部署，待主开发者复核**）
范围：`apps/control-api/app/drift.py` 的 `upsert_drift_findings`（落库聚合语义）。
本轮**未改**检测规则、未改 `check_policy_drift` 及其证据辅助函数、未改 `DriftResult`、未改端点、未新增表/字段/枚举/公共状态/前端页面。
本轮仅声明 `CL-05-DRIFT-FINDING-AGGREGATION` 子任务完成；**不宣称 CL-05、完整漂移治理或整个项目完成**。

---

## 1. 实际修改 / 新增文件

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `apps/control-api/app/drift.py` | 修改 | 相对本轮前的文件 +71 / −11（相对 HEAD 累计 +292 / −44）。只改 `upsert_drift_findings`(:322) 并新增其私有辅助函数 `_severity_rank`(:297)、`_representative_result`(:302)、`_representative_sort_key`(:312)，以及常量 `_SEVERITY_RANK`(:71)；`import json`(:40) 仅用于稳定序列化代表项 |
| `apps/control-api/app/tests/test_drift_finding_aggregation.py` | 新增 | 664 行，14 个测试函数 / 16 个用例；复用真实 `check_policy_drift`、真实 `upsert_drift_findings` 与真实 check-drift 端点，写真实 SQLite（`session_scope`） |
| `docs/development/enterprise-drift-finding-aggregation-handoff.md` | 新增 | 本文件 |

未修改任何其他文件：`check_policy_drift`、上轮已验收的证据核对辅助函数、`test_drift_evidence_boundaries.py`、`deployment_verify.py`、`policies.py`、`binding_identity.py`、`models.py`、`schemas.py`、迁移、共享审计、适配器、前端、Edge、Connector、安装器、依赖与锁文件、公共台账均只读。
工作树中其他开发线（GLM 部署测试隔离、Qwen 前端审计、主开发者 Edge 主线）的文件未被触碰；`git status` 中的既有改动与未跟踪文件保持原状。

**修复前的问题就是 HEAD 里的代码**：`git show HEAD:apps/control-api/app/drift.py` 中 `upsert_drift_findings`(:109) 的函数体与本轮基线逐字节相同——上两轮证据收口未触碰该函数，因此本次修复的是已提交状态下的既有缺陷，不是本轮新引入。

---

## 2. 修复前复现（真实函数 + 隔离 SQLite）

复现方法（可逆、未清理或还原工作树）：把本轮前的 `upsert_drift_findings` 函数体（取自本轮前的文件副本）单独替换进当前 `drift.py`，**其余代码保持当前版本不变**，跑同一份新测试文件，跑完立即还原并用 `cmp` 校验与原文件逐字节一致（已验证 `restore identical`）。这样基线只体现落库聚合差异，不掺入上轮证据逻辑差异。这是合成 SQLite 上的函数级复现，**不是生产攻击或并发保证**。

| # | 假设 | 修复前实测 | 影响 |
| --- | --- | --- | --- |
| 1 | 结果顺序影响最终级别 | 同部署本轮产出 `revision_mismatch`(high) 与 `undeclared_rules`(medium)：high 在前时最终 `Finding.severity == 'medium'`（断言 `'medium' == 'high'` 失败） | 后一条 medium 结果把 high 压成 medium → 后台按级别筛选/排序的消费方漏看真实高风险 |
| 2 | 更新既有 Finding 不同步摘要 | medium 在前、high 在后时级别正确为 `high`、`risk_acceptance.kind == 'revision_mismatch'`，但 `impact` 仍是创建时写入的 `后端存在未登记的额外网络规则: ['extra.example.com:443']`（断言 `impact == high.summary` 失败） | 同一 Finding 的摘要讲"额外规则"、详情讲"revision 漂移" → 前端 `FindingExplorerItem` 同行展示级别与 `impact`，自相矛盾 |
| 3 | 计数按结果条数 | 同部署三条结果（unreadable + missing_rules + undeclared_rules）一次调用返回 `{'created': 1, 'updated': 2}`（期望 `{'created': 1, 'updated': 0}`）；两条部署各两条结果时 `created` 为 4 而非 2 | worker 累计计数与端点返回的 created/updated 被放大，运维据此判断"新增了多少风险"失真 |

根因（HEAD 版本函数体）：逐条结果循环，用 `rule_id + resource_ref + status == "open"` 查既有 Finding；命中时只写 `last_seen_at`、`severity`、`risk_acceptance` 并 `updated += 1`（**不写 `impact`**），未命中时创建并 `created += 1`。于是"后写覆盖"同时造成级别可被降、摘要与详情不同源、计数按结果条数。

修复前基线（新测试文件，仅替换 `upsert_drift_findings`）：**12 failed / 4 passed**。
失败项：`test_result_order_does_not_downgrade_severity[high-first|medium-first]`、`test_all_permutations_of_three_results_persist_identically`、`test_same_level_representative_is_stable[missing-first|revision-first]`、`test_lower_level_round_keeps_retained_evidence_and_level`、`test_higher_level_round_updates_all_three_from_one_result`、`test_out_of_band_higher_existing_level_is_not_overwritten`、`test_multi_result_deployment_counts_once`、`test_two_deployments_count_per_finding`、`test_other_tenant_same_resource_ref_is_not_touched`、`test_endpoint_reports_all_results_but_persists_one_representative`。
基线仍通过的 4 项是单结果或无结果路径（`unreadable_only` 建单条、空输入、不改写入参、审计失败回滚），与聚合语义无关，符合预期。

---

## 3. 聚合规则（分组 / 级别 / 代表项）

保留"每部署每轮只 upsert 一条 open Finding"的既有模型，全部改动都在函数内部：

1. **先按 `deployment_id` 分组**，每部署只查一次、只写一次，调用 `session.scalar(select(Finding)...)` 的键与租户限定（`tenant_id` + `rule_id="policy-drift"` + `resource_ref=f"deployment:{id}"` + `status="open"`）与原来完全一致，未跨租户比较同名 `resource_ref`。
2. **级别取本轮该部署的最高级别**：`_SEVERITY_RANK = {"info":0,"low":1,"medium":2,"high":3,"critical":4}`，与 `models.py` Finding.severity 注明的合法级别一一对应（`# critical|high|medium|low|info`）。使用映射比较，**不做字符串排序**（避免 `"high" < "medium"` 这类字典序陷阱），不新增枚举取值，未知取值 `_severity_rank() is None`，不参与级别比较也不写库。
3. **代表项**：`min(group, key=_representative_sort_key)`，排序键为
   `(级别未知者排后, -级别权重, str(details.get("kind") or ""), json.dumps(details, sort_keys=True, default=str))`。
   即：本轮最高级别者优先；同为最高级别时按 `kind` 升序（如 `missing_rules` < `revision_mismatch`）；仍相同则按细节的稳定序列定序。这是一个**全序**，因此同一组输入的任何排列都得到同一条代表项（测试用三条结果的 6 种排列、以及同级两种顺序各验证一次）。
4. **三件套同源**：代表项的 `severity` / `impact`(=summary) / `risk_acceptance`(=details) 整条写出，绝不把一种风险的摘要配上另一种风险的详情。创建路径三条同时写入；更新路径三条同时替换。
5. **代表项不声称包含全部证据**：函数只落一条 open Finding，本轮其余结果仍由端点响应 `drift_results` 原样返回（形状未变），并在审计链路可见。要持久化多条证据需要返回合同变化，不在本函数范围，本轮**未改接口**。
6. **不原地改写入参**：分组只读 `results`，代表项不被就地修改，也不重排 `results`；端点在同一次调用之后还要用 `results` 组装响应，测试对此有专门断言。

---

## 4. 更新既有 open Finding：同步与"历史 high 不自动降级"

更新分支（`drift.py:362-373`）先算 `incoming_rank`：

- `incoming_rank >= existing_rank`：`severity` / `impact` / `risk_acceptance` 三件套一起换成代表项，并刷新 `last_seen_at`；
- `incoming_rank < existing_rank`（或任一级别不是现有合法取值，即 `None`）：**只刷新 `last_seen_at`**，保留既有三件套不动；
- 两条分支都 `updated += 1`（同一部署本轮最多一次）；不自动关闭、不重新打开、不删除 Finding；`first_seen_at`、`id`、`rule_version`、`owner_user_id`、`due_at`、`evidence_ids`、`status` 等无关字段保持原值（测试断言创建/更新前后 ID 与首见时间不变）。

**保守路径的依据**：既有风险生命周期中没有任何合同允许"证据变轻即自动降级"。

- `rules.py::upsert_findings`（:200-255）对既有 open Finding **只**刷新 `last_seen_at`，从不改级别；
- `worker.py::reap_expired_risk_acceptance`（:80-123）只会把到期的 `risk_accepted` 重新置回 `open`，方向是"升级/重开"；
- `routers/findings.py` 的确认/解决/接受风险都是**用户驱动**，且没有降级入口；
- 因此本轮不自行发明降级合同，也不把"后一条 medium 的覆盖顺序"当作降级依据。

这样处理不会产生自相矛盾的摘要：保留的三件套本身同源（来自当时那次写库的同一代表项），级别不会被一条更轻的结果悄悄改小；本轮更轻的证据仍可由端点响应与审计链路查看。若主开发者认为需要"随证据变轻而自动降级"，那属于生命周期合同变更，本轮**先报告、未自行改接口**。

---

## 5. 计数、审计、事务与脱敏

- **计数**：`{"created": n, "updated": n}` 按本次**实际创建/更新的 Finding 数**计，同一部署本轮最多计一次（三条结果 → `{'created': 1, 'updated': 0}`，重复相同输入 → `{'created': 0, 'updated': 1}` 且不新增第二条 open Finding）。`worker.py::run_drift` 与 check-drift 端点继续累加/透传该字典，语义变为"按 Finding"，调用方代码无需改动。
- **审计**：沿用既有约定，只在**创建**时写 `finding.open`（actor `system`/`drift-check`）与事件 `policy.drift.detected.v1`（payload `{finding_id, deployment_id, kind}`，取代表项的 kind）；满足"复用既有 action、不发明公共事件合同"。**更新时不新增审计/事件**——这与 `rules.py` 的既有惯例一致（更新只刷新 `last_seen_at`，不产生新审计动作），避免凭空引入公共事件契约。创建审计的 `severity`/`kind` 现在取自代表项，与落库 Finding 一致。
- **事务**：函数**不 commit**；审计/事件与状态变化同事务，由调用方（端点 / worker）统一提交。审计失败时状态与 outbox 一起回滚，无孤立风险改动（测试注入审计异常后断言 Finding/AuditEvent/OutboxEvent 均无残留）。
- **脱敏**：未扩大敏感细节存储，未新增字段；`risk_acceptance` 仍沿用既有结构（漂移检测细节 `{kind, ...}` 与用户接受风险时的 `{reason, accepted_by, expires_at}` 共用该列，本轮未改这一既有约定）；写入内容仍全部来自本轮真实结果的现有摘要/细节，不包含设备种子、令牌或密码。
- **租户**：所有查询显式带 `tenant_id`；其他租户同名 `resource_ref` 的 Finding 不被读写（测试覆盖）。

---

## 6. 实际执行的验证命令与结果

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api

# 1) 新增测试文件（修复后）
uv run --no-sync pytest -o addopts='' -q app/tests/test_drift_finding_aggregation.py
# 结果：16 passed

# 2) 隔离基线（只把 upsert_drift_findings 换回 HEAD 版本，其余保持当前文件；跑完 cmp 校验还原一致）
# 结果：12 failed / 4 passed（失败项见 §2）

# 3) 上轮证据边界测试（未改动，跑一次确认无回归）
uv run --no-sync pytest -o addopts='' -q app/tests/test_drift_evidence_boundaries.py
# 结果：98 passed

# 4) 定向合并集（新文件 + 证据边界 + 既有 rules 漂移用例）
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_drift_finding_aggregation.py app/tests/test_drift_evidence_boundaries.py app/tests/test_rules.py \
  -k "drift or evidence"
# 结果：120 passed, 26 deselected

# 5) 主开发者上轮同款命令（不含新文件，用于对照是否回归）
uv run --no-sync pytest -o addopts='' -q app/tests/test_drift_evidence_boundaries.py app/tests/test_rules.py -k "drift or evidence"
# 结果：104 passed, 26 deselected —— 与轮 2 完全一致，无回归

# 6) 静态与格式
uv run --no-sync ruff check app/drift.py app/tests/test_drift_finding_aggregation.py   # All checks passed!
cd /home/maoyd/siq/siq-agent-security && git diff --check -- apps/control-api/app/drift.py   # 无输出
grep -nP "[ \t]+$" apps/control-api/app/tests/test_drift_finding_aggregation.py apps/control-api/app/drift.py  # 无匹配
```

未跑后端全量、未跑前端、未跑 Go、未连接真实数据库/控制面/OpenShell/设备，未安装依赖，未凑测试数量（14 个测试函数 / 16 个用例，均为本次问题的正/负例，含 4 项参数化）。

---

## 7. 未解决的边界与不做声明

- **只落一条代表项**：本轮多次检测证据（如同时存在 revision 漂移与额外网络规则）在持久化层只体现为一条 Finding（级别取最高者）。本条证据由端点响应的 `drift_results` 承载，Finding 本身不声称包含全部证据；要改成"一部署多证据"需要返回合同变化，本轮不做。
- **不声称解决并发重复创建**：删除/并发路径仍可能出现同部署两条 open Finding（例如用户把漂移 Finding 接受风险后，下一次巡检按 `status == "open"` 查不到它而新建一条；`worker.reap_expired_risk_acceptance` 到期再把原记录置回 open）。这些都是既有行为，本轮未新增进程内锁或数据库约束，也**不声称**已解决全部并发/多路径重复 Finding 问题。
- **不做自动降级**：历史 high 在后续轮次只出现 medium 时保持 high（§4）。若线上出现"高风险是误报、需要自动下调"的场景，需要生命周期合同明确授权，本轮未实现。
- **未验证真实环境**：未验证真实网关/Edge/Connector 实际产生的多结果组合分布，也未验证真实并发巡检下的行为；上述结论均为合成 SQLite 上的函数级与端点级（TestClient）证据。
- 未自动部署、未改权限、未加回滚或后台调度，未扩大敏感细节存储。

## 8. 交付状态

- 未提交、未推送、未创建分支/PR、未部署、未改任何治理或台账文件；其他开发线的文件未被触碰，工作树其他改动保持原状。
- **待主开发者复核点**：①"历史 high 不自动降级"的保守取舍是否认可（§4，若要求自动降级需先定合同）；②更新既有 Finding 时的三件套整体替换（会不会覆盖主开发者期望保留的上一轮细节）；③代表项定序规则（级别 → `kind` → 细节序列）是否需要调整；④新增测试文件与私有辅助函数的命名/位置。
- **仅完成本次漂移风险聚合与展示一致性收口，未提交、未部署，待主开发者复核；不代表 CL-05 或整体项目完成。**

## 9. 主开发者验收与修复（2026-09-26）

独立复核确认本轮聚合方向成立，但发现两个边界缺陷。新增最小负例后，原交付实现为
`3 failed, 16 deselected`；未回退或替换其他开发线源码。

- 同级、同 kind、同 details，但 summary 不同时，排序键相同，`min` 取首项，创建与更新的摘要仍受输入顺序影响。现追加摘要原文作为最后排序键；稳定性指持久化的三字段，不承诺相同内容对象的 Python 身份一致。
- 全为未知级别且没有既有 open Finding 时，原创建分支仍写入未知级别，与“不写库”声明矛盾。现于新建前抛固定 `ValueError("drift_finding_severity_unavailable")`，不猜测合法级别、不静默返回零风险；调用方事务回滚。用未知串和空串两个用例确认前序正常部署的 Finding、AuditEvent、OutboxEvent 同时回滚。这是内部异常输入防御；当前检测器生产者仍只产生已知级别，不新增公共错误响应合同。既有 Finding 的未知级别保留路径、混合组的已知优先路径未改。

验收取舍：保留不自动降级；允许同级/升级时三个字段整体替换；不扩展多证据存储、事件或并发锁。历史上已经错配的三字段不会因保守保留而自动修复，本轮不执行数据修复。

纠正前文证据口径：端点 `drift_results` 保留每条结果的 deployment_id、severity、kind、summary，**不含完整 details**；worker 不保存这份响应；更新也不新增审计事件。因此不可把“端点响应与审计链路”解释为全部历史证据已持久可追溯。本子项只保证代表项聚合一致性，不关闭完整审计收口项。

实际验证（隔离 SQLite + 模拟适配器）：

```bash
cd apps/control-api
uv run --no-sync pytest -o addopts='' -q app/tests/test_drift_finding_aggregation.py \
  app/tests/test_drift_evidence_boundaries.py app/tests/test_rules.py \
  -k 'drift or evidence' --tb=short
# 123 passed, 26 deselected；既有 Starlette/httpx 弃用警告 1 条
uv run --no-sync ruff check app/drift.py app/tests/test_drift_finding_aggregation.py
```

仅增补本交付涉及的 drift.py、聚合测试与此交接记录。未跑全量后端、前端、Go 或真实环境；未安装依赖、未提交、未推送、未部署。仅本次聚合子项经修复通过定向验收，不代表 CL-05 或整体项目完成。
