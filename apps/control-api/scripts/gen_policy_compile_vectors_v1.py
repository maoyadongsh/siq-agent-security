#!/usr/bin/env python3
"""Produce packages/contracts/fixtures/policy_compile_vectors_v1.json (DEV09-F).

Python compile_policy is the producer; Go CompilePolicy is the consumer under
test. Re-run only when intentionally refreshing frozen vectors.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.adapters.openshell.contracts import BackendCapabilities, CapabilityItem, UnsupportedCapability
from app.adapters.openshell.policy_compiler import compile_policy

OUT = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "fixtures" / "policy_compile_vectors_v1.json"


def caps(**kwargs) -> BackendCapabilities:
    items = kwargs.pop("capabilities", {})
    base = dict(
        backend="openshell",
        schema_version="siq.openshell.policy.v1",
        dynamic_network_update=False,
        provider_credential_injection=False,
        capabilities={k: CapabilityItem(**v) if isinstance(v, dict) else v for k, v in items.items()},
    )
    base.update(kwargs)
    return BackendCapabilities(**base)


def ok_vector(name: str, desired: dict, capabilities: BackendCapabilities) -> dict:
    c = compile_policy(desired, capabilities)
    return {
        "name": name,
        "expect": "ok",
        "desired": desired,
        "capabilities": {
            "backend": capabilities.backend,
            "schema_version": capabilities.schema_version,
            "dynamic_network_update": capabilities.dynamic_network_update,
            "provider_credential_injection": capabilities.provider_credential_injection,
            "items": {
                k: {"status": v.status, "semantics": v.semantics, "basis": v.basis}
                for k, v in capabilities.capabilities.items()
            },
        },
        "artifact_hash": c.artifact_hash,
        "unsupported": list(c.unsupported_by_backend),
        "needs_generation": c.needs_generation,
        "enforcement_mode": c.enforcement_mode,
        "artifact": c.artifact,
    }


def err_vector(name: str, desired: dict, capabilities: BackendCapabilities, err_substr: str) -> dict:
    try:
        compile_policy(desired, capabilities)
        raise SystemExit(f"{name}: expected UnsupportedCapability")
    except UnsupportedCapability as e:
        msg = str(e)
        if err_substr not in msg:
            raise SystemExit(f"{name}: unexpected error {msg!r}")
        return {
            "name": name,
            "expect": "reject_unknown_keys",
            "desired": desired,
            "capabilities": {
                "backend": capabilities.backend,
                "schema_version": capabilities.schema_version,
                "dynamic_network_update": capabilities.dynamic_network_update,
                "provider_credential_injection": capabilities.provider_credential_injection,
                "items": {},
            },
            "error_contains": err_substr,
        }


def main() -> None:
    block_ok = caps(
        dynamic_network_update=True,
        capabilities={
            "enforcement_mode.block": {"status": "supported", "semantics": "enforce", "basis": "test"},
            "model_routing": {"status": "unknown", "semantics": "none", "basis": "not probed"},
            "tools_mcp": {"status": "unsupported", "semantics": "none", "basis": "cli"},
        },
    )
    vectors = [
        ok_vector(
            "parity_full_domains",
            {
                "policy_id": "pol-grt-1",
                "selector": {"agent_ids": ["inst_1"]},
                "version": 1,
                "status": "validated",
                "enforcement_mode": "block",
                "filesystem": {
                    "read_only": ["/skills/github-triage"],
                    "read_write": ["~/work/out"],
                },
                "network": [
                    {"endpoint": "api.github.com:443", "effect": "allow"},
                    {"endpoint": "astral.sh:443", "effect": "allow"},
                ],
                "process": {"forbid_privilege_escalation": True},
                "model_routing": {"allowed_models": ["nemotron-local"]},
                "tools": ["terminal", "read_file", "web_extract"],
            },
            block_ok,
        ),
        ok_vector(
            "minimal_audit_only_default_mode",
            {"policy_id": "pol-min"},
            caps(
                capabilities={
                    "enforcement_mode.audit_only": {
                        "status": "supported",
                        "semantics": "observe",
                        "basis": "t",
                    }
                }
            ),
        ),
        ok_vector(
            "network_static_when_no_dynamic",
            {
                "policy_id": "pol-net",
                "network": [{"endpoint": "a:443", "effect": "allow"}],
                "enforcement_mode": "audit_only",
            },
            caps(
                capabilities={
                    "enforcement_mode.audit_only": {
                        "status": "supported",
                        "semantics": "observe",
                        "basis": "t",
                    }
                }
            ),
        ),
        ok_vector(
            "field_matrix_unsupported_bucket",
            {
                "policy_id": "pol-fields",
                "enforcement_mode": "audit_only",
                "tools": ["x"],
                "tool_policies": {"x": {}},
                "data_scope_refs": ["s1"],
                "resources": ["r1"],
                "audit": {"level": "full"},
                "exceptions": [{"id": "e1"}],
                "secrets": [{"ref": "vault://a"}],
            },
            caps(
                capabilities={
                    "enforcement_mode.audit_only": {
                        "status": "supported",
                        "semantics": "observe",
                        "basis": "t",
                    },
                    "tools_mcp": {"status": "unsupported", "semantics": "none", "basis": "cli"},
                    "resources": {"status": "unknown", "semantics": "none", "basis": "n/a"},
                    "audit_events": {"status": "unsupported", "semantics": "none", "basis": "none"},
                    "secrets": {"status": "unsupported", "semantics": "none", "basis": "provider"},
                }
            ),
        ),
        err_vector(
            "unknown_key_bogus",
            {"policy_id": "p", "bogus": 1},
            caps(),
            "未知策略字段",
        ),
        err_vector(
            "unknown_key_typo_filesystem",
            {"policy_id": "p", "file_system": {}},
            caps(),
            "未知策略字段",
        ),
    ]

    # Freeze known key allowlist in the fixture for consumer cross-check.
    known_keys = sorted(
        {
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
    )
    out = {
        "schema": "policy_compile_vectors/v1",
        "producer": "apps/control-api/app/adapters/openshell/policy_compiler.compile_policy",
        "contract": "Go grant.CompilePolicy must match artifact_hash / unsupported / needs_generation; unknown keys refuse.",
        "known_keys": known_keys,
        "vectors": vectors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} vectors={len(vectors)}")


if __name__ == "__main__":
    main()
