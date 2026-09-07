#!/usr/bin/env python3
"""Exercise binding revoke over real HTTP, concurrent decisions and native CLI restart."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "codebuddy", REPO / "scripts/validate-intent-v2-codebuddy.py"
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
require = base.require


def run(h):
    pkg = json.loads((h.args.codebuddy_root / "package.json").read_text())
    require(
        pkg["name"] == "@tencent-ai/codebuddy-code" and pkg["version"] == "2.146.0",
        "wrong native package",
    )
    h.build()
    h.start()
    h.command([str(h.binary), "adapter", "install", "codebuddy"])
    h.setup_authority()
    output = h.native([h.read("allowed")])[0]["result"]
    require("fixture-visible-company-a" in output, "authorized native control missing")
    h.assert_call(h.receipts(), "allowed", "allow")
    bindings = h.api("/v1/intent-bindings")["items"]
    require(len(bindings) == 1, "unexpected fixture binding count")
    binding = bindings[0]
    binding_file = h.state / "intent-bindings" / (binding["binding_id"] + ".json")
    original_hash = base.digest(binding_file)
    path = "/v1/intent-bindings/" + binding["binding_id"]
    body = {"expected_intent_digest": binding["intent_digest"]}
    token = (h.state / "token").read_text().strip()
    h.api(path + "/revoke", body, token=token, expected=403)
    h.api(path + "/revocation", expected=404)
    start = threading.Event()

    def decide(index, prefix):
        start.wait(timeout=10)
        before = time.perf_counter()
        d = h.api(
            "/v1/decide",
            {
                "platform": h.platform,
                "session_id": base.SESSION,
                "agent_id": base.base.AGENT,
                "tool": "Read",
                "tool_call_id": f"{prefix}-{index}",
                "params": h.read("fixture")["params"],
            },
            token=token,
        )
        return {
            "action": d["action"],
            "reason_code": d["reason_code"],
            "elapsed_ms": (time.perf_counter() - before) * 1000,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(decide, index, "overlap") for index in range(32)]
        start.set()
        revoked = h.api(path + "/revoke", body)
        overlapping = [f.result() for f in futures]
        subsequent = list(pool.map(lambda i: decide(i, "after-revoke"), range(32)))
        retries = list(pool.map(lambda _: h.api(path + "/revoke", body), range(8)))
    require(
        all(
            d["action"] == "allow"
            or (d["action"] == "deny" and d["reason_code"] == "intent_binding_revoked")
            for d in overlapping
        ),
        "unexpected overlapping decision",
    )
    require(
        all(
            d["action"] == "deny" and d["reason_code"] == "intent_binding_revoked"
            for d in subsequent
        ),
        "post-revocation request authorized",
    )
    require(
        all(r == revoked for r in retries), "revocation retries changed signed record"
    )
    require(h.api(path + "/revocation") == revoked, "revocation readback differs")
    require(base.digest(binding_file) == original_hash, "revocation rewrote binding")
    revocation_file = (
        h.state / "intent-binding-revocations" / (binding["binding_id"] + ".json")
    )
    revocation_hash = base.digest(revocation_file)
    require(
        revoked["binding_digest"]
        == hashlib.sha256(
            json.dumps(
                binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest(),
        "revocation does not bind original signed binding",
    )
    denied = h.native([h.read("revoked-native")])[0]["result"]
    require(
        "fixture-visible-" not in denied and "siq-agent-security" in denied,
        "native revoke did not block",
    )
    d = h.assert_call(h.receipts(), "revoked-native", "deny")
    require(
        d["reason_code"] == "intent_binding_revoked",
        "native revoke denied for wrong reason",
    )
    h.stop(kill=True)
    h.config("optional")
    h.start()
    require(h.api(path + "/revocation") == revoked, "revocation lost on daemon restart")
    denied = h.native([h.read("revoked-after-restart")])[0]["result"]
    require(
        "fixture-visible-" not in denied, "restart optional downgraded revoked session"
    )
    d = h.assert_call(h.receipts(), "revoked-after-restart", "deny")
    require(
        d["reason_code"] == "intent_binding_revoked", "restart lost revocation reason"
    )
    unrelated = h.native([h.read("unrelated-optional")], "unrelated-session")[0][
        "result"
    ]
    require(
        "fixture-visible-company-a" in unrelated, "revocation crossed session identity"
    )
    records = h.receipts()
    h.assert_call(records, "unrelated-optional", "allow", bound=False)
    require(
        base.digest(binding_file) == original_hash
        and base.digest(revocation_file) == revocation_hash,
        "authority records changed",
    )
    h.stop()
    verified = json.loads(h.command([str(h.binary), "verify"]))
    require(verified["verified"], "offline receipt verification failed")

    def latency(values):
        values = sorted(v["elapsed_ms"] for v in values)
        return {
            f"p{n}_ms": round(values[max(0, math.ceil(len(values) * n / 100) - 1)], 3)
            for n in (50, 95, 99)
        }

    return {
        "schema": "intent-binding-revocation-validation/v1",
        "passed": True,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "siq_commit": h.command(["git", "rev-parse", "HEAD"], cwd=REPO).strip(),
        "runtime": {
            "package": pkg["name"],
            "version": pkg["version"],
            "headless_sha256": base.digest(
                h.args.codebuddy_root / "dist/codebuddy-headless.js"
            ),
        },
        "source_sha256": {
            p: base.digest(REPO / p)
            for p in [
                "scripts/validate-intent-binding-revocation.py",
                "scripts/validate-intent-v2-codebuddy.py",
                "apps/agentshield/internal/intent/revocation.go",
                "apps/agentshield/internal/intent/store.go",
                "apps/agentshield/internal/receipt/engine.go",
                "apps/agentshield/internal/receipt/intent.go",
                "apps/agentshield/internal/server/intent_http.go",
            ]
        },
        "binary_sha256": base.digest(h.binary),
        "binding_sha256": original_hash,
        "revocation_sha256": revocation_hash,
        "concurrent_http": {
            "concurrency": 8,
            "overlap_count": 32,
            "overlap_allowed": sum(v["action"] == "allow" for v in overlapping),
            "post_revoke_count": 32,
            "post_revoke_denied": len(subsequent),
            "idempotent_retries": len(retries),
            "overlap_latency": latency(overlapping),
            "post_revoke_latency": latency(subsequent),
        },
        "native_cli_invocations": h.native_count,
        "model_requests": h.model.request_count,
        "receipt_count": len(records),
        "offline_verified": True,
        "checks": [
            "decision_credential_cannot_revoke",
            "signed_revocation_readback_and_idempotency",
            "original_binding_preserved",
            "post_revoke_http_denied",
            "native_tool_blocked_after_revoke",
            "kill_restart_optional_no_downgrade",
            "unrelated_optional_session_still_allowed",
        ],
        "limitations": [
            "snapshot authorization, not atomic effect cancellation",
            "HTTP concurrency mixed with separately labelled native calls",
            "synthetic operator and local deterministic model",
            "desktop same UID; no OS isolation",
            "one fixed Linux CLI version",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codebuddy-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.codebuddy_root = args.codebuddy_root.resolve(strict=True)
    args.node = args.node.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="siq-binding-revoke-") as directory:
        h = base.Harness(Path(directory), args)
        try:
            report = run(h)
        finally:
            h.stop()
            h.model.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "receipt_count": report["receipt_count"],
                "concurrent_http": report["concurrent_http"],
            }
        )
    )


if __name__ == "__main__":
    main()
