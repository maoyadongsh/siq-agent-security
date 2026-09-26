"""内部只读证据拓扑：某环境里"能看到什么视角的什么来源"，以及"看不到时为什么"。

R03 缺口：仓库已有主机识别（`edge/agent/host_inspection*.go`）与各采集器，但没有把
「宿主 / 容器 / 远程」视角与「不可读原因」作为一等投影；名称级主机信息（DMI product_name、
device-tree model）曾被误当作型号识别。

本模块只回答"现有已验证记录支持哪些视角结论"，并为不成立的情况给出固定原因码。
它**不是** HTTP 接口、**不**发起任何探测、**不**读 Docker socket、**不**扫描整机。

刻意不合并两件不同的事实：**声明视角**（`Environment.env_type`，管理员声明）与
**观测表面**（该环境内已有证据由哪类采集器产生）。两者不一致时报告 `conflict`，
不静默取其一，也不做"最可能"推断。

只读边界：只做租户限定的 `SELECT`；不写库、不产生审计/outbox/任务、不读 payload 正文
（只判断 `payload_ref` 是否存在，不载入其指向的内容）、不发起外部网络探测。
不复制第二套验证：环境定位复用 `app.routers.environments` 的租户限定语义。
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Environment, Evidence
from app.security import Identity

SCHEMA_VERSION = "enterprise-evidence-topology/v1"

# 视角词表（固定三值 + 一个显式的"未建立"）。不设"部分可见"。
HOST = "host"
CONTAINER = "container"
REMOTE = "remote"
NOT_ESTABLISHED = "not_established"

# 状态词表（固定五值），与 binding-evidence-readiness 的词表语义对齐但不共享代码。
OBSERVED = "observed_from_records"
DECLARED_ONLY = "declared_only"
CONFLICT = "declared_and_observed_conflict"
UNMAPPED = "connector_perspective_unmapped"
SOURCE_ABSENT = "source_absent"
STATES = (OBSERVED, DECLARED_ONLY, CONFLICT, UNMAPPED, SOURCE_ABSENT)

# 固定映射：采集器 source_type → 观测表面。**未列出的采集器不猜测归属**，
# 归入 `unmapped` 并报 `connector_perspective_unmapped`。
OS_SURFACE_CONNECTORS = frozenset({"process", "systemd", "directory"})
CONTAINER_SURFACE_CONNECTORS = frozenset({"docker", "kubernetes"})
# 智能体框架/配置类采集器：既不是宿主表面也不是容器表面，单列，不塞进三视角。
AGENT_CONFIG_CONNECTORS = frozenset({"hermes", "openclaw", "piagent", "workbuddy", "dify", "mcp", "siq"})
MAPPED_CONNECTORS = OS_SURFACE_CONNECTORS | CONTAINER_SURFACE_CONNECTORS | AGENT_CONFIG_CONNECTORS

# 声明 env_type → 声明视角。`account`（云账号）是**远程**视角：仓库内没有任何采集器
# 产生远程表面证据，因此该视角恒为 `source_absent`，不借用宿主/容器表面顶替。
DECLARED_PERSPECTIVE = {"host": HOST, "container": CONTAINER, "k8s": CONTAINER, "account": REMOTE}

# 声明视角 → 与之相容的观测表面；远程视角没有对应表面来源，显式缺席。
COMPATIBLE_SURFACES = {HOST: "os", CONTAINER: "container"}
PERSPECTIVE_WITHOUT_SURFACE_SOURCE = {REMOTE: "account_perspective_source_absent"}

REASON_CODES = frozenset({
    "environment_not_recorded_in_tenant",
    "no_evidence_in_environment_scope",
    "declared_environment_type_unknown",
    "account_perspective_source_absent",
    "connector_perspective_unmapped",
    "no_observable_surface_evidence",
    "declared_and_observed_perspective_conflict",
    "evidence_without_environment_scope",
    "payload_not_retained",
    "evidence_expired",
    "behavioral_fixture_source_absent",
})

# 不得由本投影推导出的结论（固定码，逐条不随输入变化）。
MUST_NOT_INFER = (
    "host_name_is_not_model_identification",
    "dmi_product_name_is_not_device_model",
    "devicetree_model_is_not_device_model",
    "declared_environment_type_is_not_observed_perspective",
    "connector_presence_is_not_coverage_of_that_surface",
    "readable_metadata_is_not_readable_content",
    "recorded_evidence_is_not_current_runtime_state",
    "topology_projection_is_not_enforcement_proof",
)


def project_evidence_topology(session: Session, identity: Identity, environment_id: str) -> dict:
    """只读投影一个环境内可核对的视角与来源边界。

    `tenant_id` 只取自服务端验证身份；环境缺失或属于其它租户时返回与"不存在"完全相同的
    结果，不构成跨租户存在性判别。
    """
    tenant_id = _tenant_of(identity)
    if not isinstance(environment_id, str) or not environment_id:
        raise ValueError("environment_id_required")
    # no_autoflush：不隐式刷新调用方会话中的待提交状态，本模块不产生任何写入。
    with session.no_autoflush:
        return _project(session, tenant_id, environment_id)


def _tenant_of(identity: Identity) -> str:
    tenant_id = getattr(identity, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("verified_tenant_identity_required")
    return tenant_id


def _project(session: Session, tenant_id: str, environment_id: str) -> dict:
    environment = session.scalar(select(Environment).where(
        Environment.id == environment_id, Environment.tenant_id == tenant_id))
    if environment is None:
        return _result(environment_id, SOURCE_ABSENT, ("environment_not_recorded_in_tenant",),
                       _empty_surfaces(), _empty_readability(), declared=None)

    declared = _declared_perspective(environment)
    surfaces, readability = _observed_facts(session, tenant_id, environment.id)
    state, reasons = _agreement(declared, surfaces, readability["total"])
    return _result(environment_id, state, reasons, surfaces, readability, declared)


def _declared_perspective(environment: Environment) -> dict:
    env_type = environment.env_type if isinstance(environment.env_type, str) else ""
    perspective = DECLARED_PERSPECTIVE.get(env_type)
    if perspective is None:
        return {"env_type": env_type or None, "perspective": NOT_ESTABLISHED,
                "reason": "declared_environment_type_unknown"}
    return {"env_type": env_type, "perspective": perspective,
            "reason": PERSPECTIVE_WITHOUT_SURFACE_SOURCE.get(perspective)}


def _empty_surfaces() -> dict:
    return {name: {"count": 0, "connectors": []} for name in ("os", "container", "agent_config", "unmapped")}


def _empty_readability() -> dict:
    return {"total": 0, "metadata_only": 0, "expired": 0, "reasons": []}


def _observed_facts(session: Session, tenant_id: str, environment_id: str):
    """两个独立计数：按采集器归类的观测表面，以及证据的可读性。绝不载入 payload 正文。"""
    now = datetime.now(UTC).replace(tzinfo=None)
    scoped = (Evidence.tenant_id == tenant_id, Evidence.environment_id == environment_id)
    rows = session.execute(
        select(Evidence.source_type, Evidence.payload_ref.is_(None),
               Evidence.expires_at.isnot(None) & (Evidence.expires_at < now))
        .where(*scoped)
    ).all()
    surfaces = _empty_surfaces()
    metadata_only = expired = 0
    for source_type, no_payload, is_expired in rows:
        bucket = _bucket(source_type)
        surfaces[bucket]["count"] += 1
        if bucket == "unmapped" and source_type not in surfaces[bucket]["connectors"]:
            surfaces[bucket]["connectors"].append(source_type)
        if no_payload:
            metadata_only += 1
        if is_expired:
            expired += 1
    for bucket in surfaces.values():
        bucket["connectors"].sort()
    reasons = []
    if metadata_only:
        reasons.append("payload_not_retained")
    if expired:
        reasons.append("evidence_expired")
    return surfaces, {"total": len(rows), "metadata_only": metadata_only,
                      "expired": expired, "reasons": reasons}


def _bucket(source_type: str) -> str:
    if source_type in OS_SURFACE_CONNECTORS:
        return "os"
    if source_type in CONTAINER_SURFACE_CONNECTORS:
        return "container"
    if source_type in AGENT_CONFIG_CONNECTORS:
        return "agent_config"
    return "unmapped"


def _agreement(declared: dict, surfaces: dict, evidence_total: int):
    """声明视角与观测表面的相容性。**不合并、不取最可能值**。"""
    reasons = []
    if surfaces["unmapped"]["count"]:
        reasons.append("connector_perspective_unmapped")
    perspective = declared["perspective"]
    if declared["reason"] is not None:
        reasons.append(declared["reason"])
    if evidence_total == 0:
        reasons.append("no_evidence_in_environment_scope")
    if perspective == NOT_ESTABLISHED or perspective in PERSPECTIVE_WITHOUT_SURFACE_SOURCE:
        # 声明侧没有对应的表面来源（未知类型，或远程视角无采集器）：无论观测到什么，
        # 本投影都不宣称视角一致，也不借用其它表面顶替。
        return NOT_ESTABLISHED, sorted(set(reasons))
    compatible = COMPATIBLE_SURFACES[perspective]
    if surfaces[compatible]["count"] == 0:
        if evidence_total == 0:
            return DECLARED_ONLY, sorted(set(reasons))
        # 观测到了东西，但没有一个属于声明视角相容的表面。
        reasons.append("declared_and_observed_perspective_conflict")
        return CONFLICT, sorted(set(reasons))
    if _has_conflicting_surface(perspective, surfaces):
        reasons.append("declared_and_observed_perspective_conflict")
        return CONFLICT, sorted(set(reasons))
    if reasons:
        # 表面相容但仍有未归类采集器：结论成立但标注边界，不静默吞掉。
        return OBSERVED, sorted(set(reasons))
    return OBSERVED, []


def _has_conflicting_surface(perspective: str, surfaces: dict) -> bool:
    """声明宿主却观测到容器表面（或反之）即为冲突；不因同时存在相容表面而降级为一致。"""
    other = "container" if perspective == HOST else "os"
    return surfaces[other]["count"] > 0


def _result(environment_id, state, reasons, surfaces, readability, declared):
    return {
        "schema_version": SCHEMA_VERSION,
        "environment_id": environment_id,
        "declared_perspective": declared,
        "observed_surfaces": surfaces,
        "perspective_state": state,
        "reasons": sorted(set(reasons)),
        "evidence_readability": readability,
        # 行为级证据没有任何采集/存储来源：这是能力未建立，不是"缺一条记录"。
        # `enforcement_verified` 在仓储内被刻意保留，本模块**不生产**该值。
        "enforcement_verified": False,
        "behavioral_evidence": {"state": NOT_ESTABLISHED,
                                "reason": "behavioral_fixture_source_absent"},
        "coverage": "recorded_evidence_in_environment_only",
        "must_not_infer": list(MUST_NOT_INFER),
    }
