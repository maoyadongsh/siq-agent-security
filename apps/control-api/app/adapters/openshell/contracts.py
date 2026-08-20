"""OpenShell Adapter 合同类型（设计文档 §15.3）。

字段与约束逐条对齐 §15.3 关键约束：
- probe 返回实际能力、限制和 Schema 版本（不按版本号假设）；
- read_effective_policy 读取后端实际状态，不能只读控制面上次提交值；
- compile 对不支持字段失败或显式返回未覆盖项（§14.1 不静默丢失）；
- apply_dynamic 使用期望 revision，防止覆盖带外变更；
- create_generation 生成新实例，验证通过后才能切流；
- verify 至少验证预期允许和预期拒绝各一项；
- verify 结果必须如实分级（VerificationReport.level）：配置读回类检查只能产出
  readback_verified；enforcement_verified 需要真实行为 fixture 证据，
  当前 CLI 后端没有行为 fixture 通道，禁止产出该级别；
- 能力报告按能力域逐项标注（CapabilityItem）：未实测的能力一律 unknown 或
  unsupported，不得猜 supported；
- 日志和回执必须脱敏，不能包含 Provider Key、Sandbox Token 或业务正文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------ 能力文档（P1-1）

# 能力项状态：supported=已实测可用；unsupported=已确认不可用；unknown=未实测（fail-closed）
CAPABILITY_STATUSES = ("supported", "unsupported", "unknown")
# 执行语义：enforce=强制执行；observe=只观测不拦截；advisory=仅建议；none=无执行语义
ENFORCEMENT_SEMANTICS = ("enforce", "observe", "advisory", "none")

# 能力域键名（版本化能力文档的固定键）
CAP_SANDBOX_LIFECYCLE = "sandbox_lifecycle"  # 沙箱创建/重建（generation）
CAP_FILESYSTEM = "filesystem"
CAP_PROCESS = "process"
CAP_NETWORK_L34 = "network_l34"  # host:port 粒度
CAP_NETWORK_L7 = "network_l7"  # path/method 等 L7 粒度
CAP_TOOLS_MCP = "tools_mcp"  # 工具/MCP 调用治理
CAP_MODEL_ROUTING = "model_routing"
CAP_SECRETS = "secrets"  # 凭据注入
CAP_RESOURCES = "resources"  # 资源配额
CAP_AUDIT_EVENTS = "audit_events"  # 审计/行为事件流
CAP_MODE_BLOCK = "enforcement_mode.block"
CAP_MODE_WARN = "enforcement_mode.warn"
CAP_MODE_AUDIT_ONLY = "enforcement_mode.audit_only"


@dataclass(frozen=True)
class CapabilityItem:
    """单个能力项：状态 + 执行语义 + 判定依据（实测出处或保守假设说明）。"""

    status: str  # supported | unsupported | unknown
    semantics: str = "none"  # enforce | observe | advisory | none
    basis: str = ""  # 依据（实测日期/网关行为/未实测说明），禁止空泛猜测


# ------------------------------------------------------------ verify 分级（P1-2）

VERIFY_LEVEL_READBACK = "readback_verified"  # 配置读回验证通过（不证明行为执行）
VERIFY_LEVEL_ENFORCEMENT = "enforcement_verified"  # 行为 fixture 验证通过（当前无后端可产出）
VERIFY_LEVEL_FAILED = "failed"


class AdapterError(Exception):
    """适配器错误基类。"""


class RevisionConflict(AdapterError):
    """期望 revision 与后端当前 revision 不一致（并发/带外变更）。"""

    def __init__(self, expected: str | None, actual: str):
        super().__init__(f"revision conflict: expected={expected}, actual={actual}")
        self.expected = expected
        self.actual = actual


class UnsupportedCapability(AdapterError):
    """后端能力不满足编译要求。"""


class VerificationFailed(AdapterError):
    """正负向验证失败。"""


@dataclass(frozen=True)
class BackendCapabilities:
    """probe() 结果：实际能力，不是版本号推断。

    布尔字段为早期合同保留的便捷视图（多处使用，保持向后兼容）；
    版本化能力文档见 capabilities：按能力域逐项报告 CapabilityItem，
    编译器与部署路由应优先依据能力文档做 fail-closed 判定。
    """

    backend: str  # openshell
    schema_version: str  # 策略 Schema 版本（由 probe 探测结果组成，不硬编码）
    dynamic_network_update: bool  # 由 probe 实测填充（v0.0.83 网关 2026-08-13 实测 policy set 热更新可用）
    static_filesystem: bool = True  # 创建时锁定
    static_process: bool = True
    landlock: bool = False
    interceptor: bool = False  # 未经实测验证
    provider_credential_injection: bool = False
    revision_support: bool = True
    max_filesystem_paths: int = 1024
    # 版本化能力文档（P1-1）：键为 CAP_* 能力域，未报告的项按 unknown fail-closed
    capabilities: dict[str, CapabilityItem] = field(default_factory=dict)

    def capability(self, name: str) -> CapabilityItem:
        """查询能力项；文档未报告 → unknown（fail-closed，绝不当作 supported）。"""
        return self.capabilities.get(
            name,
            CapabilityItem(status="unknown", semantics="none", basis="probe 能力文档未报告该能力项"),
        )


@dataclass(frozen=True)
class PolicySnapshot:
    """后端当前实际生效策略（read_effective_policy）。

    enforcement_mode 语义：只能从后端真实输出确定时填写具体模式；
    后端输出无法确定模式时如实填 "unknown"，禁止无条件硬编码 "block"。
    """

    target: str
    revision: str
    filesystem: dict[str, Any] = field(default_factory=dict)
    network: list[dict[str, Any]] = field(default_factory=list)
    process: dict[str, Any] = field(default_factory=dict)
    enforcement_mode: str = "unknown"  # block|warn|audit_only|unknown（默认 unknown：不可确定不得编造）
    observed_at: str | None = None  # 后端观察时间，脱敏摘要


@dataclass(frozen=True)
class CompiledPolicy:
    """Desired Policy → 后端策略制品（compile）。"""

    policy_id: str
    version: int
    backend: str
    schema_version: str
    artifact: dict[str, Any]  # 规范化制品
    artifact_hash: str  # 规范化哈希
    unsupported_by_backend: list[str] = field(default_factory=list)  # 显式未覆盖项
    needs_generation: bool = False  # 静态边界变化需重建 Sandbox
    enforcement_mode: str = "audit_only"


@dataclass(frozen=True)
class ValidationReport:
    """编译制品静态校验（validate）。"""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChangePlan:
    """变更计划（plan_change）：区分动态更新与重建。"""

    target: str
    kind: str  # dynamic | generation
    expected_revision: str
    artifact_hash: str
    steps: list[str] = field(default_factory=list)
    requires_verification: bool = True


@dataclass(frozen=True)
class DeploymentReceipt:
    """发布回执。evidence 必须可机器校验（§21.1 不变量 #5），禁止凭据。"""

    backend_revision: str
    evidence: dict[str, Any] = field(default_factory=dict)  # snapshot_hash 等
    applied_at: str | None = None


