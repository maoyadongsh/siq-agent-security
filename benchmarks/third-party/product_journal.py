"""Canonical lifecycle adapter for the five registered real product sample pairs."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from common import safe_path, sha256, utc_now, write_json
from lifecycle import Journal, process_identity, process_state, project, summarize
from process_resources import identity, members, stop_owned
from product_samples import (
    approval_case,
    effect_case,
    preserved_oracle_score,
    recipient_case,
)


def preflight(path):
    p = json.loads(path.read_text())
    if p["schema_version"] != "siq-evaluation-protocol/v2" or p["operation"] != "product_samples" or p["track"] != "B":
        raise ValueError("unregistered product journal scope")
    if p["model_calls_enabled"] is not False or p["max_attempts"] != 2:
        raise ValueError("unsupported product journal budget")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", p["run_id"]):
        raise ValueError("invalid run ID")
    required = {"run.py", "common.py", "lifecycle.py", "product_journal.py", "process_resources.py", "product_samples.py", "schemas/case.v1.schema.json"}
    if not required <= set(p["harness_sources"]):
        raise ValueError("incomplete frozen harness")
    if not {"scripts/validate-mcp-provenance.py", "scripts/validate-intent-v2-hermes.py", "benchmarks/runtime-security/evidence.py"} <= set(p["candidate_sources"]):
        raise ValueError("incomplete candidate source identity")
    if sha256(Path(p["binary"])) != p["binary_sha256"] or p["candidate_digest"] != p["binary_sha256"]:
        raise ValueError("product binary identity differs")
    for name, digest in p["candidate_sources"].items():
        if sha256(safe_path(Path(p["candidate_root"]), name)) != digest:
            raise ValueError("candidate fixture source changed")
    for name, digest in p["harness_sources"].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError("use frozen product journal harness")
    if not p["allocation"] or len({u["unit_id"] for u in p["allocation"]}) != len(p["allocation"]):
        raise ValueError("empty or duplicate product allocation")
    if p.get("sample_set") in {"issuer-ingress-v1", "issuer-ingress-v2"}:
        from issuer_ingress import validate
        validate(p)
    elif p.get("sample_set") == "binding-isolation-v1":
        from binding_isolation import validate
        validate(p)
    elif p.get("sample_set") in {"revocation-boundary-v1", "revocation-boundary-v2"}:
        from revocation_boundary import allocation
        if p["allocation"] != allocation(int(p["sample_set"][-1])) or "revocation_boundary.py" not in p["harness_sources"]:
            raise ValueError("registered revocation boundary allocation required")
    elif p.get("sample_set") in {"observer-recovery-v1", "observer-recovery-v2"}:
        from observer_recovery import allocation
        if p["allocation"] != allocation(int(p["sample_set"][-1])) or "observer_recovery.py" not in p["harness_sources"]:
            raise ValueError("registered observer recovery allocation required")
    elif p.get("sample_set") == "effect-time-v1":
        from effect_authorization_time import allocation
        if p["allocation"] != allocation() or "effect_authorization_time.py" not in p["harness_sources"]:
            raise ValueError("registered effect time allocation required")
    elif p.get("sample_set") in {"hold-recovery-v1", "hold-recovery-v2"}:
        from hold_recovery import allocation
        if p["allocation"] != allocation(int(p["sample_set"][-1])) or "hold_recovery.py" not in p["harness_sources"]:
            raise ValueError("registered recovery allocation required")
    elif p.get("sample_set") in {"hold-concurrency-v1", "hold-concurrency-v2", "hold-concurrency-v3"}:
        from hold_concurrency import allocation
        if p["allocation"] != allocation(int(p["sample_set"][-1])) or "hold_concurrency.py" not in p["harness_sources"]:
            raise ValueError("registered hold race allocation required")
    elif p.get("sample_set") in {"provenance-bindings-v1", "provenance-bindings-v2"}:
        from provenance_bindings import allocation
        if p["allocation"] != allocation(int(p["sample_set"][-1])) or "provenance_bindings.py" not in p["harness_sources"]:
            raise ValueError("registered provenance binding allocation required")
    else:
        if any(u["family_id"] not in {"PB01", "AU01", "AU04", "EV01", "EV08"} for u in p["allocation"]):
            raise ValueError("unregistered product family")
        if len(p["allocation"]) != 10 or {(u["family_id"], u["condition"]) for u in p["allocation"]} != {
                (family, condition) for family in ("PB01", "AU01", "AU04", "EV01", "EV08") for condition in ("benign", "adversarial")}:
            raise ValueError("registered ten-sample allocation required")
    if p.get("pause_after") is not None and p["pause_after"] not in {u["unit_id"] for u in p["allocation"]}:
        raise ValueError("unallocated interruption checkpoint")
    return p


def projection(result, prefix):
    observation = result.get("observation", {})
    completion, decision = result.get("completion") or {}, result.get("decision") or {}
    harm, utility = result.get("harm_observed"), result.get("utility_completed")
    oracle_ref = prefix + "/oracle.json"
    return {"harm_observed": harm, "utility_completed": utility,
            "harm_unknown_reason": None if harm is not None else "oracle_not_captured",
            "utility_unknown_reason": None if utility is not None else "oracle_coverage_incomplete",
            "harm_evidence_refs": [oracle_ref] if harm is not None else [],
            "utility_evidence_refs": [oracle_ref] if utility is not None else [],
            "tool_executed": result.get("tool_executed"), "decision_action": decision.get("action"),
            "siq_completion": completion.get("status"), "siq_reason_code": completion.get("reason_code", decision.get("reason_code")),
            "oracle": {"source": observation.get("source", "evaluator_file_oracle"),
                       "coverage": "full" if observation.get("healthy") else "unknown",
                       "healthy": observation.get("healthy"), "window_start": None, "window_end": None,
                       "materials": [oracle_ref] if observation else []}}


def observe(journal, key, result, prefix):
    updates = projection(result, prefix)
    if any(a["pass"] is False for a in result.get("assertions", [])):
        updates["assertion_status"] = "fail"
    journal.transition(key, "observed", **updates)


def reconcile(journal):
    out = journal.root
    for key, row in list(journal.states.items()):
        if row["lifecycle"] not in ("started", "interrupted") or row["cleanup_confirmed"] or process_state(row["process_ref"]) == "alive":
            continue
        prefix = f"attempts/{row['unit_id']}/{row['attempt']}"
        directory = safe_path(out, prefix)
        unit = next(u for u in journal.protocol["allocation"] if u["unit_id"] == row["unit_id"])
        # Read-only recovery precedes terminal bookkeeping, preserving captured harm.
        if row["lifecycle"] == "started" and (directory / "oracle.json").exists():
            recovered = preserved_oracle_score(directory, unit)
            updates = projection(recovered, prefix)
            updates["tool_executed"] = row["tool_executed"]
            for field in ("decision_action", "siq_completion", "siq_reason_code"):
                updates[field] = row[field]
            if (directory / "result.json").exists():
                captured = json.loads((directory / "result.json").read_text())
                if any(a["pass"] is False for a in captured.get("assertions", [])):
                    updates["assertion_status"] = "fail"
            # A product outcome checkpoint is not a terminal completion record.
            updates.update(utility_completed=None, utility_unknown_reason="attempt_interrupted", utility_evidence_refs=[])
            journal.transition(key, "observed", **updates)
        cleanup = {"daemon": None, "remaining_group_members": [], "confirmed": False}
        if (directory / "resource.json").exists():
            resource = json.loads((directory / "resource.json").read_text())
            if resource["owner"] != row["process_ref"] or resource["attempt_id"] != key:
                raise ValueError("resource ownership differs")
            cleanup["daemon"] = stop_owned(resource["daemon"], resource["command_sha256"])
            cleanup["remaining_group_members"] = members(row["process_ref"]["pid"])
            cleanup["confirmed"] = cleanup["daemon"]["stopped"] and not cleanup["remaining_group_members"]
        cleanup["writer_state"] = process_state(row["process_ref"])
        recovery_name = f"recovery-cleanup-{len(list(directory.glob('recovery-cleanup-*.json'))) + 1}.json"
        write_json(directory / recovery_name, cleanup)
        if row["lifecycle"] == "started":
            journal.transition(key, "interrupted", execution_status="interrupted", measurement_status="indeterminate",
                               assertion_status="fail" if journal.states[key]["assertion_status"] == "fail" else "inconclusive",
                               error={"type": "evaluator_interrupted", "detail": process_state(row["process_ref"])})
        if cleanup["confirmed"]:
            journal.transition(key, "cleanup_confirmed", cleanup_confirmed=True,
                               event_trace_refs=[prefix + "/" + recovery_name, prefix + "/resource.json"])


def seal_run(journal):
    out = journal.root
    _, states, _, _ = project(out)
    summary = summarize(states)
    summary["scope"] = json.loads((out / "protocol.json").read_text()).get("sample_scope", "five real component sample pairs; no native host, model or same-UID isolation claim")
    with (out / "cases.jsonl").open("x") as stream:
        for value in states.values():
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")
    write_json(out / "summary.json", summary)
    names = ["protocol.json", "journal.jsonl", "cases.jsonl", "summary.json"]
    if (out / "counter-calibration.json").exists():
        names.append("counter-calibration.json")
    for directory in sorted((out / "attempts").glob("*/*")):
        names += [str(p.relative_to(out)) for p in directory.glob("*.json")]
    write_json(out / "manifest.json", {"schema_version": "siq-product-journal-manifest/v1", "relationship": "author_run",
               "artifacts": {name: sha256(out / name) for name in names}})
    return {**summary, "manifest_sha256": sha256(out / "manifest.json")}


def run(path, out, *, resume=False, retry=None, seal=False):
    p = preflight(path)
    if out.name != p["run_id"]:
        raise ValueError("frozen run ID differs")
    out.resolve().relative_to(Path(p["campaign_root"]) / "private/runs")
    if os.getpgrp() != os.getpid():
        os.setsid()
    os.umask(0o077)
    journal = Journal(out, None if resume else p)
    try:
        if sha256(path) != sha256(out / "protocol.json"):
            raise ValueError("resume protocol mismatch")
        if p.get("sample_set") in {"issuer-ingress-v1", "issuer-ingress-v2", "binding-isolation-v1", "revocation-boundary-v1", "revocation-boundary-v2", "hold-concurrency-v2", "hold-concurrency-v3", "hold-recovery-v1", "hold-recovery-v2", "effect-time-v1", "observer-recovery-v1", "observer-recovery-v2"}:
            calibration = path.parent / "counter-calibration.json"
            if sha256(calibration) != p["contract_binding"]["oracle_calibration"]["sha256"]:
                raise ValueError("registered counter calibration differs")
            target = out / "counter-calibration.json"
            if not target.exists():
                with target.open("xb") as stream:
                    stream.write(calibration.read_bytes())
            elif sha256(target) != sha256(calibration):
                raise ValueError("resumed counter calibration differs")
        reconcile(journal)
        if retry:
            journal.retry(retry)
        candidate = Path(p["candidate_root"])
        sys.path.insert(0, str(candidate / "benchmarks/runtime-security"))
        from evidence import capture
        spec = importlib.util.spec_from_file_location("journal_product_fixture", candidate / "scripts/validate-mcp-provenance.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        for key, row in list(journal.states.items()):
            if row["lifecycle"] != "scheduled":
                continue
            unit = next(u for u in p["allocation"] if u["unit_id"] == row["unit_id"])
            prefix = f"attempts/{row['unit_id']}/{row['attempt']}"
            directory = safe_path(out, prefix)
            directory.mkdir(parents=True)
            state = safe_path(out, f"state-private/{row['unit_id']}/{row['attempt']}")
            state.mkdir(parents=True, mode=0o700)

            class OwnedHarness(fixture.base.Harness):
                def start(self, directory=directory, key=key):
                    super().start()
                    resource = {"attempt_id": key, "owner": process_identity(),
                                "daemon": identity(self.proc.pid), "command_sha256": hashlib.sha256(Path(f"/proc/{self.proc.pid}/cmdline").read_bytes()).hexdigest()}
                    target = directory / "resource.json"
                    if target.exists():
                        old = json.loads(target.read_text())
                        if process_state(old["daemon"]) == "alive":
                            raise ValueError("previous owned daemon still running")
                        write_json(directory / f"resource-retired-{len(list(directory.glob('resource-retired-*.json'))) + 1}.json", old)
                        pending = directory / "resource-next.json"
                        write_json(pending, resource)
                        os.replace(pending, target)
                        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                    else:
                        write_json(target, resource)

            h = OwnedHarness(state, SimpleNamespace(binary=Path(p["binary"])))
            journal.transition(key, "started", execution_status="running", process_ref=process_identity())
            result, error = {}, None
            try:
                if unit.get("issuer_ingress_sample"):
                    from issuer_ingress import run_case
                    result = run_case(h, fixture.base, unit, directory, candidate)
                elif unit.get("binding_isolation_sample"):
                    from binding_isolation import run_case
                    result = run_case(h, fixture.base, unit, directory, candidate)
                elif unit.get("revocation_boundary_sample"):
                    from revocation_boundary import run_case
                    result = run_case(h, fixture.base, unit, directory, candidate)
                elif unit.get("observer_recovery_sample"):
                    from observer_recovery import run_case
                    result = run_case(h, fixture.base, unit, directory, candidate)
                elif unit.get("temporal_effect_sample"):
                    from effect_authorization_time import run_case
                    result = run_case(h, fixture.base, unit, directory, candidate)
                elif unit.get("recovery_sample"):
                    from hold_recovery import run_case
                    result = run_case(h, fixture.base, unit, directory, candidate)
                elif unit.get("hold_race_sample"):
                    from hold_concurrency import run_case
                    result = run_case(h, fixture.base, unit, directory, candidate)
                elif unit.get("binding_sample"):
                    from provenance_bindings import run_case
                    result = run_case(h, fixture.base, unit, directory)
                elif unit["family_id"] in ("EV01", "EV08"):
                    result = effect_case(h, fixture.base, unit, directory)
                elif unit["family_id"] in ("AU01", "AU04"):
                    result = approval_case(h, fixture.base, unit, directory, candidate)
                else:
                    result = recipient_case(h, fixture.base, unit, directory)
                write_json(directory / "result.json", result)
                write_json(directory / "product-evidence.json", capture(h, unit["unit_id"]))
                observe(journal, key, result, prefix)
                if p.get("pause_after") == row["unit_id"] and row["attempt"] == 1:
                    time.sleep(45)  # explicit bounded external interruption window
            except Exception as exc:  # noqa: BLE001 -- preserve outcome and stop only our daemon
                error = {"type": type(exc).__name__, "detail": "registered product sample failed"}
                if (directory / "oracle.json").exists():
                    recovered = preserved_oracle_score(directory, unit)
                    result.update(recovered)
                    observe(journal, key, result, prefix)
            finally:
                try:
                    if not (directory / "product-evidence.json").exists():
                        write_json(directory / "product-evidence.json", capture(h, unit["unit_id"]))
                except Exception as exc:  # noqa: BLE001 -- evidence absence must remain inconclusive
                    error = {"type": type(exc).__name__, "detail": "product evidence capture failed"}
                h.stop()
                cleanup = {"remaining_group_members": members(os.getpid(), exclude=(os.getpid(),)), "daemon_stopped": h.proc is None}
                cleanup["confirmed"] = cleanup["daemon_stopped"] and not cleanup["remaining_group_members"]
                write_json(directory / "cleanup.json", cleanup)
            assertions = result.get("assertions", [])
            status = "fail" if any(a["pass"] is False for a in assertions) else "inconclusive" if error or not cleanup["confirmed"] or not assertions else "pass"
            journal.transition(key, "finished", execution_status="error" if error else "completed",
                               measurement_status="indeterminate" if error else result.get("measurement_status", "determinate"),
                               assertion_status=status, error=error, cleanup_confirmed=cleanup["confirmed"],
                               receipt_refs=[prefix + "/product-evidence.json"] if (directory / "product-evidence.json").exists() else [],
                               product_observer_refs=[prefix + "/result.json"] if result.get("product_observer") else [],
                               event_trace_refs=[prefix + "/cleanup.json"], **projection(result, prefix))
        summary = seal_run(journal) if seal else summarize(project(out)[1])
        print(json.dumps(summary), flush=True)
        return summary["outcome_exit_code"]
    finally:
        journal.close()


def freeze(campaign, run_id, pause_after=None, sample_set=None):
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", run_id):
        raise ValueError("invalid run ID")
    campaign = campaign.resolve()
    old = json.loads((campaign / "data/B-five-samples-002/protocol.json").read_text())
    root = campaign / "protocols" / (run_id + "-protocol")
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    names = ["run.py", "common.py", "lifecycle.py", "product_journal.py", "process_resources.py", "product_samples.py", "schemas/case.v1.schema.json"]
    names += ["issuer_ingress.py", "binding_isolation.py", "provenance_bindings.py", "hold_concurrency.py", "hold_bound_authority.py", "hold_recovery.py", "effect_authorization_time.py", "observer_recovery.py", "revocation_boundary.py"]
    names += [str(p.relative_to(source)) for directory in ("oracles", "analysis", "product_observers") for p in (source / directory).glob("*.py")]
    for name in names:
        target = root / "harness-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    allocation = [{**u, "case_id": u["unit_id"], "pair_id": u["family_id"], "task_block_id": u["family_id"],
                   "track": "B", "claim_ids": [], "product_group_ids": [u["product_group_id"]]} for u in old["allocation"]]
    sample_scope = "five real component sample pairs; no native host, model or same-UID isolation claim"
    if sample_set in {"issuer-ingress-v1", "issuer-ingress-v2"}:
        from issuer_ingress import SAMPLE_SCOPE
        from issuer_ingress import allocation as ingress_allocation
        allocation, sample_scope = ingress_allocation(int(sample_set[-1])), SAMPLE_SCOPE
    elif sample_set == "binding-isolation-v1":
        from binding_isolation import SAMPLE_SCOPE
        from binding_isolation import allocation as scope_allocation
        allocation, sample_scope = scope_allocation(), SAMPLE_SCOPE
    elif sample_set in {"revocation-boundary-v1", "revocation-boundary-v2"}:
        from revocation_boundary import SAMPLE_SCOPE
        from revocation_boundary import allocation as boundary_allocation
        allocation, sample_scope = boundary_allocation(int(sample_set[-1])), SAMPLE_SCOPE
        if sample_set.endswith("v2"):
            from revocation_boundary import INTENT_SCOPE
            sample_scope = INTENT_SCOPE
    elif sample_set in {"observer-recovery-v1", "observer-recovery-v2"}:
        from observer_recovery import SAMPLE_SCOPE
        from observer_recovery import allocation as observer_allocation
        allocation, sample_scope = observer_allocation(int(sample_set[-1])), SAMPLE_SCOPE
    elif sample_set == "effect-time-v1":
        from effect_authorization_time import SAMPLE_SCOPE
        from effect_authorization_time import allocation as temporal_allocation
        allocation, sample_scope = temporal_allocation(), SAMPLE_SCOPE
    elif sample_set in {"hold-recovery-v1", "hold-recovery-v2"}:
        from hold_recovery import SAMPLE_SCOPE
        from hold_recovery import allocation as recovery_allocation
        allocation, sample_scope = recovery_allocation(int(sample_set[-1])), SAMPLE_SCOPE
        if sample_set.endswith("v2"):
            sample_scope += "; actual observe reply loss after backend persistence"
    elif sample_set in {"hold-concurrency-v1", "hold-concurrency-v2", "hold-concurrency-v3"}:
        from hold_concurrency import SAMPLE_SCOPE
        from hold_concurrency import allocation as race_allocation
        allocation, sample_scope = race_allocation(int(sample_set[-1])), SAMPLE_SCOPE
        if sample_set.endswith("v3"):
            from hold_bound_authority import SCOPE
            sample_scope = SCOPE
    elif sample_set in {"provenance-bindings-v1", "provenance-bindings-v2"}:
        from provenance_bindings import SAMPLE_SCOPE
        from provenance_bindings import allocation as binding_allocation
        allocation, sample_scope = binding_allocation(2 if sample_set.endswith("v2") else 1), SAMPLE_SCOPE
    elif sample_set is not None:
        raise ValueError("unsupported sample set")
    if pause_after:
        allocation.sort(key=lambda u: u["unit_id"] != pause_after)
    candidate = Path(old["candidate_root"])
    candidate_sources = {str(p.relative_to(candidate)): sha256(p) for p in (candidate / "scripts").glob("*.py")}
    candidate_sources.update({str(p.relative_to(candidate)): sha256(p) for p in (candidate / "benchmarks/runtime-security").glob("*.py")})
    protocol = {"schema_version": "siq-evaluation-protocol/v2", "run_id": run_id, "operation": "product_samples",
                "track": "B", "relationship": "author_run", "measurement_kind": "product_component_samples",
                "campaign_root": str(campaign), "candidate_root": str(candidate), "candidate_sources": candidate_sources,
                "binary": old["binary"], "binary_sha256": old["binary_sha256"], "candidate_digest": old["binary_sha256"],
                "allocation": allocation, "sample_set": sample_set, "sample_scope": sample_scope, "model_calls_enabled": False, "max_attempts": 2, "pause_after": pause_after,
                "harness_sources": {name: sha256(root / "harness-source" / name) for name in names}, "frozen_at": utc_now(),
                "limits": {"scope": "registered loopback components; no native host", "same_uid_tamper_resistance": False}}
    if sample_set in {"hold-concurrency-v2", "hold-concurrency-v3"}:
        from hold_concurrency_registration import register
        protocol.update(register(root, candidate, version=int(sample_set[-1])))
        protocol["candidate_sources"].update(protocol["contract_binding"]["contract_path_and_digest"])
    if sample_set in {"hold-recovery-v1", "hold-recovery-v2"}:
        from hold_recovery import register
        protocol.update(register(root, candidate, version=int(sample_set[-1])))
        protocol["candidate_sources"].update(protocol["contract_binding"]["contract_path_and_digest"])
    if sample_set == "effect-time-v1":
        from effect_authorization_time import register
        protocol.update(register(root, candidate))
        protocol["candidate_sources"].update(protocol["contract_binding"]["contract_path_and_digest"])
    if sample_set in {"observer-recovery-v1", "observer-recovery-v2"}:
        from observer_recovery import register
        protocol.update(register(root, candidate, version=int(sample_set[-1])))
        protocol["candidate_sources"].update(protocol["contract_binding"]["contract_path_and_digest"])
    if sample_set in {"revocation-boundary-v1", "revocation-boundary-v2"}:
        from revocation_boundary import register
        protocol.update(register(root, candidate, version=int(sample_set[-1])))
        protocol["candidate_sources"].update(protocol["contract_binding"]["contract_path_and_digest"])
    if sample_set == "binding-isolation-v1":
        from binding_isolation import register, validate
        protocol.update(register(root, candidate))
        protocol["candidate_sources"].update(protocol["contract_binding"]["contract_path_and_digest"])
        validate(protocol)
    if sample_set in {"issuer-ingress-v1", "issuer-ingress-v2"}:
        from issuer_ingress import register, validate
        protocol.update(register(root, candidate, version=int(sample_set[-1])))
        protocol["candidate_sources"].update(protocol["contract_binding"]["contract_path_and_digest"])
        validate(protocol)
    write_json(root / "protocol.json", protocol)
    write_json(root / "local-anchor.json", {"sha256": sha256(root / "protocol.json")})
    print(json.dumps({"protocol": str(root / "protocol.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--pause-after")
    parser.add_argument("--sample-set", choices=["issuer-ingress-v1", "issuer-ingress-v2", "binding-isolation-v1", "revocation-boundary-v1", "revocation-boundary-v2", "observer-recovery-v1", "observer-recovery-v2", "effect-time-v1", "hold-recovery-v1", "hold-recovery-v2", "provenance-bindings-v1", "provenance-bindings-v2", "hold-concurrency-v1", "hold-concurrency-v2", "hold-concurrency-v3"])
    args = parser.parse_args()
    freeze(args.campaign.resolve(), args.run_id, args.pause_after, args.sample_set)
