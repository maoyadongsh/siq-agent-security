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
    effects = 0
    for observation in report["observations"]:
        for ref in observation["stages"]["d2"]["evidence_refs"]:
            if ref not in actions:
                raise ValueError("decision evidence reference missing")
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
        effects += 1
    return {"verified_receipts": count, "verified_effect_envelopes": effects}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.report.read_text())), indent=2))


if __name__ == "__main__":
    main()