@dataclass(frozen=True)
class VerificationReport:
    """verify() 结果：至少一项预期允许 + 一项预期拒绝。

    level 如实标注验证强度：
    - readback_verified：仅配置读回一致（不证明行为执行）；
    - enforcement_verified：有真实行为 fixture 证据（当前 CLI/HTTP/Fake 后端
      均无行为 fixture 通道，禁止产出该级别）；
    - failed：任一检查失败。
    checks 中的每项必须携带 request/expected/actual/revision，便于审计复核。
    """

    passed: bool
    level: str = VERIFY_LEVEL_FAILED  # readback_verified | enforcement_verified | failed
    allow_checks: list[dict[str, Any]] = field(default_factory=list)
    deny_checks: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RollbackReceipt:
    """回滚回执。"""

    restored_revision: str
    evidence: dict[str, Any] = field(default_factory=dict)
    rolled_back_at: str | None = None


@dataclass(frozen=True)
class SandboxPage:
    """目标列表页（list_targets）。"""

    targets: list[dict[str, Any]] = field(default_factory=list)
    cursor: str | None = None


@dataclass(frozen=True)
class EventBatch:
    """后端事件流（stream_events），已脱敏。

    source 如实标注事件来源（如 cli_policy_list_readback / fake_backend_log /
    gateway_events）。注意：当前 CLI 后端的 "事件" 是 policy list 文本回读，
    不是行为事件流；消费方不得把 source 非行为通道的批次当作执行证据。
    """

    events: list[dict[str, Any]] = field(default_factory=list)
    cursor: str | None = None
    source: str = "unknown"  # 事件来源通道标注（P1-2）
