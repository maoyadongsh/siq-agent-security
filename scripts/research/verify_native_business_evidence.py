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
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def native_grant_digest(grant: dict) -> str:
    # skillcontext.GrantDigest unmarshals into map[string]any, whose numbers
    # are float64. This differs from the integer-preserving signing payload.
    generic = json.loads(canonical(grant), parse_int=float)
    return hashlib.sha256(canonical(generic)).hexdigest()


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
        for name in ("receipt.v3.schema.json", "skill-execution-context.v2.schema.json",
                     "skill-execution-context-revocation.v2.schema.json")
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


def verify_context_revocations(raw: bytes, key: Ed25519PublicKey, contexts: dict,
                               count: int, schema: Draft202012Validator) -> None:
    """Bind immutable revocations to the already verified historical contexts."""
    tombstones = json.loads(raw)
    require(type(count) is int and count > 0 and isinstance(tombstones, dict)
            and len(tombstones) == count, "context_revocation_count_mismatch")
    for context_id, tombstone in tombstones.items():
        schema.validate(tombstone)
        key.verify(bytes.fromhex(tombstone["signature"]),
                   canonical({k: v for k, v in tombstone.items() if k != "signature"}))
        require(context_id == tombstone["context_id"] and context_id in contexts,
                "context_revocation_identity_mismatch")
        context = contexts[context_id]
        require(tombstone["context_signature"] == context["signature"],
                "context_revocation_signature_binding_mismatch")
        issued = datetime.fromisoformat(context["issued_at"].replace("Z", "+00:00"))
        revoked = datetime.fromisoformat(tombstone["revoked_at"].replace("Z", "+00:00"))
        require(issued.tzinfo is not None and revoked.tzinfo is not None and revoked >= issued,
                "context_revocation_time_invalid")


def verify_live_grants(raw: bytes, key: Ed25519PublicKey, binding: dict, contexts: dict,
                       receipts: dict) -> None:
    snapshots = json.loads(raw)
    require(set(snapshots) == set(binding) == {"skill", "agent"}, "live_grant_inventory_mismatch")
    for role, grant in snapshots.items():
        key.verify(bytes.fromhex(grant["signature"]),
                   canonical({k: v for k, v in grant.items() if k != "signature"}))
        require(grant["grant_id"] == binding[role], "live_grant_identity_mismatch")
        require(grant["status"] in {"approved", "deployed", "effective"}, "live_grant_status_invalid")
    require(binding["skill"] != binding["agent"], "live_grant_roles_not_distinct")
    authorities = {
        role: {"grant_id": binding[role], "grant_digest": native_grant_digest(grant)}
        for role, grant in snapshots.items()
    }
    for context in contexts.values():
        require(context["authority"] == authorities["skill"]
                and context["agent_authority"] == authorities["agent"],
                "live_grant_context_binding_mismatch")
    # Explicit no-Skill calls have no SEC; bind their Agent authority as well.
    for receipt in receipts.values():
        require(receipt["native_invocation"]["agent_authority"] == authorities["agent"],
                "live_grant_receipt_binding_mismatch")


def verify_authority_replacement(raw: bytes, key: Ed25519PublicKey, binding: dict,
                                 contexts: dict, cases: dict, receipts: dict) -> None:
    """Verify historical replacement records; do not infer timing or execution effects."""
    evidence = json.loads(raw)
    require(set(evidence) == {"grants", "old_installation", "new_installation",
                              "removal", "update_result"}, "replacement_inventory_mismatch")
    grants = evidence["grants"]
    require(set(grants) == {"previous_before", "previous_after", "replacement", "agent"},
            "replacement_grant_inventory_mismatch")
    for record in [*grants.values(), *(evidence[k] for k in evidence if k != "grants")]:
        key.verify(bytes.fromhex(record["signature"]),
                   canonical({k: v for k, v in record.items() if k != "signature"}))
    before, after, replacement, agent = (grants[k] for k in
                                        ("previous_before", "previous_after", "replacement", "agent"))
    require(before["grant_id"] == after["grant_id"] == binding["previous_grant_id"]
            and replacement["grant_id"] == binding["replacement_grant_id"]
            and agent["grant_id"] == binding["agent_grant_id"]
            and len({before["grant_id"], replacement["grant_id"], agent["grant_id"]}) == 3,
            "replacement_grant_identity_mismatch")
    require(before["status"] == replacement["status"] == "approved"
            and after["status"] == "revoked" and agent["status"] in {"deployed", "effective"},
            "replacement_grant_status_mismatch")
    require({k: v for k, v in before.items() if k not in {"signature", "status"}}
            == {k: v for k, v in after.items() if k not in {"signature", "status"}},
            "replacement_old_permissions_changed")
    old, new, removal, result = (evidence[k] for k in
                                ("old_installation", "new_installation", "removal", "update_result"))
    require(all(op["schema_version"] == "local-skill-install-operation/v1"
                and op["status"] == "installed_unverified" and op["runtime_verified"] is False
                for op in (old, new))
            and old["install_id"] == binding["old_install_id"]
            and new["install_id"] == binding["new_install_id"]
            and old["install_id"] != new["install_id"], "replacement_installation_mismatch")
    require(removal["schema_version"] == "local-skill-install-removal-result/v1"
            and removal["status"] == "removed" and removal["install_id"] == old["install_id"]
            and removal["grant_id"] == after["grant_id"]
            and removal["grant_signature"] == after["signature"]
            and removal["grant_revoked"] is True and removal["target_absent"] is True
            and removal["retained_install_id"] == "", "replacement_removal_mismatch")
    require(result["schema_version"] == "local-skill-update-result/v1"
            and result["update_id"] == binding["update_id"]
            and result["status"] == "updated_unverified" and result["runtime_verified"] is False
            and result["removal_signature"] == removal["signature"]
            and result["installation_signature"] == new["signature"], "replacement_result_mismatch")
    authorities = {g["grant_id"]: {"grant_id": g["grant_id"], "grant_digest": native_grant_digest(g)}
                   for g in (before, replacement)}
    agent_ref = {"grant_id": agent["grant_id"], "grant_digest": native_grant_digest(agent)}
    installs = {before["grant_id"]: old, replacement["grant_id"]: new}
    represented = set()
    for context in contexts.values():
        grant_id = context["authority"]["grant_id"]
        require(grant_id in authorities and context["authority"] == authorities[grant_id]
                and context["agent_authority"] == agent_ref, "replacement_context_grant_mismatch")
        require(context["install"] == {"install_id": installs[grant_id]["install_id"],
                                        "claim_signature": installs[grant_id]["claim_signature"]},
                "replacement_context_install_mismatch")
        represented.add(grant_id)
    require(represented == set(authorities), "replacement_context_inventory_mismatch")
    for row in receipts.values():
        require(row["native_invocation"]["agent_authority"] == agent_ref,
                "replacement_agent_receipt_mismatch")
    case_grants = set()
    for case in cases.values():
        refs = receipts[case["receipt_hash"]]["native_invocation"]["contexts"]
        require(len(refs) == 1, "replacement_case_context_mismatch")
        case_grants.add(refs[0]["authority"]["grant_id"])
    require(case_grants == set(authorities), "replacement_case_authority_mismatch")


