#!/usr/bin/env python3
"""Recompute restricted AgentDojo outcomes with trusted original upstream scorers."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

from agentdojo_snapshot import restore_workspace
from analysis.scoring import aggregate
from common import safe_path, sha256
from verify_models import lifecycle


def verify_pilot_allocation(protocol, tool_names):
    if 'exposed_tools' not in protocol:
        return
    tasks = protocol['applicability']['selected_tasks']
    if len(tasks) != 20 or len(set(tasks)) != 20:
        raise ValueError('pilot requires 20 distinct official task IDs')
    expected = {(t, c, g) for t in tasks for c in ('benign', 'adversarial') for g in ('B0', 'B1', 'B2')}
    allocation = protocol['allocation']
    actual = [(u['task_id'], u['condition'], u['group']) for u in allocation]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('pilot allocation incomplete or duplicated')
    if sorted(protocol['exposed_tools']) != sorted(tool_names):
        raise ValueError('pilot tools differ from complete upstream workspace suite')
    if not protocol.get('prompt_defense'):
        raise ValueError('pilot B1 defense missing')


def verify_prompt_and_dispatch(protocol, unit, prompt, messages, row):
    expected_system = protocol['system_prompt'] + (protocol.get('prompt_defense', '') if unit['group'] == 'B1' else '')
    expected = [{'role': 'system', 'content': [{'type': 'text', 'content': expected_system}]},
                {'role': 'user', 'content': [{'type': 'text', 'content': prompt}]}]
    if messages[:2] != expected:
        raise ValueError('initial system/user prompt differs from registration')
    if unit['group'] != 'B2' and row['decisions']:
        raise ValueError('SIQ decision present in non-SIQ arm')
    if 'exposed_tools' in protocol and any(d['tool'] not in protocol['exposed_tools'] for d in row['dispatches']):
        raise ValueError('unregistered tool dispatch')


def verify(run, anchor, upstream, candidate):
    if sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("manifest anchor mismatch")
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["schema_version"] != "siq-agentdojo-smoke-manifest/v1":
        raise ValueError("unsupported AgentDojo manifest")
    if sha256(safe_path(run, "checksums.json")) != manifest["checksums_sha256"]:
        raise ValueError("checksum list differs")
    sums = json.loads((run / "checksums.json").read_text())
    if not {"protocol.json", "events.jsonl", "summary.json"} <= set(sums):
        raise ValueError("required cohort material absent")
    for name, digest in sums.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("payload differs: " + name)
    if sha256(run / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("protocol differs")
    protocol = json.loads((run / "protocol.json").read_text())
    for name, digest in protocol["upstream_sources"].items():
        if sha256(safe_path(upstream, name)) != digest:
            raise ValueError("upstream source differs from preregistration")
    sys.path.insert(0, str(upstream / "src"))
    from agentdojo.functions_runtime import FunctionCall
    from agentdojo.task_suite.load_suites import get_suite
    from agentdojo.task_suite.task_suite import (
        functions_stack_trace_from_messages,
        model_output_from_messages,
    )

    source = candidate / "benchmarks/runtime-security/evidence.py"
    if sha256(source) != protocol["candidate_sources"]["benchmarks/runtime-security/evidence.py"]:
        raise ValueError("trusted signature verifier changed")
    spec = importlib.util.spec_from_file_location("agentdojo_signature_verifier", source)
    signatures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signatures)
    suite = get_suite(protocol["benchmark_version"], protocol["suite"])
    units = protocol["allocation"]
    verify_pilot_allocation(protocol, [t.name for t in suite.tools])
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    lifecycle(events, units)
    if manifest["allocated"] != len(units):
        raise ValueError("allocation differs")
    strata, counts = {}, {"calls": 0, "charged_tokens": 0, "reported_tokens": 0, "unknown_usage_calls": 0}
    signatures_count = 0
    for unit in units:
        prefix = "cases/" + unit["unit_id"] + "/"
        required = {prefix + name for name in ("environment-before.json", "environment-after.json", "messages.json", "result.json", "events.jsonl")}
        if not required <= set(sums):
            raise ValueError("allocated task payload missing")
        directory = safe_path(run, "cases/" + unit["unit_id"])
        row = json.loads((directory / "result.json").read_text())
        if any(row[key] != value for key, value in unit.items()):
            raise ValueError("task identity differs")
        task = suite.get_user_task_by_id(unit["task_id"])
        injections = protocol["injections"][unit["task_id"]] if unit["condition"] == "adversarial" else {}
        expected_before = task.init_environment(suite.load_and_inject_default_environment(injections))
        before = restore_workspace(suite.environment_type, json.loads((directory / "environment-before.json").read_text()))
        after = restore_workspace(suite.environment_type, json.loads((directory / "environment-after.json").read_text()))
        if before != expected_before:
            raise ValueError("initial environment differs from preregistration")
        messages = json.loads((directory / "messages.json").read_text())
        verify_prompt_and_dispatch(protocol, unit, task.PROMPT, messages, row)
        for message in messages:
            if message["role"] == "assistant" and message["tool_calls"]:
                message["tool_calls"] = [FunctionCall.model_validate(call) for call in message["tool_calls"]]
            elif message["role"] == "tool":
                message["tool_call"] = FunctionCall.model_validate(message["tool_call"])
        output = model_output_from_messages(messages) if messages[-1]["role"] == "assistant" else []
        trace = functions_stack_trace_from_messages(messages)
        utility = suite._check_user_task_utility(task, output or [], before, after, trace)
        attack = suite._check_injection_task_security(suite.get_injection_task_by_id(protocol["injection_task_id"]), output or [], before, after, trace)
        completed = row["execution_status"] == "completed"
        expected = {"official_utility": utility, "official_attack_success": attack,
                    "utility_completed": utility if completed else None, "harm_observed": True if attack else False if completed else None}
        if any(row[key] != value for key, value in expected.items()):
            raise ValueError("result differs from original AgentDojo scorers: " + unit["unit_id"] + " " + json.dumps({k: {"recorded": row[k], "recomputed": v} for k, v in expected.items() if row[k] != v}))
        if unit["group"] == "B2":
            if prefix + "product-evidence.json" not in sums:
                raise ValueError("SIQ receipts not sealed")
            receipts, count = signatures.verify_receipt_bundles([json.loads((directory / "product-evidence.json").read_text())])
            signatures_count += count
            for item in row["decisions"]:
                decision = item["decision"]
                signed = receipts[decision["receipt_id"]][0]
                if any(signed[key] != decision[key] for key in ("action_id", "action", "reason_code")):
                    raise ValueError("recorded decision differs from signed receipt")
            for dispatch in row["dispatches"]:
                if dispatch["tool"] == "send_email" and dispatch["entered"]:
                    decisions = [d["decision"] for d in row["decisions"] if d["dispatch_id"] == dispatch["dispatch_id"]]
                    if not decisions or any(d["action"] != "allow" for d in decisions):
                        raise ValueError("mail entered without recorded SIQ authorization")
        local_events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
        if [e["sequence"] for e in local_events] != list(range(1, len(local_events) + 1)):
            raise ValueError("case event sequence gap/replay")
        starts = [e for e in local_events if e["event"] == "model_call_started"]
        finishes = [e for e in local_events if e["event"] == "model_call_finished"]
        if [e["call_id"] for e in starts] != list(range(1, row["calls"] + 1)) or [e["call_id"] for e in finishes] != list(range(1, row["calls"] + 1)):
            raise ValueError("case model calls missing/replayed")
        for started, ended in zip(starts, finishes):
            counts["calls"] += 1
            total = (ended.get("usage") or {}).get("total_tokens")
            if type(total) is int and total >= 0:
                counts["reported_tokens"] += total
                counts["charged_tokens"] += total
            else:
                counts["unknown_usage_calls"] += 1
                counts["charged_tokens"] += started["reserved_tokens"]
        strata.setdefault(unit["group"] + ":" + unit["condition"], []).append(row)
    computed = {key: aggregate(rows) for key, rows in strata.items()}
    summary = json.loads((run / "summary.json").read_text())
    if summary["allocated"] != len(units) or summary["strata"] != computed or summary["budget"] != counts:
        raise ValueError("summary differs from official-oracle recomputation")
    return {"integrity": "verified_against_supplied_digest", "manifest_sha256": anchor, "allocated": len(units), "strata": computed,
            "budget": counts, "verified_receipts": signatures_count, "scope": "original AgentDojo scorers over recorded environment and transcript; restricted task/tool population",
            "relationship": "author_run; no independent evaluator attestation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--trusted-upstream", type=Path, required=True)
    parser.add_argument("--trusted-candidate", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.run, args.expected_manifest_sha256, args.trusted_upstream, args.trusted_candidate)))
        return 0
    except Exception as exc:  # noqa: BLE001 -- malformed captures and invalid signatures both fail verification.
        print(json.dumps({"integrity": "failed", "error_type": type(exc).__name__, "reason": str(exc)}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
