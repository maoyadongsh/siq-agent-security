"""Verify a published native business receipt/context bundle without runtime access.

This verifies historical cryptographic bindings. It does not observe the original
machine, authorize execution, or independently establish filesystem effects.
Dependencies: cryptography and jsonschema from apps/control-api's locked environment.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def artifact(directory: Path, description: dict) -> bytes:
    name = description["file"]
    require(isinstance(name, str) and Path(name).name == name, "artifact_name_invalid")
    raw = (directory / name).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == description["sha256"], "artifact_digest_mismatch")
    return raw


def validators(contracts: Path) -> dict:
    schemas = {}
    registry = Registry()
    for path in contracts.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            continue
        schemas[path.name] = schema
        if "$id" in schema:
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return {
        name: Draft202012Validator(schemas[name], registry=registry)
        for name in ("receipt.v3.schema.json", "skill-execution-context.v2.schema.json")
    }


def verify_grant_transition(raw: bytes, key: Ed25519PublicKey, binding: dict,
                            cases: dict, receipts: dict) -> None:
    """Verify signed states and identities, not the original transition timing."""
    snapshots = json.loads(raw)
    require(set(snapshots) == {"skill_before", "skill_after", "agent_baseline"},
            "grant_snapshot_inventory_mismatch")
    for grant in snapshots.values():
        key.verify(bytes.fromhex(grant["signature"]),
                   canonical({k: v for k, v in grant.items() if k != "signature"}))
    before, after, agent = (snapshots[name] for name in
                            ("skill_before", "skill_after", "agent_baseline"))
    require(before["grant_id"] == after["grant_id"] == binding["skill_grant_id"]
            and agent["grant_id"] == binding["agent_grant_id"]
            and agent["grant_id"] != before["grant_id"], "grant_transition_identity_mismatch")
    require(before["status"] == "approved" and after["status"] == "revoked"
            and agent["status"] in {"approved", "deployed", "effective"},
            "grant_transition_status_mismatch")
    require({k: v for k, v in before.items() if k not in {"signature", "status"}}
            == {k: v for k, v in after.items() if k not in {"signature", "status"}},
            "grant_transition_permissions_changed")
    for case in cases.values():
        invocation = receipts[case["receipt_hash"]]["native_invocation"]
        require(invocation["agent_authority"]["grant_id"] == agent["grant_id"]
                and len(invocation["contexts"]) == 1
                and invocation["contexts"][0]["authority"]["grant_id"] == before["grant_id"],
                "grant_transition_case_binding_mismatch")


def verify(report: Path, contracts: Path) -> dict:
    document = json.loads(report.read_text())
    require(document["schema_version"] in {
        "optimization-native-working-repetitions/v1", "optimization-native-business-evidence/v1",
    }, "schema_unsupported")
    verification = document["verification"]
    payloads = {name: artifact(report.parent, entry) for name, entry in document["artifacts"].items()}
    raw = payloads["receipts"]
    contexts = json.loads(payloads["contexts"])
    key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(verification["receipts"]["public_key_base64"], validate=True)
    )
    schemas = validators(contracts)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    require(len(rows) == verification["receipts"]["count"] and bool(rows), "receipt_count_mismatch")
    previous = "0" * 64
    referenced = set()
    by_hash = {}
    for sequence, row in enumerate(rows):
        schemas["receipt.v3.schema.json"].validate(row)
        body = {k: v for k, v in row.items() if k not in ("hash", "sig")}
        digest = hashlib.sha256(canonical(body)).hexdigest()
        require(row["seq"] == sequence and row["prev_hash"] == previous, "receipt_chain_mismatch")
        require(row["hash"] == digest, "receipt_content_mismatch")
        key.verify(bytes.fromhex(row["sig"]), digest.encode("ascii"))
        previous = digest
        by_hash[digest] = row
        invocation = row["native_invocation"]
        invocation_ids = {ref["context_id"] for ref in invocation["contexts"]}
        require(len(invocation_ids) == len(invocation["contexts"]), "duplicate_invocation_context")
        for reference in invocation["contexts"]:
            context = contexts[reference["context_id"]]
            schemas["skill-execution-context.v2.schema.json"].validate(context)
            key.verify(
                bytes.fromhex(context["signature"]),
                canonical({k: v for k, v in context.items() if k != "signature"}),
            )
            require(context["context_id"] == reference["context_id"], "context_id_mismatch")
            require(context["signature"] == reference["context_signature"], "context_signature_mismatch")
            require(context["authority"] == reference["authority"], "skill_authority_mismatch")
            require(context["agent_authority"] == invocation["agent_authority"], "agent_authority_mismatch")
            for subject, receipt in (("session_id", "session_id"), ("task_id", "runtime_task_id"),
                                     ("agent_id", "agent_id"), ("platform", "platform")):
                require(context["subject"][subject] == row[receipt], "context_subject_mismatch")
            # Receipt timestamps have second precision; do not claim subsecond ordering.
            require(context["issued_at"][:19] <= row["issued_at"][:19] < context["expires_at"][:19],
                    "context_lifetime_mismatch")
            require(context["loader"]["runtime_artifact_sha256"] == document["build"]["artifact_sha256"],
                    "runtime_artifact_mismatch")
            ancestor = context
            ancestry = {context["context_id"]}
            while ancestor.get("parent"):
                parent = ancestor["parent"]
                require(parent["context_id"] in invocation_ids, "parent_context_missing")
                require(parent["context_id"] not in ancestry, "context_ancestry_cycle")
                ancestry.add(parent["context_id"])
                ancestor = contexts[parent["context_id"]]
                require(ancestor["signature"] == parent["signature"], "parent_signature_mismatch")
                require(ancestor["subject"] == context["subject"], "parent_subject_mismatch")
                require(ancestor["agent_authority"] == context["agent_authority"], "parent_agent_mismatch")
            referenced.add(context["context_id"])
    require(previous == verification["receipts"]["head_hash"], "receipt_head_mismatch")
    require(referenced == set(contexts) and len(contexts) == verification["signed_context_count"],
            "context_inventory_mismatch")
    cases = list(verification["cases"].values())
    require(len({case["receipt_hash"] for case in cases}) == len(cases), "duplicate_case_receipt")
    require(len({case["request_run_sha256"] for case in cases}) == len(cases), "duplicate_case_request")
    for case in cases:
        row = by_hash[case["receipt_hash"]]
        require(row["tool"] == case["tool"] and row["effective_action"] == case["effective_action"],
                "case_decision_mismatch")
        require(row["reason_code"] == case["reason_code"], "case_reason_mismatch")
        require(row["resource_refs"] == [{"domain": "filesystem", "digest": case["resource_digest"]}],
                "case_resource_mismatch")
        runs = set(re.findall(r"qwen-request-[a-f0-9]+", row["session_id"]))
        require(len(runs) == 1 and hashlib.sha256(next(iter(runs)).encode()).hexdigest()
                == case["request_run_sha256"], "case_request_mismatch")
    grant_result = {}
    if "grant_snapshots" in payloads or "grant_transition" in verification:
        require("grant_snapshots" in payloads and "grant_transition" in verification,
                "grant_transition_binding_missing")
        verify_grant_transition(payloads["grant_snapshots"], key, verification["grant_transition"],
                                verification["cases"], by_hash)
        grant_result = {"signed_grant_snapshots": 3, "grant_transition_order_reobserved": False}
    return {
        "cryptographic_bundle_verified": True,
        "receipts": len(rows),
        "signed_contexts": len(contexts),
        "case_decision_bindings": len(verification["cases"]),
        "original_filesystem_effects_reobserved": False,
        "current_execution_authorized": False,
        **grant_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--contracts", type=Path,
                        default=Path(__file__).resolve().parents[2] / "packages/contracts")
    args = parser.parse_args()
    print(json.dumps(verify(args.report, args.contracts), sort_keys=True))


if __name__ == "__main__":
    main()
