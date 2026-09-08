"""Public-only benchmark receipt bundles and independent Ed25519 verification."""
import base64
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def capture(harness, label):
    # Explicit allowlist: never include state keys, tokens, or arbitrary state files.
    records = []
    for path in sorted((harness.state / "receipts").glob("*/*.jsonl")):
        records.extend(json.loads(line) for line in path.read_text().splitlines() if line)
    records.sort(key=lambda record: (record["chain_id"], record["seq"]))
    return {"fixture": label, "public_key": harness.command([str(harness.binary), "pubkey"]).strip(),
            "binary_sha256": hashlib.sha256(harness.binary.read_bytes()).hexdigest(), "receipts": records}


def verify_global_revocation(checks, actions, primary_id, benign_id):
    """Bind a signed global withdrawal to two previously valid session receipts."""
    from datetime import datetime

    revoked = checks["revocation"]
    fields = {"schema_version", "intent_id", "intent_digest", "revoked_at", "reason_code",
              "signing_schema", "signature"}
    if (set(revoked) != fields or revoked["schema_version"] != "intent-revocation/v1"
            or revoked["signing_schema"] != "local_canonical/v1" or revoked["reason_code"] != "intent_revoked"):
        raise ValueError("invalid global revocation contract")
    stamp = datetime.fromisoformat(revoked["revoked_at"])
    if stamp.tzinfo is None:
        raise ValueError("revocation timestamp lacks timezone")
    before_ids = checks["before_receipt_ids"]
    second_id = checks["second_denied_receipt_id"]
    if len(before_ids) != 2 or len({*before_ids, second_id, primary_id, benign_id}) != 5:
        raise ValueError("revocation probes must be distinct")
    before = [actions[identity][0] for identity in before_ids]
    after = [actions[identity][0] for identity in (primary_id, second_id)]
    unsigned = {k: v for k, v in revoked.items() if k != "signature"}
    for identity in (*before_ids, primary_id, second_id):
        record, key = actions[identity]
        key.verify(bytes.fromhex(revoked["signature"]), canonical(unsigned))
        if (record["record_type"] != "decision" or record["intent_id"] != revoked["intent_id"]
                or record["intent_digest"] != revoked["intent_digest"]):
            raise ValueError("revocation probe references another Intent")
    sessions_before = {r["session_id"] for r in before}
    if len(sessions_before) != 2 or {r["session_id"] for r in after} != sessions_before:
        raise ValueError("global revocation must cover both original sessions")
    if any(r["action"] != "allow" for r in before):
        raise ValueError("revocation lacks two authorized preconditions")
    if any(r["action"] != "deny" or r["reason_code"] != "intent_revoked" for r in after):
        raise ValueError("global revocation did not deny both sessions")
    benign = actions[benign_id][0]
    if benign["action"] != "allow" or benign["intent_id"] == revoked["intent_id"]:
        raise ValueError("unrelated Intent control missing")


def verify_receipt_bundles(bundles):
    """Verify complete supplied chain prefixes; no external checkpoint claim."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    actions = {}
    count = 0
    if len(bundles) > 64:
        raise ValueError("receipt bundle capacity exceeded")
    for bundle in bundles:
        if len(bundle["receipts"]) + count > 65536:
            raise ValueError("receipt record capacity exceeded")
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(bundle["public_key"], validate=True))
        heads = {}
        for record in bundle["receipts"]:
            chain = record["chain_id"]
            seq, previous = heads.get(chain, (0, "0" * 64))
            if record["seq"] != seq or record["prev_hash"] != previous:
                raise ValueError("receipt sequence or parent hash mismatch")
            unsigned = {k: v for k, v in record.items() if k not in ("hash", "sig")}
            digest = hashlib.sha256(canonical(unsigned)).hexdigest()
            if digest != record["hash"]:
                raise ValueError("receipt content hash mismatch")
            key.verify(bytes.fromhex(record["sig"]), digest.encode())
            heads[chain] = (seq + 1, digest)
            count += 1
            identity = record["receipt_id"]
            if identity in actions:
                raise ValueError("duplicate receipt identity")
            actions[identity] = (record, key)
    return actions, count


def verify_effect_reference(record, d5, decision_receipt_id):
    """An observation cannot borrow another action's oracle or invent one."""
    if record is None:
        if d5["value"] is not None:
            raise ValueError("D5 requires an archived effect record")
        return
    effect = record["evidence"]
    if effect["decision_receipt_id"] != decision_receipt_id:
        raise ValueError("effect belongs to another observation decision")
    if d5["value"] is not None:
        if d5.get("evidence_refs") != [effect["effect_evidence_id"]]:
            raise ValueError("D5 does not reference its signed effect")
        if record.get("file_observation") is None and record.get("network_observation") is None:
            raise ValueError("D5 requires archived observation material")


