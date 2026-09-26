# 企业绑定证据就绪度 v1（内部只读检查）

> 初始交付版本保留。验收后的当前内部实现使用
> [v2 增量合同](enterprise-binding-evidence-readiness.v2.md)，包含声明校验和框架配对修正。

本层为 **S4（绑定失效联动与共享影响确认收口）的前置证据层**，不是 S4 本身，也不关闭 S4/CL-04。
它把“一个已登记运行时绑定在**现有已验证持久记录**下能核对什么、不能核对什么”固化为一份有限的内部判定，
供后续独立评审后由既有入口调用。

## 0. 边界（先读）

- **不是 HTTP 接口**：本版不新增路由、字段、权限、审批、审计或执行能力。实现为内部模块
  `apps/control-api/app/binding_evidence_readiness.py`。
- **不是授权令牌**：`execution_confirmation_supported` 恒为 `false`；本层不返回任何可执行开关，
  也不给出“总体通过/不通过”结论。任一维度为 `verified_from_records` **不得**被解释为运行占用、
  角色归属、生效权限或审批通过。
- **只读**：仅租户限定的 `SELECT`。不写库、不产生审计/outbox/任务、不发起外部网络探测、不扫描。
- **不改变既有语义**：`registered_binding_only`、`shared_runtime_occupants=unknown`、
  `skill_isolation=not_established`、`execution_confirmation_supported=false` 四个既有边界保持原样；
  执行前的独立复验（`execute_deployment` 的 `require_binding_identity_unchanged`）**必须保留**，
  不被本层替代或弱化。
- **不新增判据**：不新造签名验证、绑定判定、来源判定或名称匹配器；不新造独占性标准。
  复用：`app/binding_identity.py`（绑定一致性）、`app/framework_source_view.py`（来源与设备）、
  `app/discovery_identity.py`（可信设备证据谓词）、`app/role_skill_roots.py`（目录候选校验）。
- **不设证据有效期**：当前没有任何已定期限合同。本层不引入 TTL、不设 24 小时等默认值；
  未确认即保持未确认（见 §6）。

## 1. 输入与输出

输入（内部调用）：`assess_binding_evidence(session, identity, binding_id)`。

- `tenant_id` 只取自 `identity.tenant_id`（服务端验证身份派生）；不接受调用方的租户覆盖参数。
  取不到验证租户时抛 `ValueError("verified_tenant_identity_required")`，不做任何查询。
- 所有持久查询显式限定 `tenant_id`。绑定不存在与绑定属于其它租户返回**完全相同**的结果
  （不构成跨租户存在性判别），也不把调用方传入的 `binding_id` 当作已存在的对象。
- 输出为固定结构的普通 dict（JSON 可序列化）：

```json
{
  "schema_version": "enterprise-binding-evidence-readiness/v1",
  "binding_id": "rb_...",
  "dimensions": {
    "registered_identity": {"state": "...", "reasons": [], "references": {}, "must_not_infer": []},
    "device_origin":       {"state": "...", "reasons": [], "references": {}, "must_not_infer": []},
    "role_skill_version":  {"state": "...", "reasons": [], "references": {}, "must_not_infer": []},
    "execution_identity":  {"state": "...", "reasons": [], "references": {}, "must_not_infer": []},
    "shared_impact":       {"state": "...", "reasons": [], "references": {}, "must_not_infer": []}
  },
  "coverage": "registered_binding_only",
  "shared_runtime_occupants": "unknown",
  "skill_isolation": "not_established",
  "execution_confirmation_supported": false
}
```

`dimensions` 恒有且仅有上述五个键；每个维度恰有 `state`、`reasons`、`references`、`must_not_infer`
四个键，`state` 必在 §2 词表内，`reasons` 中每一项必在 §4 原因码内，`must_not_infer` 每项必在该维度
固定的不得推导码内（§3）。`references` 内的子键随维度状态分支变化（见 §3）；**空 `references`
不代表“无记录”**，须先读 `state` 与 `reasons`。

## 2. 状态词表（固定五值）

