"""Independent synthetic Edge protocol client against a real production API.

Only test keys and invented assets. This is not the native Edge binary or a
customer identity provider. Canonical signing is implemented from the contract.
"""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

from common import write_json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from edge_governance_scoring import REJECTIONS, evaluate

CASES = {
    "edge_enroll_a": 200, "edge_enroll_b": 200,
    "edge_register_a": 200, "edge_register_b": 200, "edge_enrollment_replay": 401,
    "edge_heartbeat_a": 200, "edge_heartbeat_b": 200,
    "edge_scan_a": 200, "edge_scan_b": 200, "edge_tasks_a": 200, "edge_tasks_b": 200,
    "edge_identity_substitution": 401, "edge_cross_task_read": 404,
    "edge_batch_signature": 401, "edge_evidence_signature": 401,
    "edge_orphan_evidence": 422, "edge_cross_task_batch": 409,
    "edge_assert_effective": 422, "edge_upload_a": 200, "edge_upload_b": 200,
    "edge_identical_replay": 200, "edge_conflicting_replay": 409,
    "edge_candidates_a": 200, "edge_candidates_b": 200,
    "edge_asset_own": 200, "edge_asset_cross": 404, "edge_asset_absent": 404,
    "edge_asset_no_permission": 403, "edge_asset_cross_no_permission": 404,
    "edge_evidence_a": 200, "edge_evidence_b": 200, "edge_evidence_cross": 404,
    "edge_confirm_cross": 404, "edge_confirm_denied": 403,
    "edge_receipt_a": 200, "edge_terminal_batch_replay": 409,
    "edge_revoke_cross": 404, "edge_revoke_audit_failure": 503,
    "edge_status_after_fault": 200, "edge_revoke_a": 200,
    "edge_revoked_tasks": 401, "edge_revoked_batch": 401, "edge_revoked_heartbeat": 401,
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def seal_batch(key, body):
    result = deepcopy(body)
    result.pop("signature", None)
    result["signature"] = key.sign(canonical(result)).hex()
    return result


def run(request, identity, sql, check, fault, events, out, a, b, ea, eb):
    observations = {}
    transport = request
    rejections = {}

    def request(case, *args, **kwargs):
        result = transport(case, *args, **kwargs)
        if case in REJECTIONS:
            rejections[case] = result
        return result

    def record(name, value):
        observations[name] = value
        events.add("edge_observation", name=name, value=value)
        return value

    def state():
        return {"assets": sql("SELECT id,tenant_id,name,status,evidence_ids FROM agent_asset ORDER BY id"),
                "evidence": sql("SELECT id,tenant_id,evidence_id,content_hash FROM evidence ORDER BY id"),
                "permissions": sql("SELECT id,state FROM permission_fact ORDER BY id"),
                "tasks": sql("SELECT id,status,result_digest FROM edge_task ORDER BY id")}

    try:
        devices, keys, headers, tasks, batches = {}, {}, {}, {}, {}
        for side, auth, environment in (("a", a, ea), ("b", b, eb)):
            enrolled = request("edge_enroll_" + side, "POST",
                               f"/api/v1/environments/{environment['id']}/edge-enrollment", auth, {})
            keys[side] = Ed25519PrivateKey.generate()
            pem = keys[side].public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
            body = {"enrollment_code": enrolled["code"], "device_identity": "tp07-edge-" + side,
                    "public_key_pem": pem, "version": "0.1.0", "capabilities": {"connectors": ["hermes"]},
                    "expected_environment_id": environment["id"]}
            devices[side] = request("edge_register_" + side, "POST", "/edge/v1/register", body=body)
            headers[side] = {"Authorization": "Bearer " + devices[side]["device_secret"], "X-Edge-Identity": body["device_identity"]}
            record("registration_" + side, {"environment_id": environment["id"], "device_id": devices[side]["edge_agent_id"],
                   "secret_sha256": hashlib.sha256(devices[side]["device_secret"].encode()).hexdigest(),
                   "stored_hash": sql("SELECT secret_hash FROM edge_agent WHERE id=%s", (devices[side]["edge_agent_id"],)),
                   "edge_public_key_pem": pem, "control_plane_public_key": devices[side]["control_plane_public_key"]})
            if side == "a":
                request("edge_enrollment_replay", "POST", "/edge/v1/register", body={**body, "device_identity": "tp07-replay-device"})
            request("edge_heartbeat_" + side, "POST", "/edge/v1/heartbeat", headers[side], {"version": "0.1.0"})
            tasks[side] = request("edge_scan_" + side, "POST", "/api/v1/scans", auth,
                                  {"environment_id": environment["id"], "connector": "hermes", "scope": {}})["task_id"]
        for side in ("a", "b"):
            record("tasks_" + side, request("edge_tasks_" + side, "GET", "/edge/v1/tasks", headers[side]))
        request("edge_identity_substitution", "GET", "/edge/v1/tasks",
                {**headers["a"], "X-Edge-Identity": "tp07-edge-b"})
        request("edge_cross_task_read", "GET", "/api/v1/scans/" + tasks["a"], b)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for side in ("a", "b"):
            evidence = {"evidence_id": "tp07-shared-evidence", "source_type": "manifest",
                        "source_locator": "profiles/fixture-" + side + "/config.yaml", "observed_at": now, "collected_at": now,
                        "collector_id": "tp07-edge-" + side, "connector_version": "0.1.0", "content_hash": hashlib.sha256(side.encode()).hexdigest(),
                        "redaction_profile": "siq.redaction.v1", "classification": "internal", "signature": ""}
            evidence["signature"] = keys[side].sign(canonical(evidence)).hex()
            candidate = {"candidate_id": "hermes_profile:fixture-" + side, "source_type": "hermes_profile",
                         "source_locator": "hermes_profile://fixture-" + side, "discovered_at": now,
                         "name": "fixture-" + side, "framework": "hermes", "evidence_ids": [evidence["evidence_id"]]}
            batches[side] = seal_batch(keys[side], {"task_id": tasks[side], "candidates": [candidate],
                                                  "evidence": [evidence], "permission_facts": []})
        record("before_invalid", state())
        bad = deepcopy(batches["a"])
        bad["candidates"][0]["name"] = "unsigned modification"
        request("edge_batch_signature", "POST", "/edge/v1/batches", headers["a"], bad)
        bad = deepcopy(batches["a"])
        bad["evidence"][0]["content_hash"] = "f" * 64
        request("edge_evidence_signature", "POST", "/edge/v1/batches", headers["a"], seal_batch(keys["a"], bad))
        request("edge_orphan_evidence", "POST", "/edge/v1/batches", headers["a"],
                seal_batch(keys["a"], {**batches["a"], "candidates": []}))
        request("edge_cross_task_batch", "POST", "/edge/v1/batches", headers["a"],
                seal_batch(keys["a"], {**batches["a"], "task_id": tasks["b"]}))
        permission = {"subject": {"type": "agent_asset", "id": batches["a"]["candidates"][0]["candidate_id"]},
                      "domain": "filesystem", "action": "read", "resource": {"type": "path", "value": "/fixture"},
                      "effect": "allow", "state": "effective", "authority": "edge", "evidence_ids": ["tp07-shared-evidence"]}
        request("edge_assert_effective", "POST", "/edge/v1/batches", headers["a"],
                seal_batch(keys["a"], {**batches["a"], "permission_facts": [permission]}))
        record("after_invalid", state())
        for side in ("a", "b"):
            request("edge_upload_" + side, "POST", "/edge/v1/batches", headers[side], batches[side])
        record("after_upload", state())
        request("edge_identical_replay", "POST", "/edge/v1/batches", headers["a"], batches["a"])
        record("after_retry", state())
        bad = deepcopy(batches["a"])
        bad["candidates"][0]["name"] = "signed conflicting retry"
        request("edge_conflicting_replay", "POST", "/edge/v1/batches", headers["a"], seal_batch(keys["a"], bad))
        record("after_conflicting_retry", state())
        assets = {}
        for side, auth in (("a", a), ("b", b)):
            listed = record("assets_" + side, request("edge_candidates_" + side, "GET", "/api/v1/candidates", auth))
            assets[side] = next(asset for asset in listed if asset["name"] == "fixture-" + side)
            record("evidence_" + side, request("edge_evidence_" + side, "GET", f"/api/v1/agents/{assets[side]['id']}/evidence", auth))
        path = f"/api/v1/agents/{assets['a']['id']}"
        for name, route, auth in (("edge_asset_own", path, a), ("edge_asset_cross", path, b),
                                  ("edge_asset_absent", "/api/v1/agents/agt_absent", b),
                                  ("edge_asset_no_permission", path, identity()),
                                  ("edge_asset_cross_no_permission", path, identity("tp07-b")),
                                  ("edge_evidence_cross", path + "/evidence", b)):
            request(name, "GET", route, auth)
        record("before_denied_confirm", state())
        for name, auth in (("edge_confirm_cross", b), ("edge_confirm_denied", identity())):
            request(name, "POST", f"/api/v1/candidates/{assets['a']['id']}/confirm", auth, {})
        record("after_denied_confirm", state())
        request("edge_receipt_a", "POST", f"/edge/v1/tasks/{tasks['a']}/receipt", headers["a"],
                {"status": "success", "task_id": tasks["a"], "device_identity": "tp07-edge-a", "candidate_count": 1,
                 "evidence_count": 1, "evidence_ids": ["tp07-shared-evidence"]})
        record("after_receipt", state())
        request("edge_terminal_batch_replay", "POST", "/edge/v1/batches", headers["a"], batches["a"])
        record("after_terminal_replay", state())
        device_id = devices["a"]["edge_agent_id"]
        revoke_path = f"/api/v1/environments/{ea['id']}/devices/{device_id}"
        revoke_body = {"schema_version": "enterprise-device-revoke/v1", "confirm_device_id": device_id}

        def revocation():
            return {"revoked": sql("SELECT revoked_at IS NOT NULL FROM edge_agent WHERE id=%s", (device_id,)),
                    "audit": sql("SELECT action,actor_id FROM audit_event WHERE resource_id=%s ORDER BY id", (device_id,)),
                    "outbox": sql("SELECT event_type,payload FROM outbox_event WHERE payload->>'resource_ref'=%s ORDER BY id", (device_id,))}

        request("edge_revoke_cross", "POST", revoke_path + "/revoke", b, revoke_body)
        record("before_revoke_fault", revocation())
        fault(True)
        try:
            request("edge_revoke_audit_failure", "POST", revoke_path + "/revoke", a, revoke_body)
        finally:
            fault(False)
        record("after_revoke_fault", revocation())
        request("edge_status_after_fault", "GET", revoke_path + "/credential-status", a)
        request("edge_revoke_a", "POST", revoke_path + "/revoke", a, revoke_body)
        record("after_revoke", revocation())
        record("before_revoked_calls", state())
        request("edge_revoked_tasks", "GET", "/edge/v1/tasks", headers["a"])
        request("edge_revoked_batch", "POST", "/edge/v1/batches", headers["a"], batches["a"])
        request("edge_revoked_heartbeat", "POST", "/edge/v1/heartbeat", headers["a"], {"version": "0.1.0"})
        record("after_revoked_calls", state())
        # Preserve only public signing inputs; no private key or credential.
        record("valid_batches", batches)
        record("rejections", rejections)
        results = evaluate(observations)
        for name, value in results.items():
            check(name, value, {"source": "edge-observations.json", "predicate": name})
    finally:
        write_json(out / "edge-observations.json", observations)
