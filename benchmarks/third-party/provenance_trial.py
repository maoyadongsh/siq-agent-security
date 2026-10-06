#!/usr/bin/env python3
"""Real receiver trial comparing no SIQ, one ablated predicate, and full SIQ."""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from common import Events, canonical, safe_path, sha256, utc_now, write_json
from oracles.receiver import ReceiverOracle


def one(protocol, unit, out, fixture, capture):
    directory = out / "cases" / unit["unit_id"]
    directory.mkdir(parents=True)
    recipient = "fixture-finance-team"
    params = {"recipient": recipient, "body": "synthetic report"}
    h, decision, selected, contract, fault = None, None, None, None, None
    oracle = ReceiverOracle(unit["unit_id"], uuid4().hex)
    observation, error = None, None
    try:
        if unit["group"] != "B0":
            root = out / "state-private" / unit["unit_id"]
            root.mkdir(parents=True)
            h = fixture.Harness(root, SimpleNamespace(binary=protocol["binaries"][unit["group"]]["path"]))
            h.read_tool = "send_message"
            h.build()
            h.start()
            h.setup_authority()
            identity = {"platform": "hermes", "session_id": "recipient-session", "agent_id": fixture.AGENT}
            scope = {**identity, "task_id": "task-recipient"}
            contract = h.api("/v1/intents/int-native-fixture")
            for key in ("digest", "signature", "signing_schema"):
                contract.pop(key, None)
            contract.update(schema_version="intent/v3", intent_id="intent-recipient", task_id="task-recipient",
                allowed_tools=["send_message"], allowed_effects=["message.send"],
                resource_constraints=[{"domain": "message", "operator": "equals", "value": "other-team" if unit["variant"] == "resource" else recipient}],
                provenance_constraints=[{"parameter_path": "/recipient", "allowed_source_types": ["USER"], "minimum_trust": "trusted", "required": True}])
            contract = h.api("/v1/intents", contract, expected=201)
            h.api("/v1/intent-bindings", {**identity, "intent_id": contract["intent_id"]}, expected=201)
            token = (h.state / "token").read_text().strip()
            low = h.api("/v1/provenance-reports", {**identity, "report_id": "recipient-mcp",
                "source": {"type": "MCP", "source_id": "synthetic-address-book"}, "content": recipient}, token=token, expected=201)
            if unit["variant"] == "scope-replay":
                scope = {**scope, "task_id": "other-task"}
            expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
            h.api("/v1/provenance-issuers", {"issuer_id": "recipient-user", "local_key_ref": "local-state",
                "allowed_source_types": ["USER"], "max_trust_level": "authoritative", "scope": scope, "expires_at": expires}, expected=201)
            trusted = h.api("/v1/provenance-assertions", {"schema_version": "provenance-assertion/v1", "provenance_id": "recipient-user",
                "source": {"type": "USER", "source_id": "approved-form", "trust": "authoritative"}, "scope": scope,
                "content_digest": hashlib.sha256(canonical(recipient)).hexdigest(), "parents": [], "derivation": "direct",
                "issued_at": contract["issued_at"], "expires_at": expires, "issuer": "recipient-user"}, expected=201)
            selected = low if unit["variant"] == "same-value" and unit["condition"] == "adversarial" else trusted
            if unit["variant"] == "issuer-revoked":
                fault = h.api("/v1/provenance-issuers/recipient-user/revoke", {}, expected=200)
            elif unit["variant"] == "signature":
                paths = []
                for path in (h.state / "provenance-assertions").rglob("*.json"):
                    if json.loads(path.read_text()).get("provenance_id") == "recipient-user":
                        paths.append(path)
                if len(paths) != 1:
                    raise ValueError("unique synthetic assertion required for fault injection")
                tampered = {**trusted, "signature": "0" * 128}
                fault = {"before": trusted, "after": tampered, "method": "test-owned assertion file signature corruption"}
                paths[0].write_text(json.dumps(tampered))
            request = {**identity, "tool": "send_message", "tool_call_id": "delivery", "params": params,
                "parameter_provenance": [{"parameter_path": "/recipient", "provenance_refs": [selected["provenance_id"]]}]}
            write_json(directory / "request.json", request)
            write_json(directory / "authority.json", {"intent": contract, "selected_assertion": selected, "fault": fault})
            decision = h.api("/v1/decide", request, token=token)
        if unit["group"] == "B0" or decision["action"] == "allow":
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with client.open(urllib.request.Request(oracle.url, data=canonical(params), headers={"Content-Type": "application/json"}), timeout=5) as response:
                if response.status != 204:
                    raise ValueError("receiver did not acknowledge")
    except Exception as exc:  # noqa: BLE001 -- keep oracle even after product/transport failure.
        error = type(exc).__name__
    finally:
        try:
            observation = oracle.finish()
            write_json(directory / "oracle.json", observation)
        finally:
            if h:
                try:
                    write_json(directory / "product-evidence.json", capture(h, unit["unit_id"]))
                except Exception as exc:  # noqa: BLE001 -- known receiver events survive failed product capture.
                    error = error or type(exc).__name__
                finally:
                    h.stop()
    count = len(observation["events"])
    params_digest = hashlib.sha256(canonical(params)).hexdigest()
    delivered = count == 1 and observation["events"][0]["body_sha256"] == params_digest
    forbidden = unit["condition"] == "adversarial"
    harm = True if forbidden and count else False if observation["healthy"] else None
    utility = delivered if observation["healthy"] else None
    assertions = [{"name": "receiver_effect", "actual": count, "expected": unit["expected_deliveries"]}]
    if decision:
        assertions += [{"name": "action", "actual": decision["action"], "expected": unit["expected_action"]},
                       {"name": "reason", "actual": decision["reason_code"], "expected": unit["expected_reason"]}]
    for assertion in assertions:
        assertion["pass"] = assertion["actual"] == assertion["expected"]
    status = "fail" if any(not a["pass"] for a in assertions) else "inconclusive" if error or not observation["healthy"] else "pass"
    row = {**unit, "execution_status": "error" if error else "completed", "error_type": error,
           "assertion_status": status, "assertions": assertions, "decision": decision,
           "harm_observed": harm, "utility_completed": utility, "params_sha256": params_digest,
           "harm_definition": "actual synthetic dispatch forbidden by this case's source/resource/identity authority"}
    write_json(directory / "result.json", row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    for root, names in [(Path(__file__).parent, protocol["harness_sources"]),
                        (Path(protocol["candidate_root"]), protocol["candidate_sources"]),
                        (Path(protocol["ablation_root"]), protocol["ablation_sources"])]:
        for relative, digest in names.items():
            if sha256(safe_path(root, relative)) != digest:
                raise ValueError("frozen source changed")
    for item in protocol["binaries"].values():
        if sha256(Path(item["path"])) != item["sha256"]:
            raise ValueError("frozen binary changed")
    os.umask(0o077)
    out = args.out.resolve()
    out.relative_to(Path(protocol["campaign_root"]) / "private/runs")
    out.mkdir(parents=True, exist_ok=False)
    candidate = Path(protocol["candidate_root"])
    spec = importlib.util.spec_from_file_location("source_trial_fixture", candidate / "scripts/validate-intent-v2-hermes.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    sys.path.insert(0, str(candidate / "benchmarks/runtime-security"))
    from evidence import capture

    write_json(out / "protocol.json", protocol)
    events = Events(out / "events.jsonl", out.name)
    for unit in protocol["allocation"]:
        events.add("scheduled", **unit)
    rows = []
    for unit in protocol["allocation"]:
        events.add("started", **unit)
        row = one(protocol, unit, out, fixture, capture)
        rows.append(row)
        events.add("finished", unit_id=unit["unit_id"], execution_status=row["execution_status"])
        print(json.dumps({"unit_id": unit["unit_id"], "assertion_status": row["assertion_status"], "harm_observed": row["harm_observed"]}), flush=True)
    summary = {"allocated": len(rows), "passed": sum(r["assertion_status"] == "pass" for r in rows),
               "failed": sum(r["assertion_status"] == "fail" for r in rows), "inconclusive": sum(r["assertion_status"] == "inconclusive" for r in rows),
               "same_value_effects": {r["unit_id"]: r["utility_completed"] for r in rows if r["variant"] == "same-value"},
               "all_params_equal": len({r["params_sha256"] for r in rows}) == 1, "recorded_at": utc_now(),
               "relationship": "author_run", "scope": "controlled component dispatch; not model ASR or runtime isolation"}
    write_json(out / "summary.json", summary)
    sums = {p.relative_to(out).as_posix(): sha256(p) for p in out.rglob("*.json") if "state-private" not in p.parts}
    sums["events.jsonl"] = sha256(out / "events.jsonl")
    write_json(out / "checksums.json", sums)
    write_json(out / "manifest.json", {"schema_version": "siq-provenance-trial-manifest/v1", "allocated": len(rows),
        "checksums_sha256": sha256(out / "checksums.json"), "protocol_sha256": sha256(out / "protocol.json"),
        "sealed_at": utc_now(), "relationship": "author_run", "trust": "author_local"})
    print(json.dumps({**summary, "manifest_sha256": sha256(out / "manifest.json")}))
    return 1 if summary["failed"] else 2 if summary["inconclusive"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
