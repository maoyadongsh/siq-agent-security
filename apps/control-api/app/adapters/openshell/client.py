"""真实 OpenShell HTTP 客户端（能力探测驱动骨架，D1 决策后联调校准）。

现状（2026-08-13）：D1 spike 确认两补丁已上游化（v0.0.104），升级路径清晰；
本客户端按"探测先行"实现：
- 端点路径可配置（SIQ_AS_OPENSHELL_* 环境变量），默认值按官方 Gateway API 形状，
  联调构建环境时以实测校准（V5 能力探测步骤）；
- 任何不可达/未知响应 → AdapterError（fail-closed，绝不伪装成功）；
- 409 并发冲突 → RevisionConflict（对齐 FakeBackend 语义）；
- httpx.MockTransport 可注入，单测不依赖真实网关。
"""

from __future__ import annotations

import os

import httpx

from app.adapters.openshell.base import EnforcementAdapter
from app.adapters.openshell.contracts import (
    AdapterError,
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
from app.adapters.openshell.policy_compiler import compile_policy, validate_compiled


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


class OpenShellHttpClient(EnforcementAdapter):
    """真实 Gateway 客户端。默认端点路径待构建环境联调校准（见模块 docstring）。"""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        endpoints: dict[str, str] | None = None,
    ):
        self.base_url = (base_url or _env("SIQ_AS_OPENSHELL_GATEWAY_URL", "https://127.0.0.1:17671")).rstrip("/")
        # 端点路径默认值（官方 Gateway API 形状，V5 探测后校准）
        self.endpoints = {
            "health": "/v1/health",
            "capabilities": "/v1/capabilities",
            "sandboxes": "/v1/sandboxes",
            "events": "/v1/events",
        }
        if endpoints:
            self.endpoints.update(endpoints)
        self._http = httpx.Client(base_url=self.base_url, transport=transport, timeout=10.0)

    # ------------------------------------------------------------ HTTP 基础

    def _request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> dict:
        try:
            resp = self._http.request(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            raise AdapterError(f"openshell gateway 不可达（fail-closed）: {exc}") from exc
        if resp.status_code == 409:
            raise RevisionConflict(expected="(from request)", actual="(backend)")
        if resp.status_code >= 400:
            raise AdapterError(f"openshell gateway 错误 {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AdapterError("openshell gateway 返回非 JSON（fail-closed）") from exc

    # ------------------------------------------------------------ 合同实现

    def probe(self) -> BackendCapabilities:
        """能力探测：先 health，再 capabilities。任何失败 fail-closed。"""
        health = self._request("GET", self.endpoints["health"])
        if not health.get("ok"):
            raise AdapterError("openshell gateway health 检查失败")
        caps = self._request("GET", self.endpoints["capabilities"])
        return BackendCapabilities(
            backend="openshell",
            schema_version=str(caps.get("schema_version", "unknown")),
            dynamic_network_update=bool(caps.get("dynamic_network_update", False)),
            static_filesystem=bool(caps.get("static_filesystem", True)),
            static_process=bool(caps.get("static_process", True)),
            landlock=bool(caps.get("landlock", False)),
            interceptor=bool(caps.get("interceptor", False)),
            provider_credential_injection=bool(caps.get("provider_credential_injection", False)),
            revision_support=bool(caps.get("revision_support", True)),
            max_filesystem_paths=int(caps.get("max_filesystem_paths", 1024)),
        )

    def list_targets(self, cursor: str | None = None) -> SandboxPage:
        params = {"cursor": cursor} if cursor else None
        data = self._request("GET", self.endpoints["sandboxes"], params=params)
        targets = data.get("sandboxes", data if isinstance(data, list) else [])
        return SandboxPage(
            targets=[{"id": t.get("id"), "revision": t.get("revision")} for t in targets],
            cursor=data.get("cursor") if isinstance(data, dict) else None,
        )

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        """读后端实际生效策略（不回退到控制面上次提交值）。"""
        data = self._request("GET", f"{self.endpoints['sandboxes']}/{target}/policy")
        return PolicySnapshot(
            target=target,
            revision=str(data.get("revision", "0")),
            filesystem=data.get("filesystem_policy") or {},
            network=data.get("network_policies") or [],
            process=data.get("process") or {},
            enforcement_mode=str(data.get("enforcement_mode", "block")),
            observed_at=data.get("observed_at"),
        )

    def compile(self, desired_policy: dict, capabilities: BackendCapabilities | None = None) -> CompiledPolicy:
        caps = capabilities or self.probe()
        return compile_policy(desired_policy, caps)

    def validate(self, compiled: CompiledPolicy) -> ValidationReport:
        return validate_compiled(compiled)

    def plan_change(self, target: str, compiled: CompiledPolicy) -> ChangePlan:
        current = self.read_effective_policy(target)
        kind = "generation" if compiled.needs_generation else "dynamic"
        return ChangePlan(
            target=target,
            kind=kind,
            expected_revision=current.revision,
            artifact_hash=compiled.artifact_hash,
            steps=[f"apply {kind} policy {compiled.artifact_hash[:12]}"],
        )

    def apply_dynamic(self, target: str, plan: ChangePlan, expected_revision: str) -> DeploymentReceipt:
        """动态网络策略更新：期望 revision 防并发；后端 409 → RevisionConflict。"""
        data = self._request(
            "PATCH",
            f"{self.endpoints['sandboxes']}/{target}/policy",
            json={"expected_revision": expected_revision, "artifact_hash": plan.artifact_hash},
        )
        return DeploymentReceipt(
            backend_revision=str(data.get("revision", "")),
            evidence={"snapshot_hash": data.get("snapshot_hash", ""), "response": data},
            applied_at=data.get("applied_at"),
        )

    def create_generation(self, target: str, compiled: CompiledPolicy) -> DeploymentReceipt:
        data = self._request(
            "POST",
            self.endpoints["sandboxes"],
            json={
                "target": target,
                "policy": compiled.artifact,
                "enforcement_mode": compiled.enforcement_mode,
            },
        )
        return DeploymentReceipt(
            backend_revision=str(data.get("revision", "")),
            evidence={"snapshot_hash": data.get("snapshot_hash", ""), "response": data},
            applied_at=data.get("applied_at"),
        )

    def verify(self, target: str, checks: dict, receipt: DeploymentReceipt) -> VerificationReport:
        """正负向验证：allow 项读回策略确认命中；deny 项确认不在允许集（block 模式）。"""
        failures: list[str] = []
        snapshot = self.read_effective_policy(target)
        if snapshot.revision != receipt.backend_revision:
            failures.append(f"revision mismatch: {snapshot.revision} != {receipt.backend_revision}")
        allowed = {r.get("endpoint") for r in snapshot.network if r.get("effect") != "deny"}
        allow_checks = [{"endpoint": e, "result": "allow"} for e in checks.get("expect_allow", [])]
        deny_checks = [{"endpoint": e, "result": "deny"} for e in checks.get("expect_deny", [])]
        for check in allow_checks:
            if check["endpoint"] not in allowed:
                failures.append(f"allow check failed: {check['endpoint']}")
        for check in deny_checks:
            if check["endpoint"] in allowed and snapshot.enforcement_mode == "block":
                failures.append(f"deny check failed: {check['endpoint']}")
        if not allow_checks or not deny_checks:
            failures.append("正负向验证必须各至少一项（§15.3）")
        return VerificationReport(
            passed=not failures, allow_checks=allow_checks, deny_checks=deny_checks, failures=failures
        )

    def rollback(self, target: str, receipt: DeploymentReceipt) -> RollbackReceipt:
        data = self._request(
            "POST",
            f"{self.endpoints['sandboxes']}/{target}/rollback",
            json={"from_revision": receipt.backend_revision},
        )
        return RollbackReceipt(
            restored_revision=str(data.get("revision", "")),
            evidence={"response": data},
            rolled_back_at=data.get("rolled_back_at"),
        )

    def stream_events(self, cursor: str | None = None) -> EventBatch:
        params = {"cursor": cursor} if cursor else None
        data = self._request("GET", self.endpoints["events"], params=params)
        return EventBatch(events=data.get("events", []) if isinstance(data, dict) else [], cursor=data.get("cursor"))
