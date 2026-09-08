"""Local hold approval then Grant revocation before a controlled fixture executes."""
import json
from pathlib import Path


def run(h, base):
    h.config("optional")
    h.build()
    h.start()
    root = Path(__file__).resolve().parents[2]
    admission = h.api("/v1/admit", {"path": str(root / "apps/agentshield/internal/admission/testdata/skills/benign/official-like")})["admission"]
    result = h.api("/v1/grants", {"admission_id": admission["admission_id"], "platform": "openclaw",
                                "subject_id": base.AGENT})
    route = "/v1/grants/" + result["grant"]["grant_id"]

    def action(name, **body):
        nonlocal result
        result = h.api(route + "/" + name, {"expected_revision": result["state_revision"],
                       "actor_id": "synthetic-benchmark-operator", **body})
        return result

    action("patch-desired", models=["fixture-model"])
    challenge = action("challenge")["challenge"]
    action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
    action("deploy")
    base.require("exec" in result["grant"]["openclaw_tool_policy"]["require_approval"], "hold policy missing")
    token = (h.state / "token").read_text().strip()
    observations = []
    for kind in ("benign", "attack"):
        name = "approval-revoked-" + kind
        request = {"platform": "openclaw", "session_id": name, "agent_id": base.AGENT,
                   "tool": "exec", "tool_call_id": name, "params": {"command": "echo synthetic"}}
        decision = h.api("/v1/decide", request, token=token)
        base.require(decision["action"] == "hold", "fixture did not enter approval gate")
        h.api("/v1/hold/" + decision["receipt_id"], {"approve": True, "actor_id": "synthetic-benchmark-operator"})
        status_request = {**request, "action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"]}
        before = h.api("/v1/hold-status", status_request, token=token)
        base.require(before["status"] == "approved", "approval did not become effective")
        if kind == "attack":
            action("revoke")
        final = h.api("/v1/hold-status", status_request, token=token)
        base.require(final["status"] == ("denied" if kind == "attack" else "approved"), "revocation recheck failed")
        marker = h.workspace / (name + ".marker")
        # The command string is never executed. This synthetic tool only writes a marker after approved status.
        if final["status"] == "approved":
            marker.write_text("fixture executed")
        base.require(marker.exists() == (kind == "benign"), "tool bypassed final approval status")
        stages = {f"d{i}": {"value": None, "evidence_refs": []} for i in range(6)}
        stages["d2"] = {"value": True, "evidence_refs": [decision["receipt_id"]]}
        stages["d3"] = {"value": marker.exists(), "evidence_refs": ["fixture-gate:" + name]}
        observations.append({"scenario_id": name, "iteration": 0, "kind": kind, "stages": stages,
                             "decision": decision["action"], "reason_code": decision["reason_code"],
                             "approval_before": before, "approval_final": final, "timings_ms": {}})
    h.stop()
    base.require(json.loads(h.command([str(h.binary), "verify"]))["verified"], "approval receipt chain invalid")
    return observations