| state | 含义 |
| --- | --- |
| `verified_from_records` | 现有已验证持久记录足以核对该维度要求的事实，且记录自洽。**不包含“运行时已生效”的含义。** |
| `evidence_missing` | 该事实**没有**记录（空集合不等于否定：见 `must_not_infer`）。 |
| `records_inconsistent` | 有记录，但记录之间或与当前持久状态矛盾/已失效（吊销、身份漂移、悬挂引用、跨租户、跨设备归属冲突）。 |
| `source_unavailable` | 声明或链接存在，但来源无法核对（设备未验证/已吊销、来源不可核对、attestation 无法独立核验）。 |
| `capability_not_established` | 该类证据在当前系统**没有采集或存储来源**，属能力尚未建立；不是“缺失一条记录”。 |

各维度**独立**：一个维度可核对不使其它维度变为可核对；“全部现有记录自洽”≠“所有必需证据齐全”。
本层不给总体结论。各维度实际使用的状态见 §3（`role_skill_version` 与 `execution_identity`
不使用 `source_unavailable`）。

## 3. 逐维度证据清单

下表逐项给出：所需事实 / 现有权威来源 / 当前能否取得 / 不能取得的原因（固定原因码）/ 可对外展示的
安全引用 / 不能推导的结论。

### A. 登记身份 `registered_identity`

| 项 | 内容 |
| --- | --- |
| 所需事实 | 绑定、环境、资产、实例同租户且关联一致；绑定状态为 `active`。 |
| 现有权威来源 | `runtime_binding`（`status`/`environment_id`/`asset_id`/`agent_instance_id`/`backend`/`backend_target_id`）+ 既有复验函数 `app/binding_identity.py`：`snapshot_binding_identity` + `require_binding_identity_unchanged`（列级重读绕过 ORM identity map，并用持久值重跑 `AgentInstance ⨝ AgentAsset` 来源核对）。 |
| 当前能否取得 | 能。复用既有函数，不复制第二套判定；本层不自行比较字段。 |
| 状态与原因 | 无该租户绑定 → `evidence_missing` / `binding_not_registered_in_tenant`；复验抛 409 `binding_revoked` → `records_inconsistent` / `binding_status_not_active`；复验抛 409 `binding_source_identity_changed`（含悬挂/跨租户/字段漂移/行被删）→ `records_inconsistent` / `registered_identity_changed`。 |
| 安全标识引用 | 可核对时：`binding_id`、`environment_id`、`asset_id`、`agent_instance_id`、`backend_target_id`（均为本租户标识）。不可核对时只回 `binding_id`（**不展示可能已漂移的旧值**）。 |
| 不能推导的结论 | `active_registration_is_not_runtime_attestation`、`attestation_is_not_independent_verification`。`active` 是登记状态，不是运行证明；`attestation` 是租户提交的登记佐证，不是服务端认证事实。 |

### B. 设备与观察来源 `device_origin`

| 项 | 内容 |
| --- | --- |
| 所需事实 | 能否从已有、经过验证的持久记录核对设备来源；该设备是否属于本租户当前环境且未被吊销。 |
| 现有权威来源 | 复用 `app/framework_source_view.py::project_framework_sources`：它按 `asset.discovery_scope` 关联 `edge_agent`+`environment`（限本租户）、要求 `framework_source.evidence_id` 在 `asset.evidence_ids` 内、并要求**唯一**匹配的 `evidence` 六元组。设备证据计数复用 `app/discovery_identity.py::asset_evidence_device_filter`。 |
| 当前能否取得 | **部分能**：只能核对**资产**这一层（资产 → 设备 → 环境 → 同设备证据）。绑定与实例没有设备字段。 |
| 状态与原因 | `no_recorded_source` → `evidence_missing` / `no_recorded_framework_source`；`source_unavailable`（含悬挂引用与其它租户设备；本层不做跨租户读取，统一按不可核对处理）→ `source_unavailable` / `framework_source_unverifiable`；设备已吊销 → `source_unavailable` / `device_revoked`；设备环境与绑定环境不一致 → `source_unavailable` / `device_environment_outside_binding_environment`；以上皆否 → `verified_from_records`（`reasons` 为空）。 |
| 安全标识引用 | `framework_source_status`、`asset_device_id`、`device_environment_id`、`device_revoked`、`device_scoped_evidence_count`（仅统计 `asset.evidence_ids` ∩ 该设备可信谓词）。不返回 `device_identity` 原文、路径、证据正文或其它租户对象。 |
| 不能推导的结论 | `asset_device_link_is_not_binding_device_origin`（绑定/实例无设备字段，设备归属不得由资产反推）、`same_name_on_two_devices_must_not_merge`、`device_link_does_not_prove_runtime_occupancy`、`no_device_evidence_must_not_select_any_device`（**没有设备证据不得从环境中“任选一台”**）。 |

