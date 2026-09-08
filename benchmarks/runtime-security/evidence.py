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


def verify(report):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    actions = {}
    count = 0
    for bundle in report["public_evidence"]:
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
