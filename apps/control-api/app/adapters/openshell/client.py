"""真实 OpenShell 客户端占位（fail-closed）。

D1 spike（OpenShell 版本路径决策）与 SIQ 基座部署（开发计划 D2）完成后接入：
- Gateway API 端点、策略 Schema、revision 语义以能力探测为准；
- 未接入前任何调用必须失败关闭，绝不伪装成功（设计文档 §6.5/§6.6）。
"""

from __future__ import annotations

from app.adapters.openshell.base import EnforcementAdapter
from app.adapters.openshell.contracts import (
    AdapterError,
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


class OpenShellHttpClient(EnforcementAdapter):
    """真实后端 HTTP 客户端（待 D1/D2 后实现）。所有方法 fail-closed。"""

    def __init__(self, base_url: str):
        self.base_url = base_url

    def _pending(self, op: str) -> AdapterError:
        return AdapterError(
            f"openshell client 未接入（{op}）：等待 D1 版本路径决策与 D2 SIQ 基座部署（开发计划 §3）"
        )

    def probe(self) -> BackendCapabilities:
        raise self._pending("probe")

    def list_targets(self, cursor: str | None = None) -> SandboxPage:
        raise self._pending("list_targets")

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        raise self._pending("read_effective_policy")

    def compile(self, desired_policy: dict, capabilities: BackendCapabilities | None = None) -> CompiledPolicy:
        raise self._pending("compile")

    def validate(self, compiled: CompiledPolicy) -> ValidationReport:
        raise self._pending("validate")

    def plan_change(self, target: str, compiled: CompiledPolicy) -> ChangePlan:
        raise self._pending("plan_change")

    def apply_dynamic(self, target: str, plan: ChangePlan, expected_revision: str) -> DeploymentReceipt:
        raise self._pending("apply_dynamic")

    def create_generation(self, target: str, compiled: CompiledPolicy) -> DeploymentReceipt:
        raise self._pending("create_generation")

    def verify(self, target: str, checks: dict, receipt: DeploymentReceipt) -> VerificationReport:
        raise self._pending("verify")

    def rollback(self, target: str, receipt: DeploymentReceipt) -> RollbackReceipt:
        raise self._pending("rollback")

    def stream_events(self, cursor: str | None = None) -> EventBatch:
        raise self._pending("stream_events")