### C. 角色与 Skill 版本 `role_skill_version`

四个**独立子事实**，位于 `references.subfacts`；每个子事实为 `{"state", "reason", ...}`：

| 子事实键 | 现有权威来源 | 状态判定 | 安全标识引用 | 不能推导 |
| --- | --- | --- | --- | --- |
| `directory_candidate` | `agent_asset.attributes.skill_source_roots`（`enterprise-role-skill-roots/v2`），校验复用 `app/role_skill_roots.py::parse_role_skill_roots`（不读原始配置正文、Skill 内容或真实用户目录） | 无记录 → `evidence_missing`/`no_layout_candidate_recorded`；非法 → `records_inconsistent`/`layout_candidate_invalid`；合法 → `verified_from_records` | `roots_basis`、`roots_status`、`root_count` | `layout_candidate_is_not_installation_or_load`：布局候选不是显式配置 allowlist、不是加载根集合、不证明目录存在/安装/加载。 |
| `declared_selection` | `role_skill_selection_observation`（`tenant_id`+`asset_id`+`edge_agent_id`，签名批次入库的 OpenClaw 声明） | 设备未知 → `evidence_missing`/`asset_device_scope_absent`；存在**其它设备**的同资产声明 → `records_inconsistent`/`declaration_device_mismatch`（**不得合并归属**）；本设备无声明 → `evidence_missing`/`no_recorded_declaration`；有 → `verified_from_records` | `declaration_count`、`latest_observed_at`、`task_id`、`batch_digest`、`declaration_status`、`declaration_source`、`declaration_name_count` | `declared_names_are_not_installation_identity`、`same_name_is_not_same_installation`、`unconfigured_or_unsupported_is_not_zero_skills`、`empty_declared_scope_is_not_no_installation`。**不返回声明名称列表**，避免以同名代替精确安装归属。 |
| `installation_observation` | `skill_installation`（`tenant_id`+`edge_agent_id`+`locator_sha256`）+ `skill_manifest_observation`（`manifest_sha256`/`parse_status`/`parser_version`/`observed_at`） | 设备未知 → `evidence_missing`/`asset_device_scope_absent`；本设备无观察 → `evidence_missing`/`no_installation_observation`；有 → `verified_from_records` | `installation_count`、`observed_installation_count`、`latest_observation.{installation_id, manifest_sha256, parse_status, parser_version, observed_at}` | `manifest_sha256_is_not_package_version`（只标识完整 `SKILL.md`，不是整个技能包版本）、`installation_observation_is_not_runtime_load`、`no_installation_observation_is_not_no_installation`、`same_name_on_two_devices_must_not_merge`。**不返回名称、工具列表或 `locator_sha256`。** |
| `runtime_load` | **无来源** | 恒为 `capability_not_established` / `runtime_load_source_absent` | 无 | `no_load_record_is_not_no_skill`。当前没有任何模型记录“运行时实际加载了哪个 Skill/角色”。 |

维度状态规则（`runtime_load` 不参与）：任一子事实 `records_inconsistent` → `records_inconsistent`；
否则任一子事实 `evidence_missing` → `evidence_missing`；否则 → `capability_not_established`。
`reasons` = 所有未达 `verified_from_records` 的子事实原因码（即就绪度不足的全部原因）。
`must_not_infer`（维度级）= 上表四行的全部不得推导码；但**任一子事实可核对都不使本维度变为可核对**。

