"""Desired Policy → OpenShell 策略制品编译（设计文档 §15.2 能力映射）。

铁律（§14.1）：后端不支持的字段必须标记 unsupported 或由其他执行点承担，
编译时不得静默丢失；未知语义拒绝。

P1-1：unsupported 原因从版本化能力文档（BackendCapabilities.capabilities）
派生；能力状态为 unknown 的字段按 fail-closed 处理——视为不可执行，
列入 unsupported 并注明 unknown，绝不当作 supported 放行。
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

# 策略字段 → 能力文档能力项（None = 无对应后端能力项，固定由其他执行点承担）
_FIELD_CAPABILITY = {
    "tools": "tools_mcp",
    "tool_policies": "tools_mcp",
    "data_scope_refs": None,
    "resources": "resources",
    "audit": "audit_events",
    "exceptions": None,
}


def _capability_reason(capabilities: BackendCapabilities, key: str, cap_name: str | None) -> str:
    """从能力文档派生 unsupported 原因；unknown → fail-closed（视为不可执行）。"""
    if cap_name is None:
        return f"{key}: 无对应后端能力项，由其他执行点承担"
    item = capabilities.capability(cap_name)
    if item.status == "unknown":
        return f"{key}: capability {cap_name}=unknown（fail-closed 视为不可执行）: {item.basis}"
    if item.status == "unsupported":
        return f"{key}: capability {cap_name}=unsupported: {item.basis or '由其他执行点承担'}"
    return f"{key}: capability {cap_name}=supported/{item.semantics}，本适配器不执行，由其他执行点承担"


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
        # dynamic_network_update 只在 probe 实测为 True 时置真（默认 False 即
        # fail-closed 静态路径），与能力文档 network_l34 同源自实测结论
        if not capabilities.dynamic_network_update:
            # v0.0.83 现状：编译期固定集合，动态更新为版本依赖项（ADR-005/009）
            unsupported.append("network.dynamic_update")
            artifact["network_policies"] = network  # 落为静态制品，由 generation 路径生效
            needs_generation = True
        else:
            artifact["network_policies"] = network

    if desired_policy.get("model_routing"):
        routing_item = capabilities.capability("model_routing")
        if capabilities.provider_credential_injection and routing_item.status == "supported":
            artifact["inference_routing"] = desired_policy["model_routing"]
        elif routing_item.status == "unknown":
            # fail-closed：能力未知视为不可执行
            unsupported.append(
                f"model_routing.inference_routing: capability unknown（fail-closed）: {routing_item.basis}"
            )
        else:
            unsupported.append(f"model_routing.inference_routing: capability unsupported: {routing_item.basis}")

    if desired_policy.get("secrets"):
        # 凭据只存引用；注入能力由 Provider 侧承担（§15.2），原因从能力文档派生
        secrets_item = capabilities.capability("secrets")
        if secrets_item.status == "unknown":
            unsupported.append(f"secrets.injection: capability unknown（fail-closed）: {secrets_item.basis}")
        else:
            unsupported.append(
                f"secrets.injection: capability {secrets_item.status}: "
                f"{secrets_item.basis or '凭据注入由 Provider 侧承担（§15.2）'}"
            )

    for key, cap_name in _FIELD_CAPABILITY.items():
        if desired_policy.get(key):
            unsupported.append(_capability_reason(capabilities, key, cap_name))

    # P1-11：执行模式同样按能力文档判定；非 supported 模式显式列入 unsupported
    # （unknown 按 fail-closed 视为不可执行），部署路由据此拒绝或显式展示
    mode = desired_policy.get("enforcement_mode", "audit_only")
    mode_item = capabilities.capability(f"enforcement_mode.{mode}")
    if mode_item.status != "supported":
        unsupported.append(f"enforcement_mode.{mode}: capability {mode_item.status}: {mode_item.basis}")

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
        enforcement_mode=mode,
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
