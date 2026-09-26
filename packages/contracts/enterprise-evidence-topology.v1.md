# 证据拓扑（视角与来源边界）v1

R03 增量。对应 ENT-006、010、012。与 [enterprise-binding-evidence-readiness/v2](enterprise-binding-evidence-readiness.v2.md) 同族：**内部只读投影，不是 HTTP 接口，不是执行授权**。本版本不新增端点、不新增迁移、不改任何既有响应。

## 解决的问题

仓库已有主机识别（`edge/agent/host_inspection*.go`、合同 `enterprise-host-inspection.v1`）与各采集器，但没有任何投影回答"这个环境里能看到**哪个视角**的**哪个来源**的证据"，也没有为看不到的情况给出固定原因。历史风险：把名称级主机信息（DMI `product_name`、device-tree `model`）当作型号识别；把"采集器存在"当作"该表面已被完整覆盖"。

## 只读边界

`app/evidence_topology.py::project_evidence_topology(session, identity, environment_id)`。只做租户限定的 `SELECT`；不写库、不产生审计/outbox/任务、**不发起任何探测**、**不读 Docker socket**、**不扫描整机**、**不载入证据 payload 正文**（只判断 `payload_ref` 是否存在）。`tenant_id` 只取自服务端验证身份；环境缺失或属于其它租户返回与"不存在"完全相同的结果，不构成跨租户存在性判别。

## 刻意不合并的两件事实

| 事实 | 来源 | 含义 |
| --- | --- | --- |
| **声明视角** | `Environment.env_type`（`host`/`container`/`k8s`/`account`） | 管理员声明该环境是什么；**不是**观测结果 |
| **观测表面** | 该环境内已有 `Evidence.source_type` 归入的表面桶 | 实际有哪些采集器产出过证据；**不证明覆盖完整** |

两者不一致时报告 `declared_and_observed_conflict`，**不静默取其一、不做"最可能"推断、不因同时存在相容表面而降级为一致**。

## 固定映射

采集器 → 观测表面，**未列出的采集器不猜测归属**：

- `process`、`systemd`、`directory` → `os`（宿主表面）
- `docker`、`kubernetes` → `container`（容器表面）
- `hermes`、`openclaw`、`piagent`、`workbuddy`、`dify`、`mcp`、`siq` → `agent_config`（智能体框架/配置类，**既不是宿主也不是容器表面**，单列不塞进三视角）
- 其余 → `unmapped`，报 `connector_perspective_unmapped`，**不计入任何表面桶**

声明视角 → 相容表面：`host` → `os`；`container`/`k8s` → `container`。`account`（云账号）是**远程**视角，仓库内没有任何采集器产生远程表面证据，因此恒为 `source_absent` 并报 `account_perspective_source_absent`——**不借用宿主/容器表面顶替**。

## 状态词表（固定五值，无"部分通过"）

| 值 | 含义 |
| --- | --- |
| `observed_from_records` | 存在与声明视角相容的表面证据，且无未归类采集器 |
| `declared_only` | 环境内无任何证据（有声明、无观测） |
| `declared_and_observed_conflict` | 观测到了东西，但没有一个属于声明视角的相容表面，或同时观测到冲突表面 |
| `connector_perspective_unmapped` | 保留值，作为原因码出现 |
| `source_absent` | 环境不可定位（含他租户），除回显请求参数外与"不存在"完全相同 |

`observed_from_records` 若同时带 `connector_perspective_unmapped` 等边界原因码，表示**结论成立但边界未闭合**，原因码必须一并展示，不得只显示状态。

## 不可读原因（记录事实，不是推断）

对租户+环境范围内的证据行统计两类**已记录**事实，绝不解引用 payload：

- `payload_not_retained`：该证据未保留 payload（`payload_ref` 为空），**只有元数据可读**。
- `evidence_expired`：`expires_at` 早于服务端当前时间。

多值为聚合计数（`total`/`metadata_only`/`expired`），不返回 evidence_id 列表，避免扩大读取面。**"元数据可读"不等于"内容可读"**。

## 行为证据：本模块不生产

`enforcement_verified` 恒为 `false`；`behavioral_evidence` 恒为 `{state: not_established, reason: behavioral_fixture_source_absent}`。仓储内 `enforcement_verified`（见 [openshell-policy-safety/v2](openshell-policy-safety.v2.md)、`app/routers/change_execution.py:77`、`app/adapters/openshell/contracts.py:11`）是**刻意保留值，尚无生产者**，需要真实行为 fixture 证据才可升格。本轮 R03 **不制造**该事实：本投影不改变该保留状态，也不提供任何升级路径。

## 不得由此投影推导（固定码，不随输入变化）

`host_name_is_not_model_identification`、`dmi_product_name_is_not_device_model`、`devicetree_model_is_not_device_model`、`declared_environment_type_is_not_observed_perspective`、`connector_presence_is_not_coverage_of_that_surface`、`readable_metadata_is_not_readable_content`、`recorded_evidence_is_not_current_runtime_state`、`topology_projection_is_not_enforcement_proof`。

## 实现与状态

`app/evidence_topology.py`；隔离验证 `app/tests/test_evidence_topology.py`（10 用例：只读与租户隔离、相容表面、仅有声明、容器表面落在宿主环境的冲突、未归类采集器不静默归桶、云账号远程视角无来源、未知 env_type 不猜、可读性原因、行为证据不生产、验证身份必填）。

**源码级 + 隔离验证级**（合成租户/环境/证据行，独立 SQLite）。**不证明**真实 DGX/容器/OpenShell 目标的证据拓扑已被核对，也不证明任何视角的覆盖完整。真实目标归 R09 资源门槛。
