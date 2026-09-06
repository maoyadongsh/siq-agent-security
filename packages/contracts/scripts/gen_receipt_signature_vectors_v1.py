#!/usr/bin/env python3
"""Independent producer for receipt_signature_vectors_v1.json (DEV09-D).

Receipt contract (apps/agentshield/internal/receipt):
  content_hash = sha256(local_canonical(body without hash/sig)).hex()
  signature    = Ed25519(content_hash.encode("ascii"))   # NOT over canonical body

Does not import agentshield or control-api. Re-run only when refreshing fixtures.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "receipt_signature_vectors_v1.json"
GENESIS = "0" * 64


def local_canon(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def content_hash(body: dict) -> tuple[str, str]:
    """Return (canonical_utf8, sha256_hex). Body must omit hash/sig."""
    if "hash" in body or "sig" in body:
        raise SystemExit("fixture body must omit hash/sig")
    c = local_canon(body)
    return c.decode("ascii"), hashlib.sha256(c).hexdigest()


def main() -> None:
    seed = bytes(range(32))
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")

    def sign_hash(h: str) -> str:
        return priv.sign(h.encode("ascii")).hex()

    r0 = {
        "receipt_id": "rcp-fixture-0",
        "chain_id": "chain-fixture",
        "seq": 0,
        "prev_hash": GENESIS,
        "issued_at": "2026-09-06T00:00:00Z",
        "platform": "hermes",
        "session_id": "sess-1",
        "agent_id": "agent-1",
        "tool": "exec",
        "tool_call_id": None,
        "params_digest": "a" * 64,
        "params_excerpt": None,
        "action": "deny",
        "advisory_action": None,
        "reason": "命中规则 <危险>",
        "matched_grant_id": None,
        "matched_fact_ids": [],
        "matched_rule_ids": ["rule.fixture"],
        "taint_labels": [],
        "trifecta": {"private_data": False, "untrusted_input": False, "egress": False},
        "enforcement_mode": "block",
        "policy_revision": None,
        "sandbox_id": None,
        "model_key": None,
        "engine": {"version": "test", "rulepack_version": 1},
        "decision_latency_ms": None,
        "hold": None,
    }
    c0, h0 = content_hash(r0)
    s0 = sign_hash(h0)

    r1 = {
        "receipt_id": "rcp-fixture-1",
        "chain_id": "chain-fixture",
        "seq": 1,
        "prev_hash": h0,
        "issued_at": "2026-09-06T00:00:01Z",
        "platform": "hermes",
        "session_id": "sess-1",
        "agent_id": "agent-1",
        "tool": "exec",
        "tool_call_id": None,
        "params_digest": "b" * 64,
        "params_excerpt": None,
        "action": "allow",
        "advisory_action": None,
        "reason": "granted",
        "matched_grant_id": "grn-fixture01",
        "matched_fact_ids": ["fact.read"],
        "matched_rule_ids": [],
        "taint_labels": [],
        "trifecta": {"private_data": False, "untrusted_input": False, "egress": False},
        "enforcement_mode": "block",
        "policy_revision": None,
        "sandbox_id": None,
        "model_key": None,
        "engine": {"version": "test", "rulepack_version": 1},
        "decision_latency_ms": None,
        "hold": None,
    }
    c1, h1 = content_hash(r1)
    s1 = sign_hash(h1)

    # Wrong contract: SignCanonical over body must differ from hash-chain sig.
    wrong_sig = priv.sign(local_canon(r0)).hex()
    assert wrong_sig != s0

    out = {
        "schema": "receipt_signature_vectors/v1",
        "signing_schema": "receipt_hash_chain/v1",
        "producer": "CPython local_canon(ensure_ascii=True) → sha256 hex → Ed25519(hex ASCII); seed=bytes(range(32))",
        "contract": "receipt.ContentHash + signing.SignBytes([]byte(hashHex)); NOT SignCanonical(body)",
        "genesis_prev_hash": GENESIS,
        "cross_contract_note": {
            "name": "genesis_chinese_html",
            "sign_canonical_of_body_hex": wrong_sig,
            "must_differ_from_hash_chain_sig": True,
        },
        "vectors": [
            {
                "name": "genesis_chinese_html",
                "document": r0,
                "canonical_utf8": c0,
                "content_hash_hex": h0,
                "signature_hex": s0,
                "public_key_b64": pub_b64,
            },
            {
                "name": "chained_second",
                "document": r1,
                "canonical_utf8": c1,
                "content_hash_hex": h1,
                "signature_hex": s1,
                "public_key_b64": pub_b64,
                "prev_must_equal_hash_of": "genesis_chinese_html",
            },
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(out['vectors'])} vectors)")


if __name__ == "__main__":
    main()
