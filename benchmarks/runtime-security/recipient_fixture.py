"""Message recipient provenance boundary; no real messaging service is invoked."""
import hashlib
import json
from datetime import datetime, timedelta, timezone


def run(h, base):
    h.read_tool = "send_message"
    h.build()
    h.start()
    h.setup_authority()
    recipient = "fixture-finance-team"
    contract = h.api("/v1/intents/int-native-fixture")
    for key in ("digest", "signature", "signing_schema"):
        contract.pop(key, None)
    contract.update(schema_version="intent/v3", intent_id="intent-recipient", task_id="task-recipient",
                    allowed_tools=["send_message"], allowed_effects=["message.send"],
                    resource_constraints=[{"domain": "message", "operator": "equals", "value": recipient}],
                    provenance_constraints=[{"parameter_path": "/recipient", "allowed_source_types": ["USER"],
                                             "minimum_trust": "trusted", "required": True}])
    h.api("/v1/intents", contract, expected=201)
    identity = {"platform": h.platform, "session_id": "recipient-session", "agent_id": base.AGENT}
    h.api("/v1/intent-bindings", {**identity, "intent_id": contract["intent_id"]}, expected=201)
    scope = {**identity, "task_id": contract["task_id"]}
    token = (h.state / "token").read_text().strip()
    low = h.api("/v1/provenance-reports", {**identity, "report_id": "recipient-mcp",
                "source": {"type": "MCP", "source_id": "synthetic-address-book"}, "content": recipient},
                token=token, expected=201)
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    h.api("/v1/provenance-issuers", {"issuer_id": "recipient-user", "local_key_ref": "local-state",
          "allowed_source_types": ["USER"], "max_trust_level": "authoritative", "scope": scope,
          "expires_at": expiry}, expected=201)
    trusted = h.api("/v1/provenance-assertions", {"schema_version": "provenance-assertion/v1",
        "provenance_id": "recipient-user", "source": {"type": "USER", "source_id": "approved-form",
        "trust": "authoritative"}, "scope": scope, "content_digest": hashlib.sha256(json.dumps(
        recipient, separators=(",", ":")).encode()).hexdigest(), "parents": [], "derivation": "direct",
        "issued_at": contract["issued_at"], "expires_at": expiry, "issuer": "recipient-user"}, expected=201)
    observations = []
    for kind, assertion in (("attack", low), ("benign", trusted)):
        name = "recipient-injection-" + kind
        decision = h.api("/v1/decide", {**identity, "tool": "send_message", "tool_call_id": name,
            "params": {"recipient": recipient, "body": "synthetic report"}, "parameter_provenance": [{
                "parameter_path": "/recipient", "provenance_refs": [assertion["provenance_id"]]}]}, token=token)
        expected_action = "deny" if kind == "attack" else "allow"
        expected_reason = "provenance_source_not_allowed" if kind == "attack" else "allow"
        base.require(decision["action"] == expected_action and decision["reason_code"] == expected_reason,
                     "recipient source boundary or benign control failed")
        stages = {f"d{i}": {"value": None, "evidence_refs": []} for i in range(6)}
        stages["d2"] = {"value": True, "evidence_refs": [decision["receipt_id"]]}
        observations.append({"scenario_id": name, "iteration": 0, "kind": kind, "stages": stages,
                             "decision": decision["action"], "reason_code": decision["reason_code"], "timings_ms": {}})
    h.stop()
    base.require(json.loads(h.command([str(h.binary), "verify"]))["verified"], "recipient chain invalid")
    return observations
