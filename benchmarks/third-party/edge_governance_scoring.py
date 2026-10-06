"""Pure assertions over independently captured SQL state and public signatures."""
import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ASSERTIONS = ["edge_secret_hash_only", "edge_task_scope_signatures", "edge_batch_signature_inputs",
              "edge_invalid_batches_atomic", "edge_actual_upload_material", "edge_retry_idempotent",
              "edge_conflict_atomic", "edge_tenant_evidence_distinct", "edge_confirm_atomic",
              "edge_terminal_replay_atomic", "edge_revocation_fault_atomic", "edge_revocation_audit_outbox",
              "edge_revoked_calls_atomic", "edge_asset_list_isolation", "edge_evidence_read_isolation", "edge_rejection_reasons"]

REJECTIONS = {"edge_enrollment_replay": "enrollment_invalid", "edge_identity_substitution": "edge_untrusted",
              "edge_batch_signature": "batch_signature_invalid", "edge_evidence_signature": "evidence_signature_invalid",
              "edge_orphan_evidence": "orphan_evidence:", "edge_cross_task_batch": "batch_task_binding_invalid",
              "edge_assert_effective": "edge_cannot_assert_effective", "edge_conflicting_replay": "batch_task_replay_conflict",
              "edge_terminal_batch_replay": "batch_task_binding_invalid", "edge_revoke_audit_failure": "device_revocation_unavailable",
              "edge_revoked_tasks": "edge_untrusted", "edge_revoked_batch": "edge_untrusted", "edge_revoked_heartbeat": "edge_untrusted"}


def evaluate(o):
    result = {}
    result["edge_secret_hash_only"] = all(o["registration_" + s]["stored_hash"] == [[o["registration_" + s]["secret_sha256"]]] for s in ("a", "b"))
    signature_checks = []
    batch_checks = []
    for side in ("a", "b"):
        registration = o["registration_" + side]
        tasks = o["tasks_" + side]
        okay = len(tasks) == 1 and tasks[0]["environment_id"] == registration["environment_id"]
        for task in tasks:
            envelope = {"task_id": task["id"], **{k: task[k] for k in ("task_type", "environment_id", "payload", "expires_at")}}
            try:
                Ed25519PublicKey.from_public_bytes(base64.b64decode(registration["control_plane_public_key"], validate=True)).verify(
                    base64.b64decode(task["signature"], validate=True), json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode())
            except (InvalidSignature, ValueError, TypeError):
                okay = False
        signature_checks.append(okay)
        batch = o["valid_batches"][side]
        key = serialization.load_pem_public_key(registration["edge_public_key_pem"].encode())
        okay = isinstance(key, Ed25519PublicKey)
        try:
            key.verify(bytes.fromhex(batch["signature"]), json.dumps({k: v for k, v in batch.items() if k != "signature"},
                       ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
            for evidence in batch["evidence"]:
                key.verify(bytes.fromhex(evidence["signature"]), json.dumps({**evidence, "signature": ""},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        except (InvalidSignature, ValueError, TypeError):
            okay = False
        batch_checks.append(okay)
    result["edge_task_scope_signatures"] = all(signature_checks)
    result["edge_batch_signature_inputs"] = all(batch_checks)
    result["edge_invalid_batches_atomic"] = o["before_invalid"] == o["after_invalid"]
    state = o["after_upload"]
    result["edge_actual_upload_material"] = len(state["assets"]) == len(state["evidence"]) == 2 and not state["permissions"] and all(
        row[1] == "uploaded" and isinstance(row[2], str) and len(row[2]) == 64 for row in state["tasks"])
    result["edge_retry_idempotent"] = state == o["after_retry"]
    result["edge_conflict_atomic"] = o["after_retry"] == o["after_conflicting_retry"]
    result["edge_tenant_evidence_distinct"] = sorted(row[1] for row in state["evidence"]) == ["tp07-a", "tp07-b"] and len({
        row[0] for row in state["evidence"]}) == 2 and {row[2] for row in state["evidence"]} == {"tp07-shared-evidence"}
    result["edge_confirm_atomic"] = o["before_denied_confirm"] == o["after_denied_confirm"]
    result["edge_terminal_replay_atomic"] = o["after_receipt"] == o["after_terminal_replay"] and sum(
        row[1] == "delivered" for row in o["after_receipt"]["tasks"]) == 1
    result["edge_revocation_fault_atomic"] = o["before_revoke_fault"] == o["after_revoke_fault"] and o["after_revoke_fault"]["revoked"] == [[False]]
    revoked = o["after_revoke"]
    result["edge_revocation_audit_outbox"] = revoked["revoked"] == [[True]] and ["edge.device.revoke", "operator-a"] in revoked["audit"] and sum(
        row[0] == "edge.device.revoked.v1" for row in revoked["outbox"]) == 1
    result["edge_revoked_calls_atomic"] = o["before_revoked_calls"] == o["after_revoked_calls"]
    result["edge_asset_list_isolation"] = all(len(o["assets_" + s]) == 1 and o["assets_" + s][0]["name"] == "fixture-" + s for s in ("a", "b"))
    result["edge_evidence_read_isolation"] = all(len(o["evidence_" + s]) == 1 and o["evidence_" + s][0]["id"] == "tp07-shared-evidence"
        and o["evidence_" + s][0]["source_locator"] == "profiles/fixture-" + s + "/config.yaml" for s in ("a", "b")) and (
        o["evidence_a"][0]["observation_id"] != o["evidence_b"][0]["observation_id"])
    result["edge_rejection_reasons"] = set(o["rejections"]) == set(REJECTIONS) and all(
        isinstance(o["rejections"][name].get("detail"), str) and (o["rejections"][name]["detail"].startswith(expected)
        if name == "edge_orphan_evidence" else o["rejections"][name]["detail"] == expected) for name, expected in REJECTIONS.items())
    if set(result) != set(ASSERTIONS):
        raise ValueError("edge predicate allocation differs")
    return result
