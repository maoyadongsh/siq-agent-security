#!/usr/bin/env python3
"""SIGKILL/restart recovery against a production daemon in private fixture state."""
import argparse
import hashlib
import importlib.util
import json
import signal
import tempfile
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from evidence import capture

ROOT = Path(__file__).resolve().parents[2]


def run(h, base):
    h.build()
    h.start()
    h.setup_authority()
    target = h.workspace / "company-a" / "recovered-report.txt"
    content = b"real process recovery fixture\n"
    digest = hashlib.sha256(content).hexdigest()
    contract = h.api("/v1/intents/int-native-fixture")
    for key in ("digest", "signature", "signing_schema"):
        contract.pop(key, None)
    contract.update(schema_version="intent/v3", intent_id="recovery-intent", task_id="recovery-task",
                    allowed_tools=[h.write_tool], allowed_effects=["file.write"],
                    provenance_constraints=[{"parameter_path": "/path", "allowed_source_types": ["USER"],
                                             "minimum_trust": "trusted", "required": False}])
    resource = "filesystem:sha256:" + hashlib.sha256(json.dumps(
        {"domain": "filesystem", "value": str(target)}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    contract["effect_requirements"] = [{"requirement_id": "report", "effect_type": "file.write",
        "resource_ref": resource, "expected_digest": digest, "minimum_independence": "host_independent",
        "minimum_coverage": "partial"}]
    h.api("/v1/intents", contract, expected=201)
    scope = {"platform": h.platform, "session_id": "recovery-session", "agent_id": base.AGENT,
             "task_id": contract["task_id"]}
    h.api("/v1/intent-bindings", {**scope, "intent_id": contract["intent_id"]}, expected=201)
    decision = h.api("/v1/decide", {"platform": h.platform, "session_id": scope["session_id"],
        "agent_id": base.AGENT, "tool": h.write_tool, "tool_call_id": "recovery-call", "params": {"path": str(target)}},
        token=(h.state / "token").read_text().strip())
    base.require(decision["action"] == "allow", "fixture lacks actual write authority")
    provision = {"source": {"type": "host_observer", "source_id": "recovery-observer",
                           "independence": "host_independent"}, "scope": scope, "expires_in": 180}
    original = h.api("/v1/effect-observers", provision, expected=201)
    bodies = [{"observation_id": identity, "action_id": decision["action_id"],
               "decision_receipt_id": decision["receipt_id"], "path": str(target),
               "expected_digest": digest, "max_bytes": 1024} for identity in ("resume-ok", "resume-revoked")]
    for body in bodies:
        before = h.api("/v1/file-observations", body, token=original["token"], expected=201)
        base.require(before["before"]["exists"] is False, "before snapshot must predate write")
    target.write_bytes(content)
    process = h.proc
    h.stop(kill=True)
    base.require(process.returncode == -signal.SIGKILL, "daemon did not terminate by SIGKILL")
    h.start()
    h.api("/v1/file-observations", bodies[0], token=original["token"], expected=403)
    replacement = h.api("/v1/effect-observers", provision, expected=201)
    recoveries = []
    for body in bodies:
        h.api("/v1/file-observations", body, token=replacement["token"], expected=409)
        recovery = h.api("/v1/file-observation-recoveries", {"observation_id": body["observation_id"],
            "observer_id": replacement["observer_id"],
            "expected_owner": hashlib.sha256(original["token"].encode()).hexdigest()})
        recoveries.append(recovery)
        before = h.api("/v1/file-observations", body, token=replacement["token"])
        base.require(before["before"]["exists"] is False, "restart resampled after actual write")
    record = h.api("/v1/file-observations/resume-ok/finish", {"path": str(target)},
                   token=replacement["token"], expected=201)
    base.require(record["file_observation"]["after"]["digest"] == digest, "actual output missing")
    completion = h.api("/v1/tasks/recovery-task/completion")
    base.require(completion["status"] == "verified", "recovered effect not verified")
    request = urllib.request.Request(h.endpoint + "/v1/effect-observers/" + replacement["observer_id"],
                                    method="DELETE", headers={"Authorization": "Bearer " + h.admin})
    with urllib.request.urlopen(request, timeout=10) as response:
        base.require(response.status == 204, "observer revocation failed")
    process = h.proc
    h.stop(kill=True)
    base.require(process.returncode == -signal.SIGKILL, "second daemon not killed")
    h.start()
    third = h.api("/v1/effect-observers", provision, expected=201)
    h.api("/v1/file-observation-recoveries", {"observation_id": "resume-revoked",
        "observer_id": third["observer_id"],
        "expected_owner": hashlib.sha256(replacement["token"].encode()).hexdigest()}, expected=409)
    base.require(h.api("/v1/effect-evidence/resume-ok") == record, "signed effect changed across restart")
    h.stop()
    verified = json.loads(h.command([str(h.binary), "verify"]))
    base.require(verified["verified"], "recovery receipt chain invalid")
    pending_records = [json.loads((h.state / "effect-evidence-pending" / (body["observation_id"] + ".json")).read_text())
                       for body in bodies]
    return {"pending_records": pending_records, "schema_version": "recovery-fixture/v1", "coverage": "component_fixture",
            "sigkill_count": 2, "recovery_records": recoveries, "effect_record": record,
            "completion": completion, "historical_revocation_rejected": True,
            "public_evidence": capture(h, "recovery"),
            "limitations": ["Linux process crash; not power-loss or OS isolation proof",
                            "controlled host observer; native platform scheduling not evaluated"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("base", ROOT / "scripts/validate-intent-v2-hermes.py")
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    with tempfile.TemporaryDirectory(prefix="siq-recovery-fixture-") as temporary:
        h = base.Harness(Path(temporary), SimpleNamespace())
        try:
            result = run(h, base)
        finally:
            h.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print("PASS: two SIGKILL restarts, original snapshot, recovered completion, durable revocation")


if __name__ == "__main__":
    main()