### D. 执行身份与沙箱 `execution_identity`

子事实位于 `references.subfacts`：

| 子事实键 | 现有权威来源 | 状态判定 | 安全标识引用 | 不能推导 |
| --- | --- | --- | --- | --- |
| `revision_history` | `deployment`（`tenant_id`+`runtime_binding_id`） | 无记录 → `evidence_missing`/`no_deployment_history_recorded`；有 → `verified_from_records` | `count`、`latest_to_revision`、`latest_status`、`latest_created_at`、`has_receipt`、`has_verification`（**只读存在性标志，不载入回执/验证正文**） | `historical_deployment_record_is_not_current_runtime_state`、`historical_revision_is_not_current_revision`。 |
| `current_revision_readback` | **无（需真实探测）** | 恒为 `capability_not_established` / `current_readback_requires_live_probe` | 无 | `current_revision_requires_live_readback`：当前 revision 需经适配器实时读回；**不得**用历史记录替代当前状态，本层不发起探测。 |
| `target_authority` | `app/target_authority.py`（operator 文档，需实时握手得到的 `endpoint_fingerprint`/`gateway_name_sha256`） | 恒为 `capability_not_established` / `target_authority_requires_live_connection_identity` | 无 | `authority_assignment_is_not_role_attribution`：授权证明允许操作某目标，**不等于**该目标属于某角色；本层不读授权文件、不新增文件读取面。 |
| `operator_attestation` | `runtime_binding.attestation`（租户提交 JSON） | 存在 → `source_unavailable`/`attestation_not_independently_verified`；不存在 → `evidence_missing`/`no_attestation_recorded` | 仅 `present`（布尔，**不返回正文、键名或摘要**） | `attestation_is_not_independent_verification`：人工 attestation 不能升格为独立核验。 |

维度状态规则：`revision_history` 与 `operator_attestation` 任一为 `evidence_missing` → `evidence_missing`；
否则 → `capability_not_established`（本维度不使用 `source_unavailable`、`records_inconsistent`）。
`reasons` = 所有未达 `verified_from_records` 的子事实原因码。
维度级不得推导另含 `sandbox_permission_fact_is_not_binding_identity`：`permission_fact` 的
`authority_revision` 来自另一条实时读回链路，未与绑定身份关联，不构成本绑定的沙箱 revision 证据。

### E. 共享影响与覆盖完整性 `shared_impact`

| 项 | 内容 |
| --- | --- |
| 所需事实 | 目标是否被多个对象共享；本绑定是否独占沙箱；完整影响覆盖是否已确认。 |
| 现有权威来源 | **无**独立运行时占用来源。唯一相关持久事实是 `runtime_binding` 的登记唯一约束 `uq_runtime_binding_target (tenant_id, backend, backend_target_id)` 与同主体（`agent_instance_id`）的其它登记。 |
| 当前能否取得 | **不能**。本维度恒为 `capability_not_established`。 |
| 不能取得的原因 | `runtime_occupancy_source_absent`（无运行时占用来源）、`target_registration_is_unique_per_tenant_backend_target`（同租户同后端同目标**结构上只能有一条登记**，因此“查不到第二条绑定”恒真，不构成独占证据）、`subject_may_hold_multiple_target_registrations`（同一实例可登记到多个不同目标）。 |
| 安全标识引用 | `registered_active_targets_for_subject`：本租户内同一 `agent_instance_id` 的 `active` 绑定数量（登记层事实，**不是**运行占用证据）。 |
| 不能推导的结论 | `single_registration_is_not_exclusive_occupancy`、`registered_binding_only_is_not_full_coverage`、`shared_runtime_occupants_remains_unknown`、`skill_isolation_remains_not_established`、`user_confirmation_is_not_evidence`。查询到一条 `RuntimeBinding` 不能证明沙箱独占；完整影响确认不能由用户勾选替代证据。**无独立运行时占用来源时保持 `unknown`。** |

