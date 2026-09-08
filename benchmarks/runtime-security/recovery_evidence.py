#!/usr/bin/env python3
"""Independently verify archived pending/recovery signatures and ownership chains.

This does not prove SIGKILL occurrence, the rejected HTTP request or arbitrary Completion policy semantics.
"""
import argparse
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from evidence import canonical, verify_receipt_bundles

ROOT = Path(__file__).resolve().parents[2]


def timestamp(value):
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", value)
    if not match:
        raise ValueError("expected canonical UTC nanosecond timestamp")
    seconds = int(datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc).timestamp())
    return seconds * 10**9 + int((match[2] or "").ljust(9, "0"))


def signed(record, schema_name, key):
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "packages/contracts" / f"{schema_name}.v1.schema.json").read_text())
    Draft202012Validator(schema).validate(record)
    key.verify(bytes.fromhex(record["signature"]), canonical({k: v for k, v in record.items() if k != "signature"}))


def verify_revocation(revocation, recovery, key):
    """Fixture-specific: the transferred observer was revoked after takeover."""
    signed(revocation, "effect-observer-revocation", key)
    if (revocation["owner_digest"] != recovery["owner_digest"]
            or timestamp(revocation["revoked_at"]) < timestamp(recovery["recovered_at"])):
        raise ValueError("revocation is not of the recovered owner after takeover")


def verify_chain(pending, history, key):
    signed(pending, "file-observation-pending", key)
    if len(history) > 64:
        raise ValueError("recovery history exceeds capacity")
    digest = hashlib.sha256(canonical(pending)).hexdigest()
    previous = "0" * 64
    owner = pending["owner_digest"]
    last = timestamp(pending["before"]["captured_at"])
    expiry = timestamp(pending["expires_at"])
    if last >= expiry:
        raise ValueError("pending expiry precedes snapshot")
    for sequence, recovery in enumerate(history, 1):
        signed(recovery, "file-observation-recovery", key)
        stamp = timestamp(recovery["recovered_at"])
        if (recovery["observation_id"] != pending["observation_id"] or recovery["pending_digest"] != digest
                or recovery["sequence"] != sequence or recovery["previous_hash"] != previous
                or recovery["owner_digest"] == owner or not last <= stamp < expiry):
            raise ValueError("invalid recovery ownership chain")
        owner, last = recovery["owner_digest"], stamp
        previous = hashlib.sha256(canonical(recovery)).hexdigest()
    return owner


def verify_pending_action(pending, decision):
    if (decision["record_type"] != "decision" or decision["action"] != "allow"
            or decision["action_id"] != pending["action_id"]
            or decision["receipt_id"] != pending["decision_receipt_id"]
            or decision.get("authority_status") != "valid"
            or "file.write" not in decision.get("effects", [])
            or any(decision.get(field) != value for field, value in pending["scope"].items())
            or timestamp(decision["issued_at"]) > timestamp(pending["before"]["captured_at"])):
        raise ValueError("pending does not reference its authorized capture scope")
    refs = {r["domain"] + ":sha256:" + r["digest"] for r in decision.get("resource_refs", [])}
    if pending["before"]["resource_ref"] not in refs:
        raise ValueError("pending resource is outside decision")


