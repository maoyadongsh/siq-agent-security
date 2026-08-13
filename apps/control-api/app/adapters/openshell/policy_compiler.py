"""Desired Policy → OpenShell 策略制品编译（设计文档 §15.2 能力映射）。

铁律（§14.1）：后端不支持的字段必须标记 unsupported 或由其他执行点承担，
编译时不得静默丢失；未知语义拒绝。
"""

from __future__ import annotations

import hashlib
import json

from app.adapters.openshell.contracts import (
    BackendCapabilities,
    CompiledPolicy,
    UnsupportedCapability,
    ValidationReport,
)

# §15.2 通用权限 → OpenShell 映射
_DOMAIN_MAP = {
    "filesystem": "filesystem_policy",  # 静态：重建生效
    "process": "process",  # 静态：重建生效
    "network": "network_policies",  # 动态能力取决于后端版本（能力探测）
    "model": "inference_routing",  # 凭据不进入 Agent；不支持则标 unsupported
    "credential": "provider_credentials",
}


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compile_policy(desired_policy: dict, capabilities: BackendCapabilities) -> CompiledPolicy:
    """编译 Desired Policy。未知键 → UnsupportedCapability（拒绝），可映射但不支持 → unsupported 列表。"""
    known_keys = {
        "policy_id",
        "selector",
        "filesystem",
        "network",
        "process",
        "model_routing",
        "tools",
        "tool_policies",
        "data_scope_refs",
        "secrets",
        "resources",
        "audit",
        "exceptions",
        "enforcement_mode",
        "version",
        "status",
    }
    unknown = set(desired_policy) - known_keys
    if unknown:
        raise UnsupportedCapability(f"未知策略字段（拒绝编译）: {sorted(unknown)}")

    artifact: dict = {"version": 1}
    unsupported: list[str] = []
    needs_generation = False

    fs = desired_policy.get("filesystem")
    if fs:
        artifact["filesystem_policy"] = {
            "read_only": fs.get("read_only") or [],
            "read_write": fs.get("read_write") or [],
        }
        needs_generation = True  # 静态边界：创建时锁定（§15.2）
    process = desired_policy.get("process")
    if process:
        artifact["process"] = process
        needs_generation = True

    network = desired_policy.get("network")
    if network:
        if not capabilities.dynamic_network_update:
            # v0.0.83 现状：编译期固定集合，动态更新为版本依赖项（ADR-005/009）
            unsupported.append("network.dynamic_update")
            artifact["network_policies"] = network  # 落为静态制品，由 generation 路径生效
            needs_generation = True
        else:
            artifact["network_policies"] = network

    if desired_policy.get("model_routing"):
        if not capabilities.provider_credential_injection:
            unsupported.append("model_routing.inference_routing")
        else:
            artifact["inference_routing"] = desired_policy["model_routing"]
    if desired_policy.get("secrets"):
        # 凭据只存引用；注入能力由 Provider 侧承担（§15.2）
        unsupported.append("secrets.injection")

    for key in ("tools", "tool_policies", "data_scope_refs", "resources", "audit", "exceptions"):
        if desired_policy.get(key):
            unsupported.append(f"{key}: 由其他执行点承担")

    artifact_bytes = _canonical(artifact)
    return CompiledPolicy(
        policy_id=desired_policy.get("policy_id", ""),
        version=int(desired_policy.get("version") or 1),
        backend=capabilities.backend,
        schema_version=capabilities.schema_version,
        artifact=artifact,
        artifact_hash=hashlib.sha256(artifact_bytes).hexdigest(),
        unsupported_by_backend=unsupported,
        needs_generation=needs_generation,
        enforcement_mode=desired_policy.get("enforcement_mode", "audit_only"),
    )


def validate_compiled(compiled: CompiledPolicy) -> ValidationReport:
    """静态校验：artifact 规范、unsupported 显式存在（允许为空列表）。"""
    errors: list[str] = []
    if not compiled.artifact:
        errors.append("artifact 为空")
    if compiled.artifact_hash != hashlib.sha256(_canonical(compiled.artifact)).hexdigest():
        errors.append("artifact_hash 与制品不一致")
    if compiled.enforcement_mode not in ("audit_only", "warn", "block"):
        errors.append("enforcement_mode 非法")
    return ValidationReport(valid=not errors, errors=errors)
