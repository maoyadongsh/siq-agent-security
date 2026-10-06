"""Actual production HTTP deployment to an owned mTLS OpenShell runtime."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import yaml
from common import write_json

CASES = {"backend_assets": 200, "backend_enforce": 200, "backend_instance": 201,
         "backend_binding": 201, "backend_policy": 201, "backend_change": 201,
         "backend_approve": 200, "backend_unassigned": 409, "backend_preview": 200,
         "backend_submit": 201, "backend_verify": 200, "backend_rollback": 200,
         "backend_verify_old_receipt": 200, "backend_change_two": 201,
         "backend_approve_two": 200, "backend_preview_two": 200,
         "backend_stale_submit": 409, "backend_unreachable_preview": 502,
         "backend_unreachable_self_report": 200}
ASSERTIONS = ["backend_unassigned_no_effect", "backend_exact_config_readback", "backend_database_effective",
              "backend_verified_receipt", "backend_exact_rollback", "backend_old_receipt_mismatch",
              "backend_stale_preview_no_effect", "backend_unreachable_no_effect"]


def evaluate(o):
    before, applied, rolled = o["before"], o["applied"], o["rolled_back"]
    network = applied["policy"].get("network_policies", {})
    endpoints = [(e["host"], e["port"]) for rule in network.values() for e in rule.get("endpoints", [])]
    static_before = {k: v for k, v in before["policy"].items() if k != "network_policies"}
    static_after = {k: v for k, v in applied["policy"].items() if k != "network_policies"}
    db = o["database_applied"]
    results = {
        "backend_unassigned_no_effect": o["unassigned_response"].get("detail") == "deployment_target_authority_unverified" and o["before_unassigned"] == o["after_unassigned"],
        "backend_exact_config_readback": static_before == static_after and endpoints == [("example.test", 443)] and before["revision"] != applied["revision"],
        # to_revision is the SIQ desired-policy identity, not OpenShell revision.
        # Old four-column cohorts preserve their original (incorrect) predicate.
        "backend_database_effective": (len(db) == 1 and db[0][1] == "effective" and (
            db[0][2] == applied["revision"] and db[0][3].get("level") == "config_readback" if len(db[0]) == 4 else
            db[0][4].get("backend_revision") == applied["revision"] and db[0][3].get("level") == "readback_verified"
            and db[0][3].get("method") == "config_readback")),
        "backend_verified_receipt": o["verified"]["result"] == "verified" and o["verified"]["actual_revision"] == applied["revision"],
        "backend_exact_rollback": rolled["policy"] == before["policy"] and o["rollback"]["status"] == "rolled_back",
        "backend_old_receipt_mismatch": o["old_receipt"]["result"] == "mismatch" and o["old_receipt"]["actual_revision"] == rolled["revision"],
        "backend_stale_preview_no_effect": o["stale_response"].get("detail") == "deployment_preview_changed" and o["before_stale"] == o["after_stale"] and o["drifted"] == o["after_stale_readback"],
        "backend_unreachable_no_effect": o["unreachable_attestation"].get("result") == "unreachable" and o["before_unreachable"] == o["after_unreachable"],
    }
    if set(results) != set(ASSERTIONS):
        raise ValueError("backend assertion allocation differs")
    return results


def run(request, identity, sql, check, events, out, a, ea, fixture, asset_name='fixture-a', effects=False, authority_boundaries=False):
    o = {}

    def record(name, value):
        o[name] = value
        events.add("backend_observation", name=name, value=value)
        return value

    def state():
        # Independent DB oracle; attestation/audit can change during read-only verification.
        return {"deployments": sql("SELECT id,status,to_revision FROM deployment ORDER BY id"),
                "changes": sql("SELECT id,status FROM change_request ORDER BY id")}

    def readback(name):
        response = fixture.cli("policy", "get", fixture.target, "--full")
        if response.returncode:
            raise RuntimeError("independent_readback_failed")
        text = response.stdout.decode()
        match = re.search(r"^Version:\s+(\S+)", text, re.MULTILINE)
        if not match or "---" not in text:
            raise ValueError("unrecognized_independent_readback")
        return record(name, {"revision": match[1], "policy": yaml.safe_load(text.split("---", 1)[1]), "raw_stdout": text})

    try:
        assets = request("backend_assets", "GET", "/api/v1/candidates", a)
        asset = next(x for x in assets if x["name"] == asset_name)
        request("backend_enforce", "PATCH", f"/api/v1/environments/{ea['id']}/mode", a, {"mode": "enforce", "reason": "owned runtime evaluation"})
        instance = request("backend_instance", "POST", f"/api/v1/assets/{asset['id']}/instances", a,
                           {"environment_id": ea["id"], "runtime": "openshell"})
        binding = request("backend_binding", "POST", "/api/v1/runtime-bindings", a,
                          {"agent_instance_id": instance["id"], "environment_id": ea["id"], "backend": "openshell-cli", "backend_target_id": fixture.target})
        policy = request("backend_policy", "POST", "/api/v1/policies", a,
                         {"name": "real-backend-allow", "selector": {"agent_ids": [asset["id"]]}, "enforcement_mode": "block",
                          "network": [{"endpoint": "example.test:443", "effect": "allow", "binary_paths": ["/usr/bin/curl"]}]})
        change = request("backend_change", "POST", "/api/v1/change-requests", a,
                         {"policy_id": policy["id"], "idempotency_key": "backend-change-one"})
        reviewer = identity(actor="backend-reviewer", roles=["reviewer"])
        request("backend_approve", "POST", f"/api/v1/change-requests/{change['id']}/approve", reviewer)
        body = {"change_request_id": change["id"], "environment_id": ea["id"], "binding_id": binding["id"]}
        record("before_unassigned", state())
        record("unassigned_response", request("backend_unassigned", "POST", "/api/v1/deployments", a, body))
        record("after_unassigned", state())
        probe = fixture.product_probe()
        if probe.returncode:
            raise RuntimeError("real_adapter_identity_probe_failed")
        caps = json.loads(probe.stdout)["capabilities"]
        now = datetime.now(timezone.utc)
        authority = {"schema_version": "enterprise-runtime-target-authority/v1", "issued_at": now.isoformat(),
                     "expires_at": (now + timedelta(hours=1)).isoformat(), "assignments": [{"id": "tp07-owned-assignment",
                     "tenant_id": "tp07-a", "environment_id": ea["id"], "asset_id": asset["id"], "agent_instance_id": instance["id"],
                     "backend_target_id": fixture.target, "endpoint_fingerprint": caps["endpoint_fingerprint"],
                     "gateway_name_sha256": hashlib.sha256(caps["handshake_gateway"].encode()).hexdigest()}]}
        write_json(fixture.root / "operator-authority.json", authority)
        record("operator_assignment", authority)
        readback("before")
        if effects:
            record('effect_before', fixture.effect('before'))
        preview = request("backend_preview", "POST", "/api/v1/deployment-preview", a,
                          {**body, "schema_version": "deployment-preview-request/v1"})
        if authority_boundaries:
            from enterprise_authority import before_deploy
            before_deploy(request, sql, record, readback, a, ea, fixture, assets, asset, authority, body, preview)
        deployed = request("backend_submit", "POST", "/api/v1/deployment-preview/submit", a,
                           {**body, "schema_version": "deployment-preview-submit/v1", "preview_digest": preview["preview_digest"]})
        record("deployed", deployed)
        record("database_applied", sql("SELECT id,status,to_revision,verification,receipt FROM deployment WHERE id=%s", (deployed["id"],)))
        readback("applied")
        if effects:
            record('effect_applied', fixture.effect('applied'))
        endpoint = f"/api/v1/deployments/{deployed['id']}"
        record("verified", request("backend_verify", "POST", endpoint + "/receipt-verify", a))
        if authority_boundaries:
            from enterprise_authority import before_rollback
            before_rollback(request, sql, record, readback, a, fixture, authority, endpoint)
        record("rollback", request("backend_rollback", "POST", endpoint + "/rollback", a))
        readback("rolled_back")
        if effects:
            record('effect_rolled_back', fixture.effect('rolled_back'))
        record("old_receipt", request("backend_verify_old_receipt", "POST", endpoint + "/receipt-verify", a))
        second = request("backend_change_two", "POST", "/api/v1/change-requests", a,
                         {"policy_id": policy["id"], "idempotency_key": "backend-change-two"})
        request("backend_approve_two", "POST", f"/api/v1/change-requests/{second['id']}/approve", reviewer)
        body["change_request_id"] = second["id"]
        preview = request("backend_preview_two", "POST", "/api/v1/deployment-preview", a,
                          {**body, "schema_version": "deployment-preview-request/v1"})
        # Explicit controlled external policy drift after preview, using the real CLI.
        path = fixture.root / "external-drift.yaml"
        path.write_text(yaml.safe_dump(o["applied"]["policy"]))
        drift = fixture.cli("policy", "set", fixture.target, "--policy", str(path), "--wait", "--timeout", "20")
        events.add("lab_backend_drift", exit_code=drift.returncode)
        if drift.returncode:
            raise RuntimeError("controlled_policy_drift_failed")
        readback("drifted")
        record("before_stale", state())
        record("stale_response", request("backend_stale_submit", "POST", "/api/v1/deployment-preview/submit", a,
               {**body, "schema_version": "deployment-preview-submit/v1", "preview_digest": preview["preview_digest"]}))
        record("after_stale", state())
        readback("after_stale_readback")
        record("before_unreachable", state())
        fixture.gateway.terminate()
        fixture.gateway.wait(timeout=8)
        events.add("lab_backend_stopped", child_pid=fixture.gateway.pid)
        request("backend_unreachable_preview", "POST", "/api/v1/deployment-preview", a,
                {**body, "schema_version": "deployment-preview-request/v1"})
        record("unreachable_attestation", request("backend_unreachable_self_report", "POST", endpoint + "/receipt-verify", a,
               {"result": "verified", "backend_revision": o["applied"]["revision"]}))
        record("after_unreachable", state())
        for name, value in evaluate(o).items():
            check(name, value, {"source": "backend-observations.json", "predicate": name})
        if effects:
            from enterprise_runtime import evaluate as evaluate_effects
            for name, value in evaluate_effects(o).items():
                check(name, value, {'source': 'backend-observations.json', 'predicate': name})
        if authority_boundaries:
            from enterprise_authority import evaluate as evaluate_authority
            for name, value in evaluate_authority(o).items():
                check(name, value, {'source': 'backend-observations.json', 'predicate': name})
    finally:
        write_json(out / "backend-observations.json", o)
