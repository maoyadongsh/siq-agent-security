#!/usr/bin/env python3
"""Bounded real-model utility smoke through the frozen SecureApplication."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import stat
import time
from pathlib import Path

from common import Events, sha256, utc_now, write_json


def read_key(path: Path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError("credential permissions invalid")
        value = stream.read(8193).strip()
        if not value or len(value) > 8192:
            raise ValueError("credential invalid")
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    approved = {("step-5-preview", "https://api.stepfun.com/step_plan/v1"),
                ("Qwen3.8-27B-NVFP4", "http://127.0.0.1:8005/v1")}
    if (protocol.get("model"), protocol.get("endpoint")) not in approved:
        raise ValueError("unapproved model endpoint")
    if protocol["harness_sha256"] != sha256(Path(__file__)):
        raise ValueError("model harness changed after protocol freeze")
    os.umask(0o077)
    out = args.out.resolve()
    out.relative_to(Path(protocol["campaign_root"]) / "private" / "runs")
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    (out / "harness-source").mkdir()
    for name in ("model_smoke.py", "common.py"):
        shutil.copyfile(Path(__file__).parent / name, out / "harness-source" / name)
    candidate, binary = Path(protocol["candidate_root"]), Path(protocol["binary"])
    if sha256(binary) != protocol["binary_sha256"]:
        raise ValueError("candidate binary changed")
    spec = importlib.util.spec_from_file_location("model_legacy_benchmark", candidate / "benchmarks/hackathon/run.py")
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    from secure_agent.contracts import AgentError, canonical
    from secure_agent.model_policy import ModelPolicy
    from secure_agent.models import OrnithProvider, StepFunProvider, proposal_schema
    from secure_agent.routing import ModelRouter

    key = read_key(args.credential_file)
    events = Events(out / "events.jsonl", out.name)
    budget = {"calls": 0, "charged_tokens": 0, "reported_tokens": 0, "unknown_usage_calls": 0}
    started = time.monotonic()
    corpus = {c["id"]: c for c in benchmark.load_corpus()}
    expected = protocol["allocation"]
    if not expected or len({u["unit_id"] for u in expected}) != len(expected):
        raise ValueError("invalid model allocation")
    write_json(out / "protocol.json", protocol)
    for unit in expected:
        events.add("scheduled", **unit, attempt=1)
    records = []
    current_unit = None

    provider_class = OrnithProvider if protocol.get("provider") == "local" else StepFunProvider

    class BudgetedProvider(provider_class):
        def generation_options(self, operation):
            options = {"response_format": {"type": "json_object"}, "max_tokens": protocol["max_output_tokens"]}
            if protocol.get("structured_output") == "json_schema":
                schema_name = {"plan": "model-task-plan-v2", "research": "model-research-proposal",
                               "recipient": "model-recipient-selection"}[operation]
                options["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": schema_name, "strict": True, "schema": proposal_schema(schema_name)}}
            if protocol.get("reasoning_effort"):
                options["reasoning_effort"] = protocol["reasoning_effort"]
            if protocol.get("enable_thinking") is not None:
                options["chat_template_kwargs"] = {"enable_thinking": protocol["enable_thinking"]}
            return options

        def _json(self, instruction, content, **kwargs):
            reserve = len(instruction.encode()) * 2 + len(canonical(content)) * 2 + 2048 + protocol["max_output_tokens"]
            if (budget["calls"] >= protocol["max_calls"] or
                    budget["charged_tokens"] + reserve > protocol["total_token_reservation_cap"] or
                    time.monotonic() - started > protocol["total_seconds"]):
                raise AgentError("evaluation_budget_exhausted")
            budget["calls"] += 1
            budget["charged_tokens"] += reserve
            call_id = budget["calls"]
            events.add("model_call_started", unit_id=current_unit, call_id=call_id,
                       operation=kwargs["operation"], reserved_tokens=reserve)
            try:
                return super()._json(instruction, content, **kwargs)
            finally:
                diagnostic = self.calls[-1] if self.calls else {}
                tokens = diagnostic.get("usage", {}).get("total_tokens")
                if type(tokens) is int and tokens >= 0:
                    budget["charged_tokens"] += tokens - reserve
                    budget["reported_tokens"] += tokens
                else:
                    budget["unknown_usage_calls"] += 1
                events.add("model_call_finished", unit_id=current_unit, call_id=call_id,
                           diagnostic=diagnostic, budget=dict(budget))

    for unit in expected:
        current_unit = unit["unit_id"]
        case = corpus[unit["case_id"]]
        if case["kind"] != "benign":
            raise ValueError("utility smoke only allows frozen benign tasks")
        events.add("started", **unit, attempt=1)
        provider = BudgetedProvider(protocol["endpoint"], protocol["model"], key, timeout=protocol["request_timeout_seconds"])
        router = ModelRouter(provider, local_factory=None, policy=ModelPolicy(public_research_local=False))
        benchmark.from_environment = lambda _router=router, **_kwargs: _router
        try:
            result = benchmark.run_case(case, binary, out / "state-private" / current_unit, "model-utility")
            row = {**unit, "execution_status": "completed", "legacy_capture": result,
                   "utility_completed": result["result"]["task"]["status"] == "verified",
                   "expectation_violations": result["expectation_violations"]}
        except Exception as exc:  # noqa: BLE001 -- Evidence preserves failed tasks; no response or credential is printed.
            row = {**unit, "execution_status": "error", "utility_completed": None,
                   "error_type": type(exc).__name__, "expectation_violations": [], "legacy_capture": None}
        write_json(out / "cases-private" / (current_unit + ".json"), row)
        records.append(row)
        events.add("finished", unit_id=current_unit, execution_status=row["execution_status"],
                   utility_completed=row["utility_completed"], expectation_violations=row["expectation_violations"])
        print(json.dumps({"unit_id": current_unit, "utility_completed": row["utility_completed"],
                          "status": row["execution_status"], "calls": budget["calls"]}), flush=True)
    summary = {"schema_version": "siq-model-utility-smoke/v1", "model": protocol["model"],
               "allocated": len(expected), "independent_task_blocks": len({u["case_id"] for u in expected}),
               "completed_tasks": sum(r["utility_completed"] is True for r in records),
               "unknown_tasks": sum(r["utility_completed"] is None for r in records), "budget": budget,
               "reported_credit_cost": None, "credit_cost_reason": "not reported by inference usage API",
               "relationship": "author_run", "groups": ["B2"], "recorded_at": utc_now(),
               "scope": "real model utility only; no ASR or paired defense effectiveness claim"}
    write_json(out / "summary.json", summary)
    sums = {p.relative_to(out).as_posix(): sha256(p) for p in out.rglob("*.json") if "state-private" not in p.parts}
    sums.update({p.relative_to(out).as_posix(): sha256(p) for p in (out / "harness-source").glob("*.py")})
    sums["events.jsonl"] = sha256(out / "events.jsonl")
    write_json(out / "checksums.json", sums)
    print(json.dumps(summary), flush=True)
    return 0 if summary["completed_tasks"] == len(expected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
