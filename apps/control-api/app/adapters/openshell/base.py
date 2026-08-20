"""EnforcementAdapter 抽象合同（设计文档 §15.3 十方法）。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.adapters.openshell.contracts import (
    BackendCapabilities,
    ChangePlan,
    CompiledPolicy,
    DeploymentReceipt,
    EventBatch,
    PolicySnapshot,
    RollbackReceipt,
    SandboxPage,
    ValidationReport,
    VerificationReport,
)


class EnforcementAdapter(ABC):
    @abstractmethod
    def probe(self) -> BackendCapabilities:
        """返回实际能力、限制和 Schema 版本。"""

    @abstractmethod
    def list_targets(self, cursor: str | None = None) -> SandboxPage:
        ...

    @abstractmethod
    def read_effective_policy(self, target: str) -> PolicySnapshot:
        """读取后端实际状态，不能只读取控制面上次提交值。"""

    @abstractmethod
    def compile(self, desired_policy: dict, capabilities: BackendCapabilities | None = None) -> CompiledPolicy:
        """对不支持字段失败或显式返回未覆盖项。"""

    @abstractmethod
    def validate(self, compiled: CompiledPolicy) -> ValidationReport:
        ...

    @abstractmethod
    def plan_change(self, target: str, compiled: CompiledPolicy) -> ChangePlan:
        ...

    @abstractmethod
    def apply_dynamic(self, target: str, plan: ChangePlan, expected_revision: str) -> DeploymentReceipt:
        """期望 revision 防并发/带外覆盖。"""

    @abstractmethod
    def create_generation(self, target: str, compiled: CompiledPolicy) -> DeploymentReceipt:
        """静态边界变化：生成新实例，验证通过后才能切流。"""

    @abstractmethod
    def verify(self, target: str, checks: dict, receipt: DeploymentReceipt) -> VerificationReport:
        """至少验证预期允许和预期拒绝各一项。

        实现必须在 report.level 如实标注验证强度：配置读回类检查只能产出
        readback_verified；enforcement_verified 需要真实行为 fixture 证据
        （当前所有后端实现均无行为 fixture 通道，禁止产出该级别）。
        """

    @abstractmethod
    def rollback(self, target: str, receipt: DeploymentReceipt) -> RollbackReceipt:
        ...

    @abstractmethod
    def stream_events(self, cursor: str | None = None) -> EventBatch:
        """事件批次必须在 source/事件 type 如实标注来源；CLI 后端的 policy list
        回读不是行为事件流，不得伪装成行为事件。"""