def verify_grant_inventory(raw: bytes, key: Ed25519PublicKey, binding: dict,
                           contexts: dict, receipts: dict) -> int:
    """Bind a finite set of historical Skill authorities to one Agent baseline."""
    inventory = json.loads(raw)
    require(set(inventory) == {"agent", "skills"} and set(binding) == {"agent", "skills"}
            and isinstance(binding["skills"], list) and bool(binding["skills"])
            and len(set(binding["skills"])) == len(binding["skills"])
            and set(inventory["skills"]) == set(binding["skills"]), "grant_inventory_mismatch")
    agent, skills = inventory["agent"], inventory["skills"]
    for record in [agent, *skills.values()]:
        key.verify(bytes.fromhex(record["signature"]),
                   canonical({k: v for k, v in record.items() if k != "signature"}))
    require(agent["grant_id"] == binding["agent"] and agent["grant_id"] not in skills
            and agent["status"] in {"deployed", "effective"}, "grant_inventory_agent_invalid")
    for grant_id, grant in skills.items():
        require(grant["grant_id"] == grant_id
                and grant["status"] in {"approved", "deployed", "effective"},
                "grant_inventory_skill_invalid")
    agent_ref = {"grant_id": agent["grant_id"], "grant_digest": native_grant_digest(agent)}
    referenced = set()
    for context in contexts.values():
        grant_id = context["authority"]["grant_id"]
        require(grant_id in skills and context["authority"] == {
            "grant_id": grant_id, "grant_digest": native_grant_digest(skills[grant_id]),
        } and context["agent_authority"] == agent_ref, "grant_inventory_context_mismatch")
        referenced.add(grant_id)
    require(referenced == set(skills), "grant_inventory_unused_skill")
    for row in receipts.values():
        require(row["native_invocation"]["agent_authority"] == agent_ref,
                "grant_inventory_receipt_mismatch")
    return 1 + len(skills)


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
    revocation_result = {}
    if "context_revocations" in payloads or "context_revocation_count" in verification:
        require("context_revocations" in payloads and "context_revocation_count" in verification,
                "context_revocation_binding_missing")
        count = verification["context_revocation_count"]
        verify_context_revocations(payloads["context_revocations"], key, contexts, count,
                                   schemas["skill-execution-context-revocation.v2.schema.json"])
        revocation_result = {"signed_context_revocations": count,
                             "post_revocation_execution_reobserved": False}
    live_grant_result = {}
    if "live_grants" in payloads or "live_grant_ids" in verification:
        require("live_grants" in payloads and "live_grant_ids" in verification,
                "live_grant_binding_missing")
        verify_live_grants(payloads["live_grants"], key, verification["live_grant_ids"], contexts,
                           by_hash)
        live_grant_result = {"signed_live_grants": 2}
    replacement_result = {}
    if "authority_replacement" in payloads or "authority_replacement" in verification:
        require("authority_replacement" in payloads and "authority_replacement" in verification,
                "replacement_binding_missing")
        verify_authority_replacement(payloads["authority_replacement"], key,
                                     verification["authority_replacement"], contexts,
                                     verification["cases"], by_hash)
        replacement_result = {"signed_replacement_grants": 4, "signed_installation_records": 4,
                              "replacement_execution_effects_reobserved": False}
    inventory_result = {}
    if "grant_inventory" in payloads or "grant_inventory_ids" in verification:
        require("grant_inventory" in payloads and "grant_inventory_ids" in verification,
                "grant_inventory_binding_missing")
        count = verify_grant_inventory(payloads["grant_inventory"], key,
                                       verification["grant_inventory_ids"], contexts, by_hash)
        inventory_result = {"signed_inventory_grants": count}
    return {
        "cryptographic_bundle_verified": True,
        "receipts": len(rows),
        "signed_contexts": len(contexts),
        "case_decision_bindings": len(verification["cases"]),
        "original_filesystem_effects_reobserved": False,
        "current_execution_authorized": False,
        **grant_result,
        **revocation_result,
        **live_grant_result,
        **replacement_result,
        **inventory_result,
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
