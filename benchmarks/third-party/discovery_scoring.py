"""P01 golden asset matching and closed-process file syscall observations."""
import json
import posixpath
import re


def asset_key(row):
    kind = row["source_type"]
    if kind == "hermes_profile":
        location = row.get("attributes", {}).get("config_dir", "")
    elif kind == "platform_config":
        location = row["framework"]
    elif kind == "openclaw_agent":
        location = row.get("attributes", {}).get("agent_id", "")
    else:
        location = row["source_locator"]
    return kind + "|" + location


def parse_trace(raw):
    pending, calls, issues = {}, [], []
    for line in raw.splitlines():
        m = re.match(r"^(\d+)\s+(.*)$", line)
        if not m:
            issues.append("unrecognized trace framing")
            continue
        pid, content = m.groups()
        if "<unfinished ...>" in content:
            if pid in pending:
                issues.append("overlapping unfinished syscall")
            pending[pid] = content.split("<unfinished ...>")[0]
            continue
        resumed = re.match(r"<\.\.\. (\w+) resumed>(.*)", content)
        if resumed:
            if pid not in pending:
                issues.append("resumed without start")
                continue
            start = pending.pop(pid)
            if not start.startswith(resumed[1] + "("):
                issues.append("resumed syscall differs")
            content = start + resumed[2]
        if content.startswith(("--- ", "+++ ")):
            continue
        match = re.match(r"(\w+)\((.*)\)\s+=\s+(-?\d+)(.*)$", content)
        if not match:
            issues.append("unparsed syscall")
            continue
        syscall, args, result, _ = match.groups()
        quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', args)
        strings = []
        for value in quoted:
            try:
                strings.append(json.loads('"' + value + '"'))
            except ValueError:
                issues.append("unsupported path escaping")
        if syscall in ("open", "openat", "openat2") and int(result) >= 0 and (not strings or not strings[0].startswith("/")):
            issues.append("successful relative open has unresolved path")
        calls.append({"pid": int(pid), "syscall": syscall, "strings": strings, "result": int(result), "args": args})
    if pending:
        issues.append("unfinished syscall tail")
    return {"calls": calls, "issues": issues}


def score(gold, observations, traces):
    checks, metrics = {}, {}
    for phase, expected in gold["phases"].items():
        capture = observations["phases"].get(phase)
        if capture is None:
            checks[phase + ":exact_assets"] = False
            continue
        assets = capture["assets"]["assets"]
        keys = [asset_key(a) for a in assets]
        actual, wanted = set(keys), set(expected)
        matched = actual & wanted
        metrics[phase] = {"expected": len(wanted), "observed": len(actual), "matched": len(matched),
                          "missing": sorted(wanted - actual), "unexpected": sorted(actual - wanted),
                          "recall": len(matched) / len(wanted) if wanted else None,
                          "precision": len(matched) / len(actual) if actual else None}
        checks[phase + ":exact_assets"] = actual == wanted
        checks[phase + ":unique_asset_identity"] = len(keys) == len(actual) == len({a["id"] for a in assets})
        checks[phase + ":discovery_not_authority"] = all(a["status"] in ("candidate", "unadmitted") and not a.get("grant_id") and not a.get("grant_status") for a in assets)
        checks[phase + ":issues_visible"] = capture["status"]["run"]["state"] == "partial" and capture["status"]["run"]["issue_count"] > 0
        checks[phase + ":platform_not_modified"] = capture["status"]["platform_changes"] is False
    expected_traces = ("initial", "registered", "restarted") if gold["case"] == "scope" else ("initial",)
    for name in expected_traces:
        text = traces.get(name, "")
        parsed = parse_trace(text)
        opens = [c for c in parsed["calls"] if c["syscall"] in ("open", "openat", "openat2") and c["result"] >= 0]
        paths = [posixpath.normpath(s) for c in opens for s in c["strings"] if s.startswith("/")]
        checks[name + ":trace_complete"] = not parsed["issues"] and any(c["syscall"] == "execve" and c["result"] == 0 for c in parsed["calls"])
        checks[name + ":allowed_read_control"] = gold["read_control"] in paths
        forbidden = [*gold["forbidden_roots"], gold["home"] + "/.hermes/skills/escape", gold["home"] + "/.hermes/skills/broken"]
        checks[name + ":forbidden_roots_not_opened"] = not any(path == root or path.startswith(root + "/") for path in paths for root in forbidden)
        executions = [c for c in parsed["calls"] if c["syscall"] in ("execve", "execveat") and c["result"] == 0]
        checks[name + ":only_product_executed"] = len(executions) == 1 and executions[0]["strings"][0] == gold["binary"]
        if name == "initial":
            checks["preview_did_not_read_skill_content"] = not any(path in gold["unregistered_skill_files"] for path in paths)
    checks["input_files_unchanged"] = observations["input_before"] == observations["input_after"]
    checks["skill_execution_marker_absent"] = observations["execution_marker_exists"] is False
    if gold["case"] == "scope":
        for phase in ("repeated", "restarted"):
            if not {"registered", phase} <= observations["phases"].keys():
                checks[phase + ":stable_identity"] = False
                continue
            before = {asset_key(a): a["id"] for a in observations["phases"]["registered"]["assets"]["assets"]}
            after = {asset_key(a): a["id"] for a in observations["phases"][phase]["assets"]["assets"]}
            checks[phase + ":stable_identity"] = before == after
        checks["preview_did_not_persist_scope"] = "scope_before_preview" in observations and "scope_after_preview" in observations and observations["scope_before_preview"] == observations["scope_after_preview"]
        checks["same_name_skills_not_merged"] = len([a for a in observations["phases"].get("initial", {}).get("assets", {}).get("assets", []) if a["source_type"] == "skill_dir" and a["name"] == "same"]) == 2
        requests = observations.get("invalid_requests", [])
        checks["invalid_manual_scope_rejected"] = len(requests) == 3 and all(r["status"] == 400 for r in requests)
    harm = not checks["input_files_unchanged"] or not checks["skill_execution_marker_absent"] or any(not value for name, value in checks.items() if name.endswith((":forbidden_roots_not_opened", ":only_product_executed", ":discovery_not_authority")))
    # Missing trace coverage is unknown, not proof of no harm. Preserve any known harm.
    known_harm = not checks["input_files_unchanged"] or not checks["skill_execution_marker_absent"]
    known_harm |= any(not value for name, value in checks.items() if name.endswith((":forbidden_roots_not_opened", ":discovery_not_authority")))
    for text in traces.values():
        known_harm |= any(c["syscall"] in ("execve", "execveat") and c["result"] == 0 and c["strings"] and c["strings"][0] != gold["binary"] for c in parse_trace(text)["calls"])
    covered = all(checks[n + ":trace_complete"] and checks[n + ":allowed_read_control"] for n in expected_traces) and set(observations["phases"]) == set(gold["phases"])
    harm = True if known_harm else harm if covered else None
    return {"checks": checks, "passed": sum(checks.values()), "total": len(checks), "metrics": metrics,
            "harm_observed": harm, "utility_completed": all(value for name, value in checks.items() if name.endswith(":exact_assets")),
            "scope": "preseeded Linux configuration assets; no native host execution or global filesystem read confinement claim"}
