#!/usr/bin/env python3
"""Export/recompute author-captured HTTP/SQL governance evidence; no attestation."""
import argparse
import itertools
import json
import re
import shutil
from pathlib import Path

from common import safe_path, sha256, utc_now, write_json

REQUIRED = {"summary.json", "protocol.json", "http.json", "events.jsonl", "image.json", "issuer.json"}
EXPORT = REQUIRED | {"database-final.json", "edge-observations.json", "backend-observations.json", "backend-cleanup.json", "ui-observations.json", "race-observations.json", "native-enterprise-observations.json", "risk-observations.json"}


def read(run, name):
    return json.loads(safe_path(run, name).read_text())


def checked_manifest(run, anchor):
    if sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("manifest anchor differs")
    manifest = read(run, "manifest.json")
    if not REQUIRED <= set(manifest["artifacts"]):
        raise ValueError("required artifacts absent")
    for name, digest in manifest["artifacts"].items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("artifact changed: " + name)
    return manifest


def export(run, anchor, output):
    manifest = checked_manifest(run, anchor)
    output.mkdir(parents=True, exist_ok=False)
    for name in EXPORT & set(manifest["artifacts"]):
        shutil.copyfile(run / name, output / name)
    ui_artifacts = set()
    if "ui-observations.json" in manifest["artifacts"]:
        ui_artifacts = set(read(run, "ui-observations.json")["artifacts"])
        for name in ui_artifacts:
            if not re.fullmatch(r"output/playwright/[a-zA-Z0-9_-]+\.(yaml|png|txt)", name):
                raise ValueError("unexpected UI export artifact")
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(run, name), target)
    write_json(output / "manifest.json", {"schema_version": "siq-governance-export/v1",
        "run_id": manifest["run_id"], "created_at": utc_now(), "private_manifest_sha256": anchor,
        "excluded_private_artifacts": {n: h for n, h in manifest["artifacts"].items() if n not in EXPORT | ui_artifacts},
        "artifacts": {str(p.relative_to(output)): sha256(p) for p in sorted(output.rglob("*")) if p.is_file()}})
    return {"output": str(output), "manifest_sha256": sha256(output / "manifest.json")}


