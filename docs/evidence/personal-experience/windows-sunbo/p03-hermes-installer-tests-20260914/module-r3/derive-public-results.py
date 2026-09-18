"""Read preserved Go JSON events, redact path separators at nested JSON depths.

This post-run derivation does not execute tests or modify the executed runner.
Pass the same local checkout/private-root/cache-root/go paths used for the run.
"""

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("private-root", "checkout", "cache-root", "go", "delivery"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    delivery = args.delivery.resolve(strict=True)
    roots = (
        (args.private_root.resolve(strict=True), "<PRIVATE_RUN_ROOT>"),
        (args.checkout.resolve(strict=True), "<CHECKOUT>"),
        (args.cache_root.resolve(strict=True).parent, "<OWNED_CACHE_ROOT>"),
        (args.go.resolve(strict=True).parent.parent, "<GO_TOOLCHAIN>"),
    )
    patterns = [
        (re.compile(r"[\\/]+".join(re.escape(part) for part in re.split(r"[\\/]", str(root))), re.I), label)
        for root, label in roots
    ]

    def redact(text):
        for pattern, label in patterns:
            text = pattern.sub(lambda match: label, text)
        text = re.sub(r"S-1-5-21-[0-9-]+", "<SID>", text)
        if re.search(r"[A-Z]:[\\/]+Users[\\/]+|S-1-5-21-\d", text, re.I):
            raise ValueError("Unrecognized personal path or SID in output")
        return text

    raw = (args.private_root / "module-tests.private.log").read_bytes()
    original = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    previous = (delivery / "module-tests.jsonl").read_bytes()
    old_events = [json.loads(line) for line in previous.decode("utf-8").splitlines()]
    assert len(original) == len(old_events)
    events = []
    changed_output_rows = []
    for index, (event, old) in enumerate(zip(original, old_events), 1):
        new = dict(event)
        if "Output" in new:
            new["Output"] = redact(new["Output"])
        assert {k: v for k, v in new.items() if k != "Output"} == {k: v for k, v in old.items() if k != "Output"}
        if new != old:
            changed_output_rows.append(index)
        events.append(new)
    derived = ("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n").encode("utf-8")
    redaction = {
        "method": "Post-run derivation from preserved raw log; case-insensitive exact owned path prefixes accept repeated forward/backslash separators, including JSON nested in Output; current-user SID pattern redacted.",
        "executed_runner_unchanged": True,
        "previous_derived_jsonl_bytes": len(previous),
        "previous_derived_jsonl_sha256": sha(previous),
        "changed_output_event_line_numbers": changed_output_rows,
        "non_output_event_fields_unchanged": True,
        "raw_log_unchanged": True,
        "derivation_script_sha256": sha(Path(__file__).read_bytes()),
    }
    phase_path = delivery / "module-tests-summary.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    assert len(raw) == phase["raw_log_bytes"] and sha(raw) == phase["raw_log_sha256"]
    phase.update(derived_jsonl_bytes=len(derived), derived_jsonl_sha256=sha(derived), public_redaction=redaction)
    summary = json.loads((delivery / "summary.json").read_text(encoding="utf-8"))
    summary["phases"] = [phase if item["name"] == "module-tests" else item for item in summary["phases"]]
    summary["public_redaction"] = redaction
    (delivery / "module-tests.jsonl").write_bytes(derived)
    write(phase_path, phase)
    write(delivery / "summary.json", summary)

    outcomes = {"pass", "fail", "skip"}
    count = lambda rows: {action: sum(row["Action"] == action for row in rows) for action in ("pass", "fail", "skip")}
    terminal = [e for e in events if e["Action"] in outcomes and "Test" in e]
    top = [e for e in terminal if "/" not in e["Test"]]
    sub = [e for e in terminal if "/" in e["Test"]]
    assert count(top) == phase["top_level_counts"] and count(sub) == phase["subtest_counts"]
    assert len(events) == phase["event_count"]
    packages = []
    failures = []
    for package in sorted({e["Package"] for e in events}):
        rows = [e for e in events if e["Package"] == package]
        package_end = [e for e in rows if e["Action"] in outcomes and "Test" not in e]
        assert len(package_end) == 1
        done = {e["Test"] for e in rows if "Test" in e and e["Action"] in outcomes}
        unfinished = [{"test": e["Test"], "started": e["Time"]} for e in rows if e["Action"] == "run" and e["Test"] not in done]
        timeout_stack_running = []
        panic = False
        capture = False
        for event in rows:
            output = event.get("Output", "").strip()
            if "panic: test timed out" in output:
                panic = True
            if panic and output == "running tests:":
                capture = True
                continue
            if capture and output.startswith("Test"):
                timeout_stack_running.append(output)
            elif capture:
                capture = False
        pt = [e for e in rows if e["Action"] in outcomes and "Test" in e]
        packages.append({"package": package, "action": package_end[0]["Action"], "elapsed_seconds": package_end[0].get("Elapsed"), "top_level_counts": count([e for e in pt if "/" not in e["Test"]]), "subtest_counts": count([e for e in pt if "/" in e["Test"]]), "explicit_test_timeout": panic, "timeout_report_running_tests": timeout_stack_running, "started_without_terminal": unfinished})
        for event in pt:
            if event["Action"] != "fail":
                continue
            messages = [e["Output"].strip() for e in rows if e.get("Test") == event["Test"] and e["Action"] == "output" and re.search(r"\.go:\d+:", e.get("Output", ""))]
            failures.append({"package": package, "test": event["Test"], "elapsed_seconds": event.get("Elapsed"), "diagnostic_lines": messages})
    result = {
        "candidate": summary["candidate"],
        "source_before": phase["source_before"], "source_after": phase["source_after"],
        "test_exit_code": phase["exit_code"], "outer_timed_out": phase["outer_timed_out"],
        "event_count": len(events), "package_counts": dict(collections.Counter(p["action"] for p in packages)),
        "top_level_counts": count(top), "subtest_counts": count(sub),
        "explicit_timeout_package_count": sum(p["explicit_test_timeout"] for p in packages),
        "started_without_terminal_count": sum(len(p["started_without_terminal"]) for p in packages),
        "counting_note": "Only terminal pass/fail/skip events enter counts. Started-without-terminal tests are incomplete, not semantic failures; tests never started have unknown denominator. Parent and subtest failures can describe the same assertion and are not summed as unique defects.",
        "raw_log_bytes": len(raw), "raw_log_sha256": sha(raw),
        "derived_jsonl_bytes": len(derived), "derived_jsonl_sha256": sha(derived),
        "raw_and_derived_non_output_fields_equal": True,
        "packages": packages, "terminal_failures": failures,
    }
    write(delivery / "analysis.json", result)
    print(json.dumps({key: result[key] for key in ("package_counts", "top_level_counts", "subtest_counts", "explicit_timeout_package_count", "started_without_terminal_count", "derived_jsonl_bytes", "derived_jsonl_sha256")}))
    print(json.dumps(redaction))


if __name__ == "__main__":
    main()
