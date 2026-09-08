#!/usr/bin/env python3
"""Independently verify archived pending/recovery signatures and ownership chains.

This does not prove SIGKILL occurrence, historical revocation or Completion semantics.
"""
import argparse
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from evidence import canonical

ROOT = Path(__file__).resolve().parents[2]


def timestamp(value):
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", value)
    if not match:
        raise ValueError("expected canonical UTC nanosecond timestamp")
    seconds = int(datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc).timestamp())
    return seconds * 10**9 + int((match[2] or "").ljust(9, "0"))


def verify_chain(pending, history, key):
    from jsonschema import Draft202012Validator

    def signed(record, schema_name):
        schema = json.loads((ROOT / "packages/contracts" / f"{schema_name}.v1.schema.json").read_text())
        Draft202012Validator(schema).validate(record)
        key.verify(bytes.fromhex(record["signature"]), canonical({k: v for k, v in record.items() if k != "signature"}))

    signed(pending, "file-observation-pending")
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
        signed(recovery, "file-observation-recovery")
        stamp = timestamp(recovery["recovered_at"])
        if (recovery["observation_id"] != pending["observation_id"] or recovery["pending_digest"] != digest
                or recovery["sequence"] != sequence or recovery["previous_hash"] != previous
                or recovery["owner_digest"] == owner or not last <= stamp < expiry):
            raise ValueError("invalid recovery ownership chain")
        owner, last = recovery["owner_digest"], stamp
        previous = hashlib.sha256(canonical(recovery)).hexdigest()
    return owner


def verify(report):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(report["public_evidence"]["public_key"], validate=True))
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
    return {"verified_pending_records": 2, "verified_recovery_records": 2}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.report.stat().st_size > 16 << 20:
        raise ValueError("report exceeds byte budget")
    print(json.dumps(verify(json.loads(args.report.read_text())), indent=2))


if __name__ == "__main__":
    main()
