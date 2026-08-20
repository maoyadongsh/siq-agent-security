"""OpenShell Adapter 合同类型（设计文档 §15.3）。

字段与约束逐条对齐 §15.3 关键约束：
- probe 返回实际能力、限制和 Schema 版本（不按版本号假设）；
- read_effective_policy 读取后端实际状态，不能只读控制面上次提交值；
- compile 对不支持字段失败或显式返回未覆盖项（§14.1 不静默丢失）；
- apply_dynamic 使用期望 revision，防止覆盖带外变更；
- create_generation 生成新实例，验证通过后才能切流；
- verify 至少验证预期允许和预期拒绝各一项；
- 日志和回执必须脱敏，不能包含 Provider Key、Sandbox Token 或业务正文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    """probe() 结果：实际能力，不是版本号推断。"""

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


@dataclass(frozen=True)
class PolicySnapshot:
    """后端当前实际生效策略（read_effective_policy）。"""

    target: str
    revision: str
    filesystem: dict[str, Any] = field(default_factory=dict)
    network: list[dict[str, Any]] = field(default_factory=list)
    process: dict[str, Any] = field(default_factory=dict)
    enforcement_mode: str = "block"
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
    """verify() 结果：至少一项预期允许 + 一项预期拒绝。"""

    passed: bool
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
    """后端事件流（stream_events），已脱敏。"""

    events: list[dict[str, Any]] = field(default_factory=list)
    cursor: str | None = None
