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
    out = {"stages": {}, "latency_ms": {}}
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
