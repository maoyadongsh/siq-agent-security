"""OpenShell Enforcement Adapter（设计文档 §15.3 合同）。

合同类型 + 策略编译器 + 同一 EnforcementAdapter 合同的两套 transport 实现：
- OpenShellCliBackend（cli_backend.py）：当前部署路由使用的 CLI transport；
- OpenShellHttpClient（client.py）：HTTP transport，端点待联调校准；
- FakeOpenShellBackend：契约测试参照。
"""

from app.adapters.openshell.base import EnforcementAdapter
from app.adapters.openshell.contracts import (
    BackendCapabilities,
    ChangePlan,
    CompiledPolicy,
    DeploymentReceipt,
    EventBatch,
    PolicySnapshot,
    RevisionConflict,
    RollbackReceipt,
    SandboxPage,
    ValidationReport,
    VerificationReport,
)
from app.adapters.openshell.fake_backend import FakeOpenShellBackend

__all__ = [
    "EnforcementAdapter",
    "BackendCapabilities",
    "ChangePlan",
    "CompiledPolicy",
    "DeploymentReceipt",
    "EventBatch",
    "PolicySnapshot",
    "RevisionConflict",
    "RollbackReceipt",
    "SandboxPage",
    "ValidationReport",
    "VerificationReport",
    "FakeOpenShellBackend",
]