def verify(report):
    actions, count = verify_receipt_bundles(report["public_evidence"])
    scenarios = {s["id"]: s for path in (Path(__file__).parent / "scenarios").glob("*.json")
                 for s in [json.loads(path.read_text())]}
    seen = set()
    effects = 0
    for observation in report["observations"]:
        identity = observation["scenario_id"]
        if identity in seen or identity not in scenarios or observation["iteration"] != 0:
            raise ValueError("duplicate or unknown benchmark observation")
        seen.add(identity)
        scenario = scenarios[identity]
        if (observation["scenario_sha256"] != hashlib.sha256(canonical(scenario)).hexdigest()
                or observation["kind"] != scenario["kind"] or observation["category"] != scenario["category"]
                or observation["expected_action"] != scenario["expected"]["decision_action"]
                or observation["expected_reason"] != scenario["expected"]["reason_code"]):
            raise ValueError("observation does not match reviewed scenario")
        refs = observation["stages"]["d2"]["evidence_refs"]
        if len(refs) != 1 or refs[0] not in actions or observation["stages"]["d2"]["value"] is not True:
            raise ValueError("decision evidence reference missing")
        decision, _ = actions[refs[0]]
        reason = (observation["decision"]["reason_code"] if isinstance(observation["decision"], dict)
                  else observation["reason_code"])
        if (decision["record_type"] != "decision" or observation["decision_action"] != decision["action"]
                or reason != decision["reason_code"]):
            raise ValueError("reported decision differs from signed receipt")
        record = observation.get("effect_record")
        verify_effect_reference(record, observation["stages"]["d5"], refs[0])
        if record is None:
            continue
        effect = record["evidence"]
        decision, key = actions[effect["decision_receipt_id"]]
        if decision["action_id"] != effect["action_id"]:
            raise ValueError("effect action correlation mismatch")
        for document in (effect, record):
            if document["signing_schema"] != "local_canonical/v1":
                raise ValueError("unsupported signing schema")
            unsigned = {k: v for k, v in document.items() if k != "signature"}
            # Record.unsigned uses Go json.Unmarshal into map[string]any:
            # JSON numbers become float64 (e.g. size 28 signs as 28.0).
            normalized = json.loads(json.dumps(unsigned), parse_int=float)
            key.verify(bytes.fromhex(document["signature"]), canonical(normalized))
        d5 = observation["stages"]["d5"]
        if d5["value"] is not None:
            if d5.get("independence") != effect["source"]["independence"]:
                raise ValueError("claimed independence differs from signed effect")
            material = record.get("file_observation")
            observed = material["after"]["exists"] if material else record.get("network_observation") is not None
            if d5["value"] is not observed:
                raise ValueError("D5 differs from archived observation material")
        effects += 1
    if seen != set(scenarios):
        raise ValueError("benchmark observations are incomplete")
    global_pair = {o["kind"]: o for o in report["observations"] if o["scenario_id"].startswith("revoked-intent-")}
    if global_pair:
        verify_global_revocation(report["fixture_evidence"]["global_revocation_checks"], actions,
                                 global_pair["attack"]["stages"]["d2"]["evidence_refs"][0],
                                 global_pair["benign"]["stages"]["d2"]["evidence_refs"][0])
    from metrics import summarize
    if report["summary"] != summarize(report["observations"]):
        raise ValueError("reported metrics differ from observations")
    return {"verified_receipts": count, "verified_effect_envelopes": effects}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-sha256", help="Report digest obtained from a separately trusted channel")
    args = parser.parse_args()
    raw = args.report.read_bytes()
    if args.expected_sha256 and hashlib.sha256(raw).hexdigest() != args.expected_sha256:
        raise ValueError("report differs from trusted digest")
    print(json.dumps(verify(json.loads(raw)), indent=2))


if __name__ == "__main__":
    main()