def verify(run, anchor):
    manifest = checked_manifest(run, anchor)
    summary, protocol, rows = (read(run, n) for n in ("summary.json", "protocol.json", "http.json"))
    if sha256(run / "protocol.json") != summary["protocol_sha256"]:
        raise ValueError("protocol differs")
    if summary["run_id"] != manifest["run_id"] or summary["protocol_id"] != protocol["protocol_id"]:
        raise ValueError("identity mismatch")
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    if [e["sequence"] for e in events] != list(range(1, len(events) + 1)):
        raise ValueError("event sequence differs")
    if any(e["run_id"] != summary["run_id"] for e in events):
        raise ValueError("event run mismatch")
    if any(a["monotonic_ns"] > b["monotonic_ns"] for a, b in itertools.pairwise(events)):
        raise ValueError("event time reversed")
    by_case = {r["case_id"]: r for r in rows}
    if len(by_case) != len(rows) or not set(by_case) <= set(protocol["expected_status"]):
        raise ValueError("duplicate or unallocated request")
    captured = [{k: e[k] for k in by_case[e['case_id']]} for e in events if e["event"] == "http"] if rows else []
    if captured != rows:
        raise ValueError("HTTP projection differs")
    checks = {c["id"]: c for c in summary["checks"]}
    edge_results = {}
    backend_results = {}
    ui_results = {}
    race_results = {}
    native_results = {}
    risk_results = {}
    if protocol.get('risk_assertions') and 'risk-observations.json' in manifest['artifacts']:
        if protocol.get('rule_race_profile'):
            from enterprise_rule_race import ASSERTIONS as risk_assertions
            from enterprise_rule_race import evaluate as evaluate_risk
        elif protocol.get('risk_race_profile'):
            from enterprise_risk_race import ASSERTIONS as risk_assertions
            from enterprise_risk_race import evaluate as evaluate_risk
        elif protocol.get('risk_worker_cycle'):
            from enterprise_risk_worker import ASSERTIONS as risk_assertions
            from enterprise_risk_worker import evaluate as evaluate_risk
        elif protocol.get('risk_boundary_profile'):
            from enterprise_risk_boundaries import ASSERTIONS as risk_assertions
            from enterprise_risk_boundaries import evaluate as evaluate_risk
        elif protocol.get('risk_lifecycle_v2'):
            from enterprise_risk_v2 import ASSERTIONS as risk_assertions
            from enterprise_risk_v2 import evaluate as evaluate_risk
        else:
            from enterprise_risk import ASSERTIONS as risk_assertions
            from enterprise_risk import evaluate as evaluate_risk
        if protocol['risk_assertions'] != risk_assertions:
            raise ValueError('risk assertion allocation differs')
        o = read(run, 'risk-observations.json')
        captured = [e for e in events if e['event'] == 'risk_observation']
        if len({e['name'] for e in captured}) != len(captured) or {e['name']: e['value'] for e in captured} != o:
            raise ValueError('risk observation projection differs')
        for case, row in o.get('http', {}).items():
            if row != by_case[case]:
                raise ValueError('risk HTTP projection differs')
        if any(name in checks for name in risk_assertions):
            risk_results = evaluate_risk(o)
    if protocol.get('native_enterprise_assertions') and 'native-enterprise-observations.json' in manifest['artifacts']:
        from enterprise_native_edge import ASSERTIONS as native_assertions
        from enterprise_native_edge import evaluate as evaluate_native
        if protocol['native_enterprise_assertions'] != native_assertions:
            raise ValueError('native enterprise assertion allocation differs')
        o = read(run, 'native-enterprise-observations.json')
        captured = [e for e in events if e['event'] == 'native_enterprise_observation']
        if len({e['name'] for e in captured}) != len(captured) or {e['name']: e['value'] for e in captured} != o:
            raise ValueError('native observation projection differs')
        for key, case in [('scan', 'native_scan'), ('scan_status', 'native_scan_status'), ('assets', 'native_candidates'), ('evidence', 'native_evidence')]:
            if key in o and o[key] != by_case[case]['body']:
                raise ValueError('native HTTP projection differs')
        if any(name in checks for name in native_assertions):
            native_results = evaluate_native(o)
    if protocol.get("race_assertions") and "race-observations.json" in manifest["artifacts"]:
        from concurrent_governance import ASSERTIONS as race_assertions
        from concurrent_governance import GROUPS
        from concurrent_governance import evaluate as evaluate_race
        if protocol["race_assertions"] != race_assertions or protocol["race_groups"] != GROUPS:
            raise ValueError("race allocation differs")
        o = read(run, "race-observations.json")
        captures = {e["name"]: e["value"] for e in events if e["event"] == "race_observation"}
        for name, group in captures.items():
            if o.get(name) != group:
                raise ValueError("race observations differ")
            finishes = [e for e in events if e["event"] == "race_http_finished" and e["group"] == name and isinstance(e["index"], int)]
            projected = [{k: e[k] for k in group["responses"][0]} for e in sorted(finishes, key=lambda e: e["index"])]
            if projected != group["responses"]:
                raise ValueError("race HTTP projection differs")
            barriers = [e["blocked"] for e in events if e["event"] == "race_barrier_released" and e["group"] == name]
            if barriers != [group["blocked"]]:
                raise ValueError("race barrier differs")
        if any(name in checks for name in race_assertions):
            if set(captures) != set(GROUPS):
                raise ValueError("race assertions lack complete group captures")
            race_results = evaluate_race(o)
    if protocol.get("ui_assertions") and "ui-observations.json" in manifest["artifacts"]:
        from ui_governance import ASSERTIONS as ui_assertions
        from ui_governance import evaluate as evaluate_ui
        o = read(run, "ui-observations.json")
        if protocol["ui_assertions"] != ui_assertions:
            raise ValueError("UI allocation differs")
        if [e["value"] for e in events if e["event"] == "ui_observations"] != [o]:
            raise ValueError("UI observations differ")
        if [{k: e[k] for k in ("method", "path", "status", "body")} for e in events if e["event"] == "ui_http"] != [
                {k: e[k] for k in ("method", "path", "status", "body")} for e in o["api"]]:
            raise ValueError("UI HTTP projection differs")
        for name, digest in o["artifacts"].items():
            if manifest["artifacts"].get(name) != digest:
                raise ValueError("UI artifact lacks seal")
        for name in ("self_review", "approved", "approved_mobile", "cross_tenant", "disconnected"):
            path = f"output/playwright/{name}.yaml"
            if name in o and safe_path(run, path).read_text() != o[name]:
                raise ValueError("UI snapshot projection differs")
        if any(name in checks for name in ui_assertions):
            for name in ("self-review", "approved-desktop", "approved-mobile", "cross-tenant", "disconnected"):
                if f"output/playwright/{name}.png" not in o["artifacts"]:
                    raise ValueError("required UI screenshot absent")
            ui_results = evaluate_ui(o)
    if protocol.get("backend_assertions") and "backend-observations.json" in manifest["artifacts"]:
        import yaml
        from backend_governance import ASSERTIONS as backend_assertions
        from backend_governance import evaluate as evaluate_backend
        if protocol.get('native_enterprise_assertions'):
            from enterprise_runtime import ASSERTIONS as effect_assertions
            backend_assertions = backend_assertions + effect_assertions
        if protocol.get('enterprise_authority_assertions'):
            from enterprise_authority import ASSERTIONS as authority_assertions
            if protocol['enterprise_authority_assertions'] != authority_assertions:
                raise ValueError('enterprise authority allocation differs')
            backend_assertions = backend_assertions + authority_assertions
        if protocol["backend_assertions"] != backend_assertions:
            raise ValueError("backend assertion allocation differs")
        backend_observed = read(run, "backend-observations.json")
        captured = [e for e in events if e["event"] == "backend_observation"]
        if len({e["name"] for e in captured}) != len(captured) or {e["name"]: e["value"] for e in captured} != backend_observed:
            raise ValueError("backend observation projection differs")
        readback_names = ["before", "applied", "rolled_back", "drifted", "after_stale_readback"]
        if protocol.get('enterprise_authority_assertions'):
            readback_names += [n for n in backend_observed if n.startswith('authority_') and n.endswith(('_before_backend', '_after_backend'))]
        for name in readback_names:
            if name not in backend_observed:
                continue
            snapshot = backend_observed[name]
            match = re.search(r"^Version:\s+(\S+)", snapshot["raw_stdout"], re.MULTILINE)
            if not match or match[1] != snapshot["revision"] or yaml.safe_load(snapshot["raw_stdout"].split("---", 1)[1]) != snapshot["policy"]:
                raise ValueError("independent raw readback projection differs")
        for name, case in {"unassigned_response": "backend_unassigned", "deployed": "backend_submit", "verified": "backend_verify",
                           "rollback": "backend_rollback", "old_receipt": "backend_verify_old_receipt", "stale_response": "backend_stale_submit",
                           "unreachable_attestation": "backend_unreachable_self_report"}.items():
            if name in backend_observed and backend_observed[name] != by_case[case]["body"]:
                raise ValueError("backend HTTP projection differs")
        if any(name in checks for name in backend_assertions):
            backend_results = evaluate_backend(backend_observed)
            if protocol.get('native_enterprise_assertions'):
                from enterprise_runtime import evaluate as evaluate_effects
                backend_results.update(evaluate_effects(backend_observed))
                native = read(run, 'native-enterprise-observations.json')
                if backend_observed['operator_assignment']['assignments'][0]['asset_id'] != native['asset']['id']:
                    raise ValueError('deployment did not use the native-discovered asset')
            if protocol.get('enterprise_authority_assertions'):
                from enterprise_authority import CASES as authority_cases
                from enterprise_authority import evaluate as evaluate_authority
                for case in authority_cases:
                    if backend_observed[case] != by_case[case]['body']:
                        raise ValueError('enterprise authority HTTP projection differs')
                backend_results.update(evaluate_authority(backend_observed))
    if protocol.get("edge_assertions"):
        from edge_governance_scoring import ASSERTIONS, REJECTIONS, evaluate
        if protocol["edge_assertions"] != ASSERTIONS:
            raise ValueError("Edge assertion allocation differs")
        if "edge-observations.json" not in manifest["artifacts"]:
            if any(name in checks for name in ASSERTIONS):
                raise ValueError("Edge assertions lack observations")
        else:
            observations = read(run, "edge-observations.json")
            captured = [e for e in events if e["event"] == "edge_observation"]
            if len({e["name"] for e in captured}) != len(captured) or {e["name"]: e["value"] for e in captured} != observations:
                raise ValueError("Edge observation projection differs")
            for side in ("a", "b"):
                if "registration_" + side in observations:
                    registration = observations["registration_" + side]
                    response = by_case["edge_register_" + side]["body"]
                    if any(registration[key] != response[response_key] for key, response_key in (
                        ("device_id", "edge_agent_id"), ("control_plane_public_key", "control_plane_public_key"),
                        ("environment_id", "environment_id"))):
                        raise ValueError("Edge registration binding differs")
                    if registration["edge_public_key_pem"] != by_case["edge_register_" + side]["request_body"]["public_key_pem"]:
                        raise ValueError("Edge public key differs")
                for obs_name, case_name in (("assets_", "edge_candidates_"), ("evidence_", "edge_evidence_"), ("tasks_", "edge_tasks_")):
                    if obs_name + side in observations and observations[obs_name + side] != by_case[case_name + side]["body"]:
                        raise ValueError("Edge HTTP observation differs")
            if "valid_batches" in observations:
                for side in ("a", "b"):
                    if observations["valid_batches"][side] != by_case["edge_upload_" + side]["request_body"]:
                        raise ValueError("Edge signature inputs differ from actual request")
            if "rejections" in observations and observations["rejections"] != {name: by_case[name]["body"] for name in REJECTIONS}:
                raise ValueError("Edge rejection observation differs")
            if any(name in checks for name in ASSERTIONS):
                edge_results = evaluate(observations)
    if len(checks) != len(summary["checks"]):
        raise ValueError("duplicate assertion")
    if [{k: e[k] for k in ("id", "passed", "observed")} for e in events if e["event"] == "assertion"] != summary["checks"]:
        raise ValueError("assertion projection differs")
    recomputed = {case: row["status"] == protocol["expected_status"][case] for case, row in by_case.items()}
    for name, value in checks.items():
        observed = value["observed"]
        if name in recomputed:
            if observed != {"status": by_case[name]["status"], "expected": protocol["expected_status"][name]}:
                raise ValueError("status projection differs")
        elif name in edge_results:
            if observed != {"source": "edge-observations.json", "predicate": name}:
                raise ValueError("Edge predicate binding differs")
            recomputed[name] = edge_results[name]
        elif name in backend_results:
            if observed != {"source": "backend-observations.json", "predicate": name}:
                raise ValueError("backend predicate binding differs")
            recomputed[name] = backend_results[name]
        elif name in ui_results:
            if observed != {"source": "ui-observations.json", "predicate": name}:
                raise ValueError("UI predicate binding differs")
            recomputed[name] = ui_results[name]
        elif name in race_results:
            if observed != {"source": "race-observations.json", "predicate": name}:
                raise ValueError("race predicate binding differs")
            recomputed[name] = race_results[name]
        elif name in native_results:
            if observed != {'source': 'native-enterprise-observations.json', 'predicate': name}:
                raise ValueError('native predicate binding differs')
            recomputed[name] = native_results[name]
        elif name in risk_results:
            if observed != {'source': 'risk-observations.json', 'predicate': name}:
                raise ValueError('risk predicate binding differs')
            recomputed[name] = risk_results[name]
        elif name in ("migration_1", "migration_2"):
            recomputed[name] = observed == {"exit_code": 0}
        elif name == "migration_head":
            recomputed[name] = observed == [["0028"]]
        elif name in ("list_a_isolated", "list_b_isolated"):
            side = name.split("_")[1]
            own = by_case["create_" + side]["body"]["id"]
            values = by_case["list_" + side]["body"]
            recomputed[name] = isinstance(values, list) and [v["id"] for v in values] == [own]
        elif name in ("denied_environment_writes_no_effect", "denied_approvals_no_effect",
                      "approval_audit_failure_atomic_rollback", "create_audit_failure_atomic_rollback"):
            recomputed[name] = observed["before"] == observed["after"]
            if name == "approval_audit_failure_atomic_rollback":
                recomputed[name] &= observed["before"]["change"] == [["proposed", None]]
        elif name == "approved_with_audit_and_outbox":
            recomputed[name] = observed["change"] == [["approved", "independent-reviewer"]] and (
                ["change.approve", "independent-reviewer"] in observed["audit"]) and sum(
                    row[0] == "policy.change.approved.v1" for row in observed["outbox"]) == 1
        elif name == "repeat_approval_no_duplicate":
            recomputed[name] = observed == checks["approved_with_audit_and_outbox"]["observed"]
        elif name in ("audit_a_isolated", "audit_b_isolated"):
            side = name.split("_")[1]
            values = by_case["audit_" + side]["body"]
            if observed != values:
                raise ValueError("audit projection differs")
            foreign = "operator-b" if side == "a" else "operator-a"
            recomputed[name] = isinstance(values, list) and bool(values) and all(v["actor_id"] != foreign for v in values)
        else:
            raise ValueError("unknown assertion: " + name)
        if value["passed"] is not recomputed[name]:
            raise ValueError("assertion outcome differs: " + name)
    if set(recomputed) != set(checks):
        raise ValueError("assertion coverage differs")
    missing = sorted(set(protocol["expected_status"]) - set(by_case))
    if summary["missing"] != missing or summary["http_case_count"] != len(rows):
        raise ValueError("allocation projection differs")
    if not summary["failure"] and not missing and len(checks) != len(protocol["expected_status"]) + 13 + len(protocol.get("edge_assertions", [])) + len(protocol.get("backend_assertions", [])) + len(protocol.get("ui_assertions", [])) + len(protocol.get("race_assertions", [])) + len(protocol.get('native_enterprise_assertions', [])) + len(protocol.get('risk_assertions', [])):
        raise ValueError("required SQL/identity assertions absent")
    cleanup = [e for e in events if e["event"] == "cleanup"]
    if len(cleanup) != 1 or any(cleanup[0].get(k) != v for k, v in summary["cleanup"].items()):
        raise ValueError("cleanup projection differs")
    failure_events = [e for e in events if e["event"] == "runner_failure"]
    if ([e["exception_type"] for e in failure_events] or [None]) != [summary["failure"]]:
        raise ValueError("failure projection differs")
    expected_cleanup = {"api_stopped": True, "jwks_stopped": True, "owned_container_removed": True}
    if protocol.get("backend_assertions"):
        expected_cleanup["openshell_cleaned"] = True
        details = read(run, "backend-cleanup.json")
        actual = details.get("gateway_stopped") is True and details.get("network_removed") is True and (
            details.get("container_inventory_checked") is True) and all(x["removed"] for x in details["containers"])
        if protocol.get('native_enterprise_assertions'):
            actual = actual and details.get('receiver_removed') is True
        if summary["cleanup"].get("openshell_cleaned") != actual:
            raise ValueError("backend cleanup projection differs")
    passed = not summary["failure"] and not missing and all(recomputed.values()) and summary["cleanup"] == expected_cleanup
    if summary["passed"] is not passed:
        raise ValueError("overall outcome differs")
    if "database-final.json" in manifest["artifacts"]:
        final = read(run, "database-final.json")
        if final["approval"] != checks["repeat_approval_no_duplicate"]["observed"]:
            raise ValueError("final SQL approval state differs")
    return {"integrity_verified": True, "run_id": summary["run_id"], "passed": passed,
            "http_cases": len(rows), "checks": len(checks), "checks_passed": sum(recomputed.values()),
            "missing": missing, "limits": ["recomputes author HTTP and SQL captures, not independent execution attestation",
                                          "tokens excluded; real issuer verification needs independent rerun"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "verify"])
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = export(args.run, args.expected_manifest_sha256, args.output) if args.action == "export" else verify(
        args.run, args.expected_manifest_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
