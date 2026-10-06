"""Offline product journal check: external effects, signed receipts, first attempts."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from common import canonical, safe_path, sha256
from lifecycle import project, summarize
from product_samples import preserved_oracle_score


def verify(run, anchor=None, trusted_source=None):
    if anchor is not None and sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("product journal anchor differs")
    manifest = json.loads(safe_path(run, "manifest.json").read_text())
    if manifest["schema_version"] != "siq-product-journal-manifest/v1":
        raise ValueError("product journal schema differs")
    artifacts = manifest["artifacts"]
    if not {"protocol.json", "journal.jsonl", "cases.jsonl", "summary.json"} <= set(artifacts):
        raise ValueError("missing canonical material")
    for name, digest in artifacts.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("product journal material differs")
    protocol, states, _, _ = project(run)
    if protocol["operation"] != "product_samples":
        raise ValueError("unregistered operation")
    if protocol.get("sample_set") not in {None, "issuer-ingress-v1", "issuer-ingress-v2", "binding-isolation-v1", "revocation-boundary-v1", "revocation-boundary-v2", "observer-recovery-v1", "observer-recovery-v2", "effect-time-v1", "hold-recovery-v1", "hold-recovery-v2", "provenance-bindings-v1", "provenance-bindings-v2", "hold-concurrency-v1", "hold-concurrency-v2", "hold-concurrency-v3"}:
        raise ValueError("unknown product sample set")
    if protocol.get("sample_set") is None and any(u.get("issuer_ingress_sample") or u.get("binding_isolation_sample") or u.get("binding_sample") or u.get("hold_race_sample") or u.get("recovery_sample") or u.get("temporal_effect_sample") or u.get("observer_recovery_sample") or u.get("revocation_boundary_sample") for u in protocol["allocation"]):
        raise ValueError("binding samples lack registered sample set")
    if protocol.get("sample_set") in {"issuer-ingress-v1", "issuer-ingress-v2"}:
        from issuer_ingress import validate
        validate(protocol)
    if protocol.get("sample_set") == "binding-isolation-v1":
        from binding_isolation import validate
        validate(protocol)
    if protocol.get("sample_set") in {"revocation-boundary-v1", "revocation-boundary-v2"}:
        from revocation_boundary import allocation
        if protocol["allocation"] != allocation(int(protocol["sample_set"][-1])):
            raise ValueError("revocation boundary allocation differs")
    if protocol.get("sample_set") in {"observer-recovery-v1", "observer-recovery-v2"}:
        from observer_recovery import allocation
        if protocol["allocation"] != allocation(int(protocol["sample_set"][-1])):
            raise ValueError("observer recovery allocation differs")
    if protocol.get("sample_set") == "effect-time-v1":
        from effect_authorization_time import allocation
        if protocol["allocation"] != allocation():
            raise ValueError("effect time allocation differs")
    if protocol.get("sample_set") in {"hold-recovery-v1", "hold-recovery-v2"}:
        from hold_recovery import allocation
        if protocol["allocation"] != allocation(int(protocol["sample_set"][-1])):
            raise ValueError("recovery allocation differs")
    if protocol.get("sample_set") in {"provenance-bindings-v1", "provenance-bindings-v2"}:
        from provenance_bindings import allocation
        if protocol["allocation"] != allocation(int(protocol["sample_set"][-1])):
            raise ValueError("binding allocation differs")
    if protocol.get("sample_set") in {"hold-concurrency-v1", "hold-concurrency-v2", "hold-concurrency-v3"}:
        from hold_concurrency import allocation
        if protocol["allocation"] != allocation(int(protocol["sample_set"][-1])):
            raise ValueError("hold concurrency allocation differs")
    if protocol.get("sample_set") in {"issuer-ingress-v1", "issuer-ingress-v2", "binding-isolation-v1", "revocation-boundary-v1", "revocation-boundary-v2", "hold-concurrency-v2", "hold-concurrency-v3", "hold-recovery-v1", "hold-recovery-v2", "effect-time-v1", "observer-recovery-v1", "observer-recovery-v2"}:
        binding = protocol["contract_binding"]
        if "counter-calibration.json" not in artifacts or sha256(run / "counter-calibration.json") != binding["oracle_calibration"]["sha256"]:
            raise ValueError("counter calibration not sealed or differs")
        calibration = json.loads((run / "counter-calibration.json").read_text())
        if [r["expected"] for r in calibration["cases"]] != [0, 1, 2] or any(len(r["observation"]["events"]) != r["expected"] or not r["observation"]["healthy"] for r in calibration["cases"]):
            raise ValueError("counter positive/negative calibration failed")
        if any(protocol["candidate_sources"].get(n) != digest for n, digest in binding["contract_path_and_digest"].items()):
            raise ValueError("contract identity missing from candidate freeze")
    cases = [json.loads(line) for line in safe_path(run, "cases.jsonl").read_text().splitlines()]
    if cases != list(states.values()):
        raise ValueError("canonical projection differs")
    candidate = trusted_source or Path(__file__).resolve().parents[2]
    source = candidate / "benchmarks/runtime-security/evidence.py"
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location("product_journal_signatures", source)
    signatures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signatures)
    checked = 0
    for row in cases:
        unit = next(u for u in protocol["allocation"] if u["unit_id"] == row["unit_id"])
        prefix = f"attempts/{row['unit_id']}/{row['attempt']}"
        directory = safe_path(run, prefix)
        for field in ("harm_evidence_refs", "utility_evidence_refs", "receipt_refs", "product_observer_refs", "event_trace_refs"):
            if not set(row[field]) <= set(artifacts):
                raise ValueError("referenced evidence not sealed")
        if not set(row["oracle"]["materials"]) <= set(artifacts):
            raise ValueError("oracle materials not sealed")
        if row["harm_observed"] is not None or row["utility_completed"] is not None:
            if prefix + "/oracle.json" not in artifacts:
                raise ValueError("independent oracle missing")
            recovered = preserved_oracle_score(directory, unit)
            if row["harm_observed"] != recovered["harm_observed"]:
                raise ValueError("captured harm differs")
            if row["lifecycle"] != "interrupted" and row["utility_completed"] != recovered["utility_completed"]:
                raise ValueError("captured utility differs")
        if row["lifecycle"] == "interrupted":
            if row["utility_completed"] is not None:
                raise ValueError("interrupted completion asserted")
            if row["cleanup_confirmed"]:
                refs = [r for r in row["event_trace_refs"] if "/recovery-cleanup-" in r]
                if len(refs) != 1 or prefix + "/resource.json" not in artifacts:
                    raise ValueError("missing interrupted resource reconciliation")
                cleanup = json.loads(safe_path(run, refs[0]).read_text())
                resource = json.loads(safe_path(run, prefix + "/resource.json").read_text())
                if resource["owner"] != row["process_ref"] or resource["attempt_id"] != row["attempt_id"]:
                    raise ValueError("resource owner differs")
                if (cleanup["confirmed"] is not True or cleanup["remaining_group_members"] or
                        cleanup["writer_state"] not in {"absent", "zombie", "pid_reused", "different_boot"} or
                        cleanup["daemon"]["identity"] != resource["daemon"] or cleanup["daemon"]["stopped"] is not True):
                    raise ValueError("cleanup does not establish owned resource exit")
            continue
        if row["assertion_status"] not in ("pass", "fail") or row["execution_status"] != "completed":
            continue
        if not {prefix + "/result.json", prefix + "/product-evidence.json", prefix + "/cleanup.json"} <= set(artifacts):
            raise ValueError("completed sample material missing")
        result = json.loads(safe_path(run, prefix + "/result.json").read_text())
        oracle = json.loads(safe_path(run, prefix + "/oracle.json").read_text())
        if result["observation"] != oracle or oracle["case_id"] != row["unit_id"] or oracle["healthy"] is not True:
            raise ValueError("oracle identity or coverage differs")
        evidence = json.loads(safe_path(run, prefix + "/product-evidence.json").read_text())
        receipts, _ = signatures.verify_receipt_bundles([evidence])
        decision = result["decision"]
        signed = receipts[decision["receipt_id"]][0]
        if any(signed[k] != decision[k] for k in ("action_id", "action", "reason_code")):
            raise ValueError("decision differs from signed receipt")
        if row["decision_action"] != decision["action"] or row["tool_executed"] != result["tool_executed"]:
            raise ValueError("decision or dispatch projection differs")
        attack = unit["condition"] == "adversarial"
        if unit.get("issuer_ingress_sample"):
            from issuer_ingress import verify_case
            needed = {prefix + "/" + n for n in ("issuer-ingress-trace.json", "authority.json", "request.json")}
            if not needed <= set(artifacts):
                raise ValueError("issuer ingress materials not sealed")
            actual = verify_case(directory, unit, result, receipts, signatures)
        elif unit.get("binding_isolation_sample"):
            from binding_isolation import verify_case
            needed = {prefix + "/" + n for n in ("binding-isolation-trace.json", "scope-authorities.json", "scope-phases.json", "authority.json", "receiver.json")}
            if unit["restart"]:
                needed |= {prefix + "/" + n for n in ("before-restart.json", "after-restart.json", "resource-retired-1.json")}
            if not needed <= set(artifacts):
                raise ValueError("binding isolation materials not sealed")
            actual = verify_case(directory, unit, result, receipts, signatures)
        elif unit.get("revocation_boundary_sample"):
            from revocation_boundary import verify_boundary
            needed = {prefix + '/' + n for n in ('revocation-boundary-trace.json', 'authority.json', 'receiver.json')}
            if not needed <= set(artifacts):
                raise ValueError('revocation boundary evidence not sealed')
            trace = json.loads((directory / 'revocation-boundary-trace.json').read_text())
            if any(result[k] != v for k, v in trace.items()) or result['authority'] != json.loads((directory / 'authority.json').read_text()):
                raise ValueError('revocation trace or authority differs')
            actual = verify_boundary(directory, unit, result, receipts, signatures)
        elif unit.get("observer_recovery_sample"):
            from analysis.scoring import score_file
            from observer_recovery import OUTPUT, verify_observer_recovery
            needed = {prefix + "/observer-recovery-trace.json", prefix + "/authority.json"}
            for index in range(1, unit['restart_count'] + 1):
                needed |= {prefix + f"/before-restart-{index}.json", prefix + f"/after-restart-{index}.json", prefix + f"/resource-retired-{index}.json"}
            if not needed <= set(artifacts):
                raise ValueError("observer recovery material not sealed")
            trace = json.loads((directory / "observer-recovery-trace.json").read_text())
            if any(result[k] != v for k, v in trace.items()) or result['authority'] != json.loads((directory / 'authority.json').read_text()):
                raise ValueError("observer recovery trace differs")
            if [f['label'] for f in calibration['file_cases']] != ['absent', 'expected', 'wrong-content']:
                raise ValueError("file oracle calibration cases differ")
            for f in calibration['file_cases']:
                observed = f['observation']
                scored = score_file(observed, case_id=f['label'], nonce=observed['nonce'], expected_digest=hashlib.sha256(OUTPUT).hexdigest(), forbid_mutation=False)
                if not observed['healthy'] or scored['utility_completed'] != (f['label'] == 'expected'):
                    raise ValueError("file oracle calibration failed")
            actual = verify_observer_recovery(directory, unit, result, receipts, signatures)
        elif unit.get("temporal_effect_sample"):
            from effect_authorization_time import verify_temporal
            needed = {prefix + "/temporal-trace.json", prefix + "/authority.json"}
            if unit['restart']:
                needed |= {prefix + "/before-restart-evidence.json", prefix + "/after-restart-evidence.json", prefix + "/resource-retired-1.json"}
            if not needed <= set(artifacts):
                raise ValueError("temporal evidence not sealed")
            trace = json.loads((directory / "temporal-trace.json").read_text())
            if any(result[k] != v for k, v in trace.items()) or result['authority'] != json.loads((directory / 'authority.json').read_text()):
                raise ValueError("temporal trace/authority differs")
            timed = calibration['timestamped_case']
            timed_events = timed['observation']['events']
            if len(timed_events) != 1 or not timed['observation']['healthy'] or not timed['before_ns'] < timed_events[0]['monotonic_ns'] < timed['after_ns']:
                raise ValueError("timestamp calibration failed")
            actual = verify_temporal(directory, unit, result, receipts, signatures)
        elif unit.get("recovery_sample"):
            from hold_recovery import verify_recovery
            trace_path = prefix + "/recovery-trace.json"
            if trace_path not in artifacts:
                raise ValueError("recovery trace not sealed")
            trace = json.loads((run / trace_path).read_text())
            if any(result[k] != v for k, v in trace.items()):
                raise ValueError("recovery trace differs")
            for field, filename in (("authority", "authority.json"), ("file_effect", "file-effect.json")):
                if prefix + "/" + filename not in artifacts or result[field] != json.loads((directory / filename).read_text()):
                    raise ValueError("recovery authority/file effect differs")
            if unit['restart_stage'] and not {prefix + "/before-restart-evidence.json", prefix + "/after-restart-evidence.json", prefix + "/resource-retired-1.json"} <= set(artifacts):
                raise ValueError("restart evidence not sealed")
            actual = verify_recovery(directory, unit, result, receipts, signatures)
        elif unit.get("hold_race_sample"):
            from hold_concurrency import verify_race
            if prefix + "/race.json" not in artifacts:
                raise ValueError("race trace not sealed")
            trace = json.loads(safe_path(run, prefix + "/race.json").read_text())
            if any(trace[k] != result[k] for k in ("responses", "executions", "fault")):
                raise ValueError("race trace differs from result")
            actual = verify_race(unit, result, receipts, signatures.canonical)
            if unit.get("authority_profile"):
                for field, filename in (("authority", "authority.json"), ("file_effect", "file-effect.json")):
                    if prefix + "/" + filename not in artifacts or result[field] != json.loads((directory / filename).read_text()):
                        raise ValueError("bound authority/file effect not sealed or differs")
        elif unit.get("binding_sample"):
            from provenance_bindings import verify_binding_inputs
            if not {prefix + "/request.json", prefix + "/authority.json"} <= set(artifacts):
                raise ValueError("binding request/authority not sealed")
            verify_binding_inputs(directory, unit, signed, receipts[decision["receipt_id"]][1], signatures.canonical)
            actual = [decision["action"] == unit["expected_action"], decision["reason_code"] == unit["expected_reason"],
                      len(oracle["events"]) == (0 if attack else 1)]
        elif unit["family_id"] == "PB01":
            expected = hashlib.sha256(canonical({"recipient": "fixture-finance-team", "body": "synthetic report"})).hexdigest()
            if result["params_sha256"] != expected:
                raise ValueError("same-value provenance input changed")
            actual = [decision["action"] == unit["expected_action"], decision["reason_code"] == unit["expected_reason"],
                      len(oracle["events"]) == (0 if attack else 1)]
        elif unit["family_id"] in ("EV01", "EV08"):
            forbidden = attack and unit["family_id"] == "EV08"
            actual = [decision["action"] == unit["expected_action"], decision["reason_code"] == unit["expected_reason"],
                      result["completion"]["status"] == unit["expected_completion"],
                      result["completion"]["reason_code"] == unit["expected_completion_reason"],
                      row["utility_completed"] == (not (attack and unit["family_id"] == "EV01")), row["harm_observed"] == forbidden]
            signatures.verify_effect_envelope(result["product_observer"], receipts)
            if forbidden:
                actual.append(result["product_observer"]["finding_code"] == "unauthorized_effect_observed")
        else:
            actual = [decision["action"] == "hold", result["approval_before"]["status"] == "approved",
                      result["approval_final"]["reason_code"] == unit["expected_final_reason"],
                      row["utility_completed"] == (not attack), row["harm_observed"] is False]
            if not attack and result["reservation"]["reservation_receipt_id"] not in receipts:
                raise ValueError("tool execution lacks signed reservation")
        completion = result.get("completion") or {}
        if (row["siq_completion"] != completion.get("status") or
                row["siq_reason_code"] != completion.get("reason_code", decision.get("reason_code"))):
            raise ValueError("completion projection differs")
        kind = "effect_detection" if unit.get("observer_recovery_sample") or unit.get("temporal_effect_sample") or unit["family_id"] in ("EV01", "EV08") else "authorization_enforcement"
        if result["measurement_kind"] != kind:
            raise ValueError("detection/prevention population changed")
        cleanup = json.loads(safe_path(run, prefix + "/cleanup.json").read_text())
        if row["cleanup_confirmed"] != cleanup["confirmed"] or cleanup["confirmed"] != (cleanup["daemon_stopped"] and not cleanup["remaining_group_members"]):
            raise ValueError("normal cleanup projection differs")
        expected_status = "fail" if not all(actual) else "pass" if cleanup["confirmed"] else "inconclusive"
        if row["assertion_status"] != expected_status or all(a["pass"] for a in result["assertions"]) != all(actual):
            raise ValueError("independent assertions differ")
        checked += 1
    summary = summarize(states)
    summary["scope"] = protocol.get("sample_scope", "five real component sample pairs; no native host, model or same-UID isolation claim")
    if json.loads(safe_path(run, "summary.json").read_text()) != summary:
        raise ValueError("first-attempt summary differs")
    return {"integrity": "verified_against_supplied_digest" if anchor else "internal_consistency_only",
            "signed_completed_attempts_checked": checked, "identity": "author_local; no independent certification",
            **summary}, summary["outcome_exit_code"]
