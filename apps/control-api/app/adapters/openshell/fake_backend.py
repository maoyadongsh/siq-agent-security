"""FakeOpenShellBackend：契约测试用内存后端（Phase 3 真实后端接入前的合同参照）。

默认能力镜像 SIQ 冻结版本 v0.0.83：dynamic_network_update=False（编译期固定集合）、
interceptor=False、provider_credential_injection=False（设计文档兼容矩阵）。
行为与真实后端约束一致：revision 并发冲突、静态边界需 generation、正负向验证、回滚。
"""

from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime

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
    VerificationFailed,
    VerificationReport,
)
from app.adapters.openshell.policy_compiler import _canonical, compile_policy, validate_compiled


class FakeOpenShellBackend(EnforcementAdapter):
    def __init__(self, *, dynamic_network_update: bool = False, interceptor: bool = False):
        self.capabilities = BackendCapabilities(
            backend="openshell",
            schema_version="siq.openshell.policy.v1",
            dynamic_network_update=dynamic_network_update,
            interceptor=interceptor,
            provider_credential_injection=False,
            landlock=True,
        )
        self._lock = threading.Lock()
        # target -> {"revision": int, "snapshot": PolicySnapshot, "history": [PolicySnapshot]}
        self._targets: dict[str, dict] = {}
        # artifact_hash -> CompiledPolicy（compile 注册，apply 引用）
        self._artifacts: dict[str, CompiledPolicy] = {}
        self._events: list[dict] = []

    # ------------------------------------------------------------ 合同实现

    def probe(self) -> BackendCapabilities:
        return self.capabilities

    def list_targets(self, cursor: str | None = None) -> SandboxPage:
        with self._lock:
            return SandboxPage(
                targets=[{"id": t, "revision": s["revision"]} for t, s in self._targets.items()],
                cursor=None,
            )

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        """读取后端实际状态（不是控制面上次提交值）。"""
        with self._lock:
            state = self._targets.get(target)
            if state is None:
                return PolicySnapshot(target=target, revision="0", enforcement_mode="block")
            return state["snapshot"]

    def compile(self, desired_policy: dict, capabilities: BackendCapabilities | None = None) -> CompiledPolicy:
        compiled = compile_policy(desired_policy, capabilities or self.capabilities)
        with self._lock:
            self._artifacts[compiled.artifact_hash] = compiled
        return compiled

    def validate(self, compiled: CompiledPolicy) -> ValidationReport:
        return validate_compiled(compiled)

    def plan_change(self, target: str, compiled: CompiledPolicy) -> ChangePlan:
        with self._lock:
            current = self._targets.get(target, {}).get("revision", 0)
        kind = "generation" if compiled.needs_generation else "dynamic"
        return ChangePlan(
            target=target,
            kind=kind,
            expected_revision=str(current),
            artifact_hash=compiled.artifact_hash,
            steps=[f"apply {kind} policy {compiled.artifact_hash[:12]}"],
        )

    def apply_dynamic(self, target: str, plan: ChangePlan, expected_revision: str) -> DeploymentReceipt:
        with self._lock:
            state = self._targets.get(target)
            current = str(state["revision"]) if state else "0"
            if current != expected_revision:
                raise RevisionConflict(expected=expected_revision, actual=current)
            compiled = self._artifacts.get(plan.artifact_hash)
            if compiled is None:
                raise VerificationFailed("未知制品哈希，拒绝发布")
            if compiled.needs_generation:
                raise VerificationFailed("静态边界变化不能走动态发布路径")
            state = self._targets.setdefault(
                target,
                {"revision": 0, "snapshot": PolicySnapshot(target=target, revision="0"), "history": []},
            )
            state["history"].append(state["snapshot"])
            new_rev = state["revision"] + 1
            snapshot = PolicySnapshot(
                target=target,
                revision=str(new_rev),
                filesystem=state["snapshot"].filesystem,  # 动态更新保留静态边界
                network=compiled.artifact.get("network_policies", []),
                process=state["snapshot"].process,
                enforcement_mode=compiled.enforcement_mode,
                observed_at=self._now(),
            )
            state["snapshot"] = snapshot
            state["revision"] = new_rev
            self._events.append({"type": "policy.applied", "target": target, "revision": new_rev})
            return DeploymentReceipt(
                backend_revision=str(new_rev),
                evidence={"snapshot_hash": self._snapshot_hash(snapshot)},
                applied_at=self._now(),
            )

    def create_generation(self, target: str, compiled: CompiledPolicy) -> DeploymentReceipt:
        with self._lock:
            state = self._targets.setdefault(
                target,
                {"revision": 0, "snapshot": PolicySnapshot(target=target, revision="0"), "history": []},
            )
            state["history"].append(state["snapshot"])
            new_rev = state["revision"] + 1
            snapshot = PolicySnapshot(
                target=target,
                revision=str(new_rev),
                filesystem=compiled.artifact.get("filesystem_policy", {}),
                network=compiled.artifact.get("network_policies", []),
                process=compiled.artifact.get("process", {}),
                enforcement_mode=compiled.enforcement_mode,
                observed_at=self._now(),
            )
            state["snapshot"] = snapshot
            state["revision"] = new_rev
            self._events.append({"type": "generation.created", "target": target, "revision": new_rev})
            return DeploymentReceipt(
                backend_revision=str(new_rev),
                evidence={"snapshot_hash": self._snapshot_hash(snapshot)},
                applied_at=self._now(),
            )

    def verify(self, target: str, checks: dict, receipt: DeploymentReceipt) -> VerificationReport:
        """正负向验证各至少一项：allow 项必须命中网络规则，deny 项必须被拒绝。"""
        allow_checks = [{"endpoint": e, "result": "allow"} for e in checks.get("expect_allow", [])]
        deny_checks = [{"endpoint": e, "result": "deny"} for e in checks.get("expect_deny", [])]
        failures: list[str] = []
        snapshot = self.read_effective_policy(target)
        if snapshot.revision != receipt.backend_revision:
            failures.append(f"revision mismatch: {snapshot.revision} != {receipt.backend_revision}")
        allowed_endpoints = {r.get("endpoint") for r in snapshot.network if r.get("effect") != "deny"}
        for check in allow_checks:
            if check["endpoint"] not in allowed_endpoints:
                failures.append(f"allow check failed: {check['endpoint']}")
        for check in deny_checks:
            if check["endpoint"] in allowed_endpoints and snapshot.enforcement_mode == "block":
                failures.append(f"deny check failed: {check['endpoint']}")
        if not allow_checks or not deny_checks:
            failures.append("正负向验证必须各至少一项（§15.3）")
        self._events.append({"type": "policy.verified", "target": target, "passed": not failures})
        return VerificationReport(
            passed=not failures, allow_checks=allow_checks, deny_checks=deny_checks, failures=failures
        )

    def rollback(self, target: str, receipt: DeploymentReceipt) -> RollbackReceipt:
        with self._lock:
            state = self._targets.get(target)
            if state is None or not state["history"]:
                raise VerificationFailed("无可回滚的历史快照")
            previous = state["history"].pop()
            state["snapshot"] = previous
            state["revision"] = int(previous.revision)
            self._events.append({"type": "policy.rolled_back", "target": target, "revision": previous.revision})
            return RollbackReceipt(
                restored_revision=previous.revision,
                evidence={"snapshot_hash": self._snapshot_hash(previous)},
                rolled_back_at=self._now(),
            )

    def stream_events(self, cursor: str | None = None) -> EventBatch:
        with self._lock:
            return EventBatch(events=list(self._events), cursor=None)

    # ------------------------------------------------------------ 内部

    def _snapshot_hash(self, snapshot: PolicySnapshot) -> str:
        payload = {
            "target": snapshot.target,
            "revision": snapshot.revision,
            "network": snapshot.network,
            "filesystem": snapshot.filesystem,
            "process": snapshot.process,
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()
