"""DEV09-F: frozen policy compile vectors match live Python compile_policy."""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.openshell.contracts import BackendCapabilities, CapabilityItem, UnsupportedCapability
from app.adapters.openshell.policy_compiler import compile_policy

FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "fixtures"
    / "policy_compile_vectors_v1.json"
)


def _caps(raw: dict) -> BackendCapabilities:
    items = {
        k: CapabilityItem(status=v["status"], semantics=v["semantics"], basis=v["basis"])
        for k, v in (raw.get("items") or {}).items()
    }
    return BackendCapabilities(
        backend=raw["backend"],
        schema_version=raw["schema_version"],
        dynamic_network_update=raw["dynamic_network_update"],
        provider_credential_injection=raw["provider_credential_injection"],
        capabilities=items,
    )


def test_policy_compile_vectors_match_live_compiler():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert doc["schema"] == "policy_compile_vectors/v1"
    for vec in doc["vectors"]:
        caps = _caps(vec["capabilities"])
        if vec["expect"] == "ok":
            c = compile_policy(vec["desired"], caps)
            assert c.artifact_hash == vec["artifact_hash"], vec["name"]
            assert list(c.unsupported_by_backend) == vec["unsupported"], vec["name"]
            assert c.needs_generation == vec["needs_generation"], vec["name"]
            assert c.enforcement_mode == vec["enforcement_mode"], vec["name"]
        elif vec["expect"] == "reject_unknown_keys":
            try:
                compile_policy(vec["desired"], caps)
                raise AssertionError(f"{vec['name']}: expected reject")
            except UnsupportedCapability as e:
                assert vec["error_contains"] in str(e)
        else:
            raise AssertionError(vec["expect"])
