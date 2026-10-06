"""Recompute P06 HTTP results without running SIQ or importing its decision engine."""
import base64
import hashlib
import json

from common import safe_path, sha256
from lifecycle import project, summarize
from management_scoring import score, specs


def verify(run, anchor=None):
    if anchor is not None and sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("management manifest anchor differs")
    manifest = json.loads(safe_path(run, "manifest.json").read_text())
    if manifest["schema_version"] != "siq-management-http-manifest/v1":
        raise ValueError("management manifest schema differs")
    artifacts = manifest["artifacts"]
    if not {"protocol.json", "journal.jsonl", "cases.jsonl", "summary.json"} <= set(artifacts):
        raise ValueError("canonical management material missing")
    for name, digest in artifacts.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("management material changed")
    protocol, states, _, _ = project(run)
    expected = json.loads(json.dumps(specs()))
    if protocol["operation"] != "management_http" or {u["unit_id"]: u["requests"] for u in protocol["allocation"]} != expected:
        raise ValueError("management allocation changed")
    cases = [json.loads(line) for line in safe_path(run, "cases.jsonl").read_text().splitlines()]
    if cases != list(states.values()):
        raise ValueError("management case projection differs")
    totals = {"http_requests": 0, "predicates": 0, "predicates_passed": 0, "signed_intent_responses": 0}
    for row in cases:
        unit = next(u for u in protocol["allocation"] if u["unit_id"] == row["unit_id"])
        prefix = f"attempts/{row['unit_id']}/{row['attempt']}"
        for field in ("harm_evidence_refs", "utility_evidence_refs", "receipt_refs", "event_trace_refs"):
            if not set(row[field]) <= set(artifacts):
                raise ValueError("management evidence unsealed")
        if not set(row["oracle"]["materials"]) <= set(artifacts):
            raise ValueError("management oracle unsealed")
        http_path = prefix + "/http.jsonl"
        requests = []
        if http_path in artifacts:
            raw = safe_path(run, http_path).read_bytes()
            if not raw.endswith(b"\n"):
                raise ValueError("interrupted HTTP journal")
            requests = [json.loads(line) for line in raw.splitlines()]
        if [r["request_id"] for r in requests] != [item[0] for item in unit["requests"][:len(requests)]]:
            raise ValueError("HTTP request order differs")
        totals["http_requests"] += len(requests)
        observed_harm = False
        for request, (_, status) in zip(requests, unit["requests"], strict=False):
            changed = request["authority_before"] != request["authority_after"]
            observed_harm |= (status >= 400 and (request["status"] < 400 or changed)) or request["unexpected_credential_reflection"]
        if observed_harm and row["harm_observed"] is not True:
            raise ValueError("partial management harm erased")
        if row["execution_status"] != "completed":
            continue
        required = {prefix + "/observations.json", prefix + "/score.json", prefix + "/cleanup.json", http_path}
        if not required <= set(artifacts):
            raise ValueError("completed management material missing")
        observations = json.loads(safe_path(run, prefix + "/observations.json").read_text())
        if observations["http"] != requests:
            raise ValueError("HTTP projection differs")
        result = score(unit, observations)
        if json.loads(safe_path(run, prefix + "/score.json").read_text()) != result:
            raise ValueError("management score differs")
        for field in ("harm_observed", "utility_completed", "assertion_status"):
            if row[field] != result[field]:
                raise ValueError("management canonical result differs")
        cleanup = json.loads(safe_path(run, prefix + "/cleanup.json").read_text())
        if cleanup["confirmed"] != (not cleanup["remaining_group_members"]) or row["cleanup_confirmed"] != cleanup["confirmed"]:
            raise ValueError("management cleanup differs")
        if protocol.get("signed_intent_verification"):
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(observations["public_key"], validate=True))
            for request in requests:
                contract = request["response_body"]
                signed_response = request["status"] == 201 or (request["request_id"].endswith("readback") and request["status"] == 200)
                if not signed_response:
                    continue
                if not isinstance(contract, dict) or contract.get("schema_version") not in ("intent/v2", "intent/v3"):
                    raise ValueError("issued Intent signed response missing")
                unsigned = {k: v for k, v in contract.items() if k != "signature"}
                digest_input = {k: v for k, v in unsigned.items() if k != "digest"}

                def canonical(value):
                    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

                if hashlib.sha256(canonical(digest_input)).hexdigest() != contract["digest"]:
                    raise ValueError("issued Intent digest differs")
                try:
                    key.verify(bytes.fromhex(contract["signature"]), canonical(unsigned))
                except InvalidSignature:
                    raise ValueError("issued Intent signature invalid") from None
                totals["signed_intent_responses"] += 1
        totals["predicates"] += result["total"]
        totals["predicates_passed"] += result["passed"]
    summary = summarize(states)
    if json.loads(safe_path(run, "summary.json").read_text()) != summary:
        raise ValueError("management first-attempt summary differs")
    return {"integrity": "verified_against_supplied_digest" if anchor else "internal_consistency_only",
            "scope": "P06 loopback HTTP; no browser or OS isolation certification", **totals, **summary}, summary["outcome_exit_code"]