def verify_file_completion(report, pending, decision, key):
    """Recompute this fixture's single file requirement, not arbitrary task policy."""
    intent = report["signed_intent"]
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT / "packages/contracts/intent-contract.v3.schema.json").read_text())
    Draft202012Validator(schema).validate(intent)
    unsigned = {k: v for k, v in intent.items() if k != "signature"}
    key.verify(bytes.fromhex(intent["signature"]), canonical(unsigned))
    body = {k: v for k, v in unsigned.items() if k != "digest"}
    if (hashlib.sha256(canonical(body)).hexdigest() != intent["digest"]
            or intent["digest"] != decision["intent_digest"] or intent["intent_id"] != decision["intent_id"]
            or intent["task_id"] != decision["task_id"] or intent["agent"]["id"] != decision["agent_id"]
            or intent["agent"]["platform"] != decision["platform"]):
        raise ValueError("Intent does not bind the decision")
    requirements = intent["effect_requirements"]
    if len(requirements) != 1:
        raise ValueError("unsupported recovery completion requirements")
    req = requirements[0]
    record = report["effect_record"]
    effect, material = record["evidence"], record["file_observation"]
    for document in (record, effect):
        if document["signing_schema"] != "local_canonical/v1":
            raise ValueError("unsupported effect signing scheme")
        normalized = json.loads(json.dumps({k: v for k, v in document.items() if k != "signature"}), parse_int=float)
        key.verify(bytes.fromhex(document["signature"]), canonical(normalized))
    material_digest = hashlib.sha256(canonical(json.loads(json.dumps(material), parse_int=float))).hexdigest()
    if (req["effect_type"] != "file.write" or req["minimum_independence"] != "host_independent"
            or req["minimum_coverage"] != "partial" or effect["effect_evidence_id"] != pending["observation_id"]
            or effect["action_id"] != pending["action_id"] or effect["decision_receipt_id"] != pending["decision_receipt_id"]
            or effect["source"] != pending["source"] or effect["source"]["independence"] != "host_independent"
            or effect["coverage"] != "partial" or effect["effect_type"] != "file.write"
            or effect["result"] != "expected" or effect["execution_state"] != "completed"
            or effect["evidence_digest"] != material_digest or record["finding_code"] != ""
            or record["task_id"] != intent["task_id"] or material["before"] != pending["before"]
            or material["result"] != "expected" or material["execution_state"] != "completed"
            or material["after"]["exists"] is not True
            or material["after"]["digest"] != req["expected_digest"]
            or material["expected_digest"] != req["expected_digest"] or pending["expected_digest"] != req["expected_digest"]
            or material["after"]["resource_ref"] != req["resource_ref"] or effect["resource_ref"] != req["resource_ref"]
            or effect["observed_at"] != material["after"]["captured_at"]
            or not timestamp(pending["before"]["captured_at"]) <= timestamp(effect["observed_at"]) < timestamp(pending["expires_at"])):
        raise ValueError("file material does not satisfy signed completion requirement")
    takeover = next(x["recovery"] for x in report["recovery_records"]
                    if x["recovery"]["observation_id"] == pending["observation_id"])
    if not timestamp(takeover["recovered_at"]) <= timestamp(effect["observed_at"]) <= timestamp(report["observer_revocation"]["revoked_at"]):
        raise ValueError("effect capture is outside recovered observer lifetime")
    expected = {"schema_version": "completion-status/v1", "task_id": intent["task_id"],
                "status": "verified", "reason_code": "effects_verified", "incident_ids": [],
                "requirements": [{"requirement_id": req["requirement_id"], "status": "verified",
                                  "reason_code": "effect_verified", "evidence_ids": [effect["effect_evidence_id"]]}]}
    if report["completion"] != expected:
        raise ValueError("reported completion differs from verified materials")


def verify(report):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(report["public_evidence"]["public_key"], validate=True))
    actions, receipt_count = verify_receipt_bundles([report["public_evidence"]])
    pending = report["pending_records"]
    recoveries = report["recovery_records"]
    # This fixture has exactly two independent pending captures and one transfer each.
    if len(pending) != 2 or len(recoveries) != 2:
        raise ValueError("incomplete recovery fixture archive")
    by_id = {p["observation_id"]: p for p in pending}
    if set(by_id) != {"resume-ok", "resume-revoked"}:
        raise ValueError("duplicate or unexpected observation")
    seen = set()
    for envelope in recoveries:
        recovery = envelope["recovery"]
        identity = recovery["observation_id"]
        if identity in seen or identity not in by_id:
            raise ValueError("duplicate or unknown recovery")
        seen.add(identity)
        original = by_id[identity]
        if envelope["expires_at"] != original["expires_at"]:
            raise ValueError("recovery extended pending expiry")
        verify_chain(original, [recovery], key)
        verify_pending_action(original, actions[original["decision_receipt_id"]][0])
        verify_revocation(report["observer_revocation"], recovery, key)
    original = by_id["resume-ok"]
    verify_file_completion(report, original, actions[original["decision_receipt_id"]][0], key)
    return {"verified_pending_records": 2, "verified_recovery_records": 2, "verified_observer_revocations": 1,
            "verified_receipts": receipt_count, "verified_file_completions": 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.report.stat().st_size > 16 << 20:
        raise ValueError("report exceeds byte budget")
    print(json.dumps(verify(json.loads(args.report.read_text())), indent=2))


if __name__ == "__main__":
    main()
