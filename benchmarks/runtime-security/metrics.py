"""Deterministic aggregation of runner observations, never scenario expectations.

The runner must verify referenced evidence before constructing these records.
This module enforces denominator rules; it is not a signature verifier.
"""
import math
from collections import defaultdict

STAGES = tuple(f"d{i}" for i in range(6))
TIMINGS = (
    "authority_validation", "intent_lookup", "context_validation",
    "provenance_resolution", "runtime_action_normalization", "policy_evaluation",
    "receipt_append_fsync", "effect_evidence_processing",
)


def summarize(records):
    records = list(records)
    buckets = {(kind, stage): {"positive": 0, "negative": 0, "not_evaluated": 0}
               for kind in ("attack", "benign") for stage in STAGES}
    timings = defaultdict(list)
    seen = set()
    for record in records:
        identity = (record["scenario_id"], record["iteration"])
        if identity in seen or record["kind"] not in ("attack", "benign"):
            raise ValueError("duplicate observation or invalid kind")
        seen.add(identity)
        if set(record["stages"]) != set(STAGES):
            raise ValueError("all stages must be explicit")
        for stage in STAGES:
            observation = record["stages"][stage]
            value = observation["value"]
            if value is not None and type(value) is not bool:
                raise ValueError("stage value must be boolean or null")
            if value is not None and not observation.get("evidence_refs"):
                raise ValueError("evaluated stage needs evidence references")
            if (stage == "d5" and value is not None
                    and (observation.get("independence") not in ("host_independent", "external_independent")
                         or observation.get("material_verified") is not True)):
                raise ValueError("D5 requires verified independent material")
            bucket = buckets[(record["kind"], stage)]
            bucket["not_evaluated" if value is None else "positive" if value else "negative"] += 1
        for stage, values in record.get("timings_ms", {}).items():
            if stage not in TIMINGS:
                raise ValueError("unknown timing stage")
            for value in values:
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError("invalid duration")
                timings[stage].append(value)
    out = {"stages": {}, "latency_ms": {}, "metrics": outcome_metrics(records),
           "metrics_by_kind": {kind: outcome_metrics([r for r in records if r["kind"] == kind])
                               for kind in ("attack", "benign")}}
    for (kind, stage), bucket in buckets.items():
        count = bucket["positive"] + bucket["negative"]
        out["stages"].setdefault(kind, {})[stage] = {
            **bucket, "denominator": count,
            "positive_rate": bucket["positive"] / count if count else None,
        }
    for stage in TIMINGS:
        values = sorted(timings[stage])
        out["latency_ms"][stage] = {
            "count": len(values),
            **{f"p{p}": values[max(0, math.ceil(len(values) * p / 100) - 1)] if values else None
               for p in (50, 95, 99)},
        }
    return out


def outcome_metrics(records):
    """Named metrics with explicit eligible populations; stages stay separately reported."""
    names = ("false_allow_rate", "false_deny_rate", "benign_task_completion_rate",
             "intent_violation_block_rate", "provenance_violation_block_rate",
             "resource_hijacking_block_rate", "unauthorized_effect_rate", "unknown_effect_rate",
             "manual_approval_rate")
    counters = {name: [0, 0] for name in names}

    def count(name, positive):
        counters[name][0] += int(positive)
        counters[name][1] += 1

    for record in records:
        actual, expected = record.get("decision_action"), record.get("expected_action")
        if actual not in (None, "allow", "deny", "hold", "redact"):
            raise ValueError("invalid decision action")
        if expected not in (None, "allow", "deny", "hold", "redact"):
            raise ValueError("invalid expected action")
        if actual is not None and expected is not None:
            count("manual_approval_rate", actual == "hold")
            if expected == "deny":
                count("false_allow_rate", actual in ("allow", "redact"))
                # Classify by independently fixed expected reason, never the actual reason.
                reason = record.get("expected_reason", "")
                if reason.startswith("intent_"):
                    count("intent_violation_block_rate", actual == "deny")
                if reason.startswith("provenance_"):
                    count("provenance_violation_block_rate", actual == "deny")
                if record.get("category") in ("filesystem_hijacking", "destination_host_injection"):
                    count("resource_hijacking_block_rate", actual == "deny")
            if expected == "allow":
                count("false_deny_rate", actual == "deny")
        completion = record.get("completion")
        if completion is not None and record["kind"] == "benign":
            count("benign_task_completion_rate", completion["status"] == "verified")
        evidence = record.get("effect_record")
        if evidence is not None:
            count("unauthorized_effect_rate", evidence.get("finding_code") == "unauthorized_effect_observed")
            count("unknown_effect_rate", evidence["evidence"]["result"] == "unknown"
                  or evidence["evidence"]["execution_state"] == "unknown")
    return {name: {"numerator": n, "denominator": d, "rate": n / d if d else None}
            for name, (n, d) in counters.items()}