### 登记来源不可用时的降级

`registered_identity` 不是 `verified_from_records`（绑定缺失/已吊销/身份漂移）或该资产无法在本租户解析时，
其余四个维度统一为 `evidence_missing` / `registered_subject_unavailable`，`references` 为空、
`must_not_infer` 保持各自固定集合。**此时空 `references` 的原因是登记不可用，不是“这些维度无记录”。**

## 4. 固定原因码

`reasons` 与子事实 `reason` 只允许取以下有限集合（实现常量 `REASON_CODES` 与本节逐项一致）：

```
binding_not_registered_in_tenant
binding_status_not_active
registered_identity_changed
registered_subject_unavailable
no_recorded_framework_source
framework_source_unverifiable
device_revoked
device_environment_outside_binding_environment
asset_device_scope_absent
no_layout_candidate_recorded
layout_candidate_invalid
no_recorded_declaration
declaration_device_mismatch
no_installation_observation
runtime_load_source_absent
no_deployment_history_recorded
current_readback_requires_live_probe
target_authority_requires_live_connection_identity
no_attestation_recorded
attestation_not_independently_verified
runtime_occupancy_source_absent
target_registration_is_unique_per_tenant_backend_target
subject_may_hold_multiple_target_registrations
```

`must_not_infer` 只允许 §3 各维度列出的固定码。**不新增状态、原因码或不得推导码而不升级本合同。**

## 5. 安全输出约束

- 不返回 attestation 正文、签名、密钥、设备种子、来源路径、原始配置正文、Skill 内容或任何
  `locator_sha256`/文件路径原文。
- 不返回其它租户的任何对象；不因对象存在与否而改变响应结构。
- 名称、`manifest_sha256`、`batch_digest` 等只以“数量/摘要/状态”形式出现，且**不得**被用来自行
  推导安装归属或版本等义（见各维度 `must_not_infer`）。
- 输出不含任何可执行开关；`execution_confirmation_supported` 恒为 `false`。

## 6. 未定事项与不回退

- **证据有效期未定**：仓库内没有任何“绑定/来源证据有效期”合同。本版**不**引入 TTL，也不把
  “未确认”改写为某个默认窗口（例如 24 小时）。若后续需要有效期，须先有独立合同与业务决策。
- **共享沙箱独占性判定标准需业务确认**，不由模型或本层设定（S4 既有用户决策点）。
- **无回退**：证据不可核对的维度返回不可用/未建立，不回退为“最新属性”“同名匹配”或
  “环境内任选设备”；`unknown` 保持 `unknown`。

## 7. 后续前置、消费与所有权

以下维度当前**没有**来源，需要新的采集/存储合同与迁移才能推进；本版只登记前置，不实现：

1. 运行时实际加载（Skill/角色）→ 需要独立加载观察来源。
2. 目标/沙箱的运行时占用与独占 → 需要独立运行时占用来源与业务判定的共享标准。
3. 沙箱 revision 进入绑定身份 → 属 S4 拥有者文件（`binding_identity.py`/`models.py`+迁移/`bindings.py`）
   的范围，本版不改这些文件。
4. 绑定/实例的设备绑定 → 现无设备字段，需要新的登记字段与合同。
5. 人工 attestation 的独立核验 → 需要服务端可独立核验的来源。

- 生产者：`apps/control-api/app/binding_evidence_readiness.py`（内部模块，本版无可执行接入点）。
- 未来接入点建议：既有只读影响预检 `POST /api/v1/deployment-preview/impact` 的调用链
  （`app/routers/deployment_impact.py`），在其已验收的身份复验之后、报告生成之前作为**附加内部检查**读取；
  是否投影到 wire、以何种 schema 暴露，需独立评审与合同升级，本版不预设。
- 接入前仍需：上述 1–5 的前置、wire 层 schema 决策、以及“不得据本结果开放执行按钮”的评审。
  因此本版**不开放执行**、不改变任何权限或审批。
