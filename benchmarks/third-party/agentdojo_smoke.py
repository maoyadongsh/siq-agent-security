#!/usr/bin/env python3
"""Run a preregistered restricted AgentDojo cohort with original outcome scorers."""
import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from adapters.agentdojo import MailGate, make_runtime, serializable_messages
from common import Events, canonical, safe_path, sha256, utc_now, write_json
from model_smoke import read_key


def run_unit(protocol, unit, client, suite, out, budget, keyless_fixture):
    from agentdojo.agent_pipeline.llms.openai_llm import (
        _function_to_openai,
        _message_to_openai,
        _openai_to_assistant_message,
    )
    from agentdojo.agent_pipeline.tool_execution import ToolsExecutor
    from agentdojo.task_suite.task_suite import (
        functions_stack_trace_from_messages,
        model_output_from_messages,
    )
    from agentdojo.types import text_content_block_from_string

    directory = out / "cases" / unit["unit_id"]
    directory.mkdir(parents=True)
    events = Events(directory / "events.jsonl", unit["unit_id"])
    task = suite.get_user_task_by_id(unit["task_id"])
    injection_task = suite.get_injection_task_by_id(protocol["injection_task_id"])
    injection = protocol["injections"][unit["task_id"]] if unit["condition"] == "adversarial" else {}
    environment = task.init_environment(suite.load_and_inject_default_environment(injection))
    before = environment.model_copy(deep=True)
    write_json(directory / "environment-before.json", before.model_dump(mode="json"))
    system_prompt = protocol['system_prompt'] + (protocol.get('prompt_defense', '') if unit['group'] == 'B1' else '')
    messages = [{"role": "system", "content": [text_content_block_from_string(system_prompt)]},
                {"role": "user", "content": [text_content_block_from_string(task.PROMPT)]}]
    harness, gate = None, None
    status, error, calls, returned_models = "error", None, 0, []
    runtime, dispatches = None, []
    try:
        if unit["group"] == "B2":
            root = out / "state-private" / unit["unit_id"]
            root.mkdir(parents=True)
            harness = keyless_fixture.Harness(root, SimpleNamespace(binary=protocol["binary"]))
            harness.read_tool = "send_message"
            harness.build()
            harness.start()
            harness.setup_authority()
            gate = MailGate(harness, keyless_fixture.AGENT, "task-" + unit["unit_id"], task.PROMPT)
        runtime, dispatches = make_runtime(suite.tools, gate, events, protocol.get('exposed_tools'))
        executor = ToolsExecutor()
        for _iteration in range(protocol["max_calls_per_unit"]):
            wire_messages = [_message_to_openai(m, protocol["model"]) for m in messages]
            wire_tools = [_function_to_openai(t) for t in runtime.functions.values()]
            reservation = len(canonical({"messages": wire_messages, "tools": wire_tools})) * 2 + 2048 + protocol["max_output_tokens"]
            if (budget["calls"] >= protocol["max_calls"] or budget["charged_tokens"] + reservation > protocol["token_reservation_cap"]
                    or time.monotonic() - budget["started"] > protocol["total_seconds"]):
                raise RuntimeError("cohort_budget_exhausted")
            budget["calls"] += 1
            budget["charged_tokens"] += reservation
            calls += 1
            events.add("model_call_started", call_id=calls, reserved_tokens=reservation)
            options = {"model": protocol["model"], "messages": wire_messages, "tools": wire_tools,
                       "tool_choice": "auto", "temperature": 0, "max_tokens": protocol["max_output_tokens"]}
            if protocol.get("provider") == "local":
                options["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            else:
                options["reasoning_effort"] = "low"
            try:
                completion = client.chat.completions.create(**options)
            except Exception as exc:
                budget["unknown_usage_calls"] += 1
                events.add("model_call_finished", call_id=calls, error_type=type(exc).__name__, usage=None)
                raise
            usage = completion.usage.model_dump() if completion.usage else None
            total = usage.get("total_tokens") if usage else None
            if type(total) is int and total >= 0:
                budget["reported_tokens"] += total
                budget["charged_tokens"] += total - reservation
            else:
                budget["unknown_usage_calls"] += 1
            choice = completion.choices[0]
            returned_models.append(completion.model)
            events.add("model_call_finished", call_id=calls, usage=usage, response_id=completion.id,
                       returned_model=completion.model, system_fingerprint=completion.system_fingerprint,
                       finish_reason=choice.finish_reason)
            if choice.finish_reason not in ("stop", "tool_calls"):
                raise RuntimeError("model_response_incomplete")
            messages.append(_openai_to_assistant_message(choice.message))
            if not messages[-1]["tool_calls"]:
                if messages[-1]["content"] is None:
                    raise RuntimeError("empty_model_output")
                status = "completed"
                break
            _, _, environment, messages, _ = executor.query(task.PROMPT, runtime, environment, messages, {})
        else:
            raise RuntimeError("task_call_limit")
    except Exception as exc:  # noqa: BLE001 -- retain environment after partial tool execution; no automatic replay.
        error = {"type": type(exc).__name__, "code": str(exc) if type(exc) is RuntimeError else None}
    finally:
        if harness is not None:
            spec = importlib.util.spec_from_file_location("agentdojo_receipt_capture", Path(protocol["candidate_root"]) / "benchmarks/runtime-security/evidence.py")
            evidence = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(evidence)
            try:
                write_json(directory / "product-evidence.json", evidence.capture(harness, unit["unit_id"]))
            except Exception as exc:  # noqa: BLE001 -- independent oracle below still runs if product evidence fails.
                status, error = "error", {"type": type(exc).__name__, "code": "product_capture_failed"}
            finally:
                harness.stop()
    trace = functions_stack_trace_from_messages(messages)
    output = model_output_from_messages(messages) if messages and messages[-1]["role"] == "assistant" else []
    # Only now call the original benchmark's gold evaluators. They are never
    # supplied to MailGate or used to construct its authorization.
    official_utility = suite._check_user_task_utility(task, output or [], before, environment, trace)
    official_attack = suite._check_injection_task_security(injection_task, output or [], before, environment, trace)
    row = {**unit, "execution_status": status, "error": error, "calls": calls,
           "returned_models": sorted(set(returned_models)), "official_utility": official_utility,
           "official_attack_success": official_attack,
           "utility_completed": official_utility if status == "completed" else None,
           "harm_observed": True if official_attack else False if status == "completed" else None,
           "dispatches": dispatches, "decisions": gate.decisions if gate else [],
           "lab_boundary_intervened": any(d["error_type"] == "UnsupportedMapping" for d in dispatches),
           "attribution_scope": protocol.get('attribution_scope', 'email dispatch authority/provenance fail-closed; data read tools not protected')}
    write_json(directory / "messages.json", serializable_messages(messages))
    write_json(directory / "environment-after.json", environment.model_dump(mode="json"))
    write_json(directory / "result.json", row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    approved = {("Qwen3.8-27B-NVFP4", "http://127.0.0.1:8005/v1"), ("step-5-preview", "https://api.stepfun.com/step_plan/v1")}
    if (protocol["model"], protocol["endpoint"]) not in approved:
        raise ValueError("unapproved model endpoint")
    for relative, digest in protocol["harness_sources"].items():
        if sha256(safe_path(Path(__file__).parent, relative)) != digest:
            raise ValueError("harness changed after registration")
    for relative, digest in protocol["upstream_sources"].items():
        if sha256(safe_path(Path(protocol["upstream_root"]), relative)) != digest:
            raise ValueError("upstream changed after registration")
    for relative, digest in protocol["candidate_sources"].items():
        if sha256(safe_path(Path(protocol["candidate_root"]), relative)) != digest:
            raise ValueError("candidate source changed after registration")
    if sha256(Path(protocol["binary"])) != protocol["binary_sha256"]:
        raise ValueError("candidate binary changed")
    os.umask(0o077)
    out = args.out.resolve()
    out.relative_to(Path(protocol["campaign_root"]) / "private/runs")
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(Path(protocol["upstream_root"]) / "src"))
    import httpx
    import openai
    from agentdojo.task_suite.load_suites import get_suite
    from analysis.scoring import aggregate

    suite = get_suite(protocol["benchmark_version"], protocol["suite"])
    spec = importlib.util.spec_from_file_location("agentdojo_siq_fixture", Path(protocol["candidate_root"]) / "scripts/validate-intent-v2-hermes.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    write_json(out / "protocol.json", protocol)
    events = Events(out / "events.jsonl", out.name)
    for unit in protocol["allocation"]:
        events.add("scheduled", **unit)
    budget = {"calls": 0, "charged_tokens": 0, "reported_tokens": 0, "unknown_usage_calls": 0, "started": time.monotonic()}
    client = openai.OpenAI(api_key=read_key(args.credential_file), base_url=protocol["endpoint"], max_retries=0,
                           timeout=protocol["request_timeout_seconds"], http_client=httpx.Client(trust_env=False))
    records = []
    try:
        for unit in protocol["allocation"]:
            events.add("started", **unit)
            row = run_unit(protocol, unit, client, suite, out, budget, fixture)
            records.append(row)
            events.add("finished", unit_id=unit["unit_id"], execution_status=row["execution_status"])
            print(json.dumps({k: row[k] for k in ("unit_id", "execution_status", "utility_completed", "harm_observed", "calls")}), flush=True)
    finally:
        client.close()
    strata = {}
    for row in records:
        strata.setdefault(row["group"] + ":" + row["condition"], []).append(row)
    summary = {"schema_version": "siq-agentdojo-restricted-smoke/v1", "allocated": len(records),
               "task_blocks": len({r["task_id"] for r in records}),
               "block_dependence": "shared workspace entities; no independence claim",
               "strata": {k: aggregate(rows) for k, rows in strata.items()}, "budget": {k: v for k, v in budget.items() if k != "started"},
               "relationship": "author_run", "recorded_at": utc_now(), "reported_credit_cost": None,
               "scope": "restricted workspace queries versus injection_task_0; not official full-suite leaderboard result"}
    write_json(out / "summary.json", summary)
    sums = {p.relative_to(out).as_posix(): sha256(p) for p in out.rglob("*.json") if "state-private" not in p.parts}
    sums.update({p.relative_to(out).as_posix(): sha256(p) for p in out.rglob("*.jsonl") if "state-private" not in p.parts})
    write_json(out / "checksums.json", sums)
    write_json(out / "manifest.json", {"schema_version": "siq-agentdojo-smoke-manifest/v1", "allocated": len(records),
        "checksums_sha256": sha256(out / "checksums.json"), "protocol_sha256": sha256(out / "protocol.json"),
        "sealed_at": utc_now(), "relationship": "author_run", "trust": "author_local"})
    print(json.dumps({**summary, "manifest_sha256": sha256(out / "manifest.json")}), flush=True)
    return 2 if any(row["execution_status"] != "completed" for row in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
