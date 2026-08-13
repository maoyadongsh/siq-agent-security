"""OpenShell Enforcement Adapter（设计文档 §15.3 合同）。

Phase 3 前置：合同类型 + 策略编译器 + FakeBackend（契约测试）。
真实 client 在 D1 spike（OpenShell 版本路径决策）后接入，当前 fail-closed 占位。
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
