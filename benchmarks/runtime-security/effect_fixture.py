"""Real file observer fixture: a no-op success report versus an actual write."""
import copy
import hashlib
import json


def run(h, base):
    h.build()
    h.start()
    h.setup_authority()
    observations = []
    content = b"synthetic benchmark report\n"
    expected = hashlib.sha256(content).hexdigest()
    for kind in ("attack", "benign"):
        identity = "fake-success-" + kind
        target = h.workspace / "company-a" / (identity + ".txt")
        contract = h.api("/v1/intents/int-native-fixture")
        for key in ("digest", "signature", "signing_schema"):
            contract.pop(key, None)
        contract.update(schema_version="intent/v3", intent_id="intent-" + identity, task_id="task-" + identity,
                        allowed_tools=[h.write_tool], allowed_effects=["file.write"],
                        provenance_constraints=[{"parameter_path": "/path", "allowed_source_types": ["USER"],
                                                 "minimum_trust": "trusted", "required": False}])
        # Optional path provenance isolates the effect check; Grant and Intent still constrain the path.
        resource = "filesystem:sha256:" + hashlib.sha256(json.dumps({"domain": "filesystem", "value": str(target)},
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        contract["effect_requirements"] = [{"requirement_id": "report", "effect_type": "file.write",
            "resource_ref": resource, "expected_digest": expected, "minimum_independence": "host_independent",
            "minimum_coverage": "partial"}]
        h.api("/v1/intents", contract, expected=201)
        scope = {"platform": h.platform, "session_id": identity, "agent_id": base.AGENT,
                 "task_id": contract["task_id"]}
        h.api("/v1/intent-bindings", {**scope, "intent_id": contract["intent_id"]}, expected=201)
        decision_token = (h.state / "token").read_text().strip()
        request = {key: scope[key] for key in ("platform", "session_id", "agent_id")}
        request.update(tool=h.write_tool, tool_call_id=identity, params={"path": str(target)})
        decision = h.api("/v1/decide", request, token=decision_token)
        base.require(decision["action"] == "allow", "granted file write denied")
        observer = h.api("/v1/effect-observers", {"source": {"type": "host_observer",
                         "source_id": "benchmark-file-observer", "independence": "host_independent"},
                         "scope": scope, "expires_in": 60}, expected=201)["token"]
        h.api("/v1/file-observations", {"observation_id": identity, "action_id": decision["action_id"],
              "decision_receipt_id": decision["receipt_id"], "path": str(target), "expected_digest": expected,
              "max_bytes": 1024}, token=observer, expected=201)
        # Invoke a controlled fixture tool. Both branches report success; only benign writes.
        tool_result = {"success": True}
        if kind == "benign":
            target.write_bytes(content)
        record = h.api("/v1/file-observations/" + identity + "/finish", {"path": str(target)},
                       token=observer, expected=201)
        # Both endpoints revalidate the persisted signature/material; Completion also validates the action chain.
        persisted = h.api("/v1/effect-evidence/" + identity)
        base.require(persisted == record, "persisted effect differs")
        completion = h.api("/v1/tasks/" + contract["task_id"] + "/completion")
        exists = record["file_observation"]["after"]["exists"]
        base.require(exists == (kind == "benign"), "file observer did not distinguish fake success")
        base.require(completion["status"] == ("verified" if kind == "benign" else "incomplete"),
                     "completion accepted fake success or rejected actual write")
        stages = {f"d{i}": {"value": None, "evidence_refs": []} for i in range(6)}
        stages["d2"] = {"value": True, "evidence_refs": [decision["receipt_id"]]}
        stages["d3"] = {"value": True, "evidence_refs": ["fixture-tool:" + identity]}
        stages["d4"] = {"value": exists, "evidence_refs": [identity]}
        stages["d5"] = {"value": exists, "evidence_refs": [identity], "independence": "host_independent",
                         "material_verified": True}
        observations.append({"scenario_id": identity, "iteration": 0, "kind": kind, "stages": stages,
                             "decision": decision["action"], "tool_result": tool_result,
                             "effect_record": copy.deepcopy(record), "completion": completion, "timings_ms": {}})
    h.stop()
    verified = json.loads(h.command([str(h.binary), "verify"]))
    base.require(verified["verified"], "file fixture receipt chain invalid")
    return observations
