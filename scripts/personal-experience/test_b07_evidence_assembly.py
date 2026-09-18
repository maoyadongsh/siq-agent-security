"""Assembly validates evidence; these synthetic files are never performance evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("b07", Path(__file__).with_name("assemble-b07-evidence.py"))
b07 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b07)


def save(root, name, value):
    (root / name).write_text(json.dumps(value))


def seal(root):
    (root / "SHA256SUMS").write_text("".join(
        hashlib.sha256((root / name).read_bytes()).hexdigest() + "  " + name + "\n"
        for name in sorted(b07.FILES)))


def fixture(root, scenarios, start, value=1.0):
    root.mkdir()
    p = b07.protocol
    rounds = {scenario: [
        {"scenario": scenario, "round": index, "warmup": p.WARMUP[scenario],
         "samples_ms": {metric: [value] * count for metric, count in p.SAMPLES[scenario].items()}}
        for index in (1, 2, 3) for _ in range(2 if scenario in "AB" else 1)
    ] for scenario in scenarios}
    report = {"source_hashes": {}, "head": "synthetic-test-only", "started_at": start,
              "finished_at": start, "environment": {"os": "test"},
              "protocol": {"frozen_before_measurement": True, "rounds": 3,
                  "round_orders": p.ROUND_ORDERS, "tail_scenarios": [s for s in "CDE" if s in scenarios], "percentile_algorithm": p.PERCENTILE_ALGORITHM,
                  "exclusion_rule": p.EXCLUSION_RULE, "samples_per_round": p.SAMPLES, "warmup": p.WARMUP},
              "budgets": p.BUDGETS, "evidence_labels": p.EVIDENCE_LABEL,
              "pooled_summary": {scenario: {metric: p.summarize([value] * count * 3 * (2 if scenario in "AB" else 1))
                  for metric, count in p.SAMPLES[scenario].items()} for scenario in scenarios}}
    save(root, "report.json", report)
    save(root, "samples.json", {"rounds_raw": rounds})
    save(root, "source-hashes.json", {})
    (root / "protocol.md").write_text("Synthetic test only")
    seal(root)
    return root


def test_comparison_keeps_changed_and_missing_work_separate(tmp_path):
    b0 = fixture(tmp_path / "b0", "ABCD", "2026-01-01T00:00:00+00:00")
    b1 = fixture(tmp_path / "b1", "ABCDE", "2026-01-02T00:00:00+00:00")
    result = b07.compare(b0, b1)
    assert result["status"] == "partial"
    assert result["comparable_relative_passed"] is True
    assert {r["comparability"] for r in result["rows"] if r["scenario"] == "C"} == {"changed_probe_workload"}
    assert all(r["relative_passed"] is None for r in result["rows"] if r["scenario"] in "CE")


def test_regression_remains_failure(tmp_path):
    b0 = fixture(tmp_path / "b0", "ABCD", "2026-01-01T00:00:00+00:00")
    b1 = fixture(tmp_path / "b1", "ABCDE", "2026-01-02T00:00:00+00:00", 2.0)
    assert b07.compare(b0, b1)["comparable_relative_passed"] is False


@pytest.mark.parametrize("change", ["hash", "summary", "round", "sample", "budget", "manifest_path"])
def test_invalid_or_rewritten_evidence_rejected(tmp_path, change):
    root = fixture(tmp_path / "run", "ABCD", "2026-01-01T00:00:00+00:00")
    report = json.loads((root / "report.json").read_text())
    samples = json.loads((root / "samples.json").read_text())
    if change == "hash":
        (root / "protocol.md").write_text("changed after hash")
    elif change == "manifest_path":
        with (root / "SHA256SUMS").open("a") as f:
            f.write("0" * 64 + "  ../outside\n")
    else:
        if change == "summary":
            report["pooled_summary"]["A"]["decide_allow_ms"]["p95_ms"] = 0
        elif change == "round":
            samples["rounds_raw"]["D"].pop()
        elif change == "sample":
            samples["rounds_raw"]["D"][0]["samples_ms"]["timeout_fail_ms"][0] = -1
        else:
            report["budgets"]["D"]["timeout_fail_ms"]["p95"] = 500
        save(root, "report.json", report)
        save(root, "samples.json", samples)
        seal(root)  # even self-consistent hashes cannot conceal invalid measurements
    with pytest.raises((ValueError, SystemExit)):
        b07.read_run(root, "ABCD")


def test_parallel_measurements_rejected(tmp_path):
    b0 = fixture(tmp_path / "b0", "ABCD", "2026-01-02T00:00:00+00:00")
    b1 = fixture(tmp_path / "b1", "ABCDE", "2026-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="overlapping_runs"):
        b07.compare(b0, b1)


def test_explicit_zero_warmup_may_be_omitted_by_go_result(tmp_path):
    root = fixture(tmp_path / "run", "ABCD", "2026-01-01T00:00:00+00:00")
    samples = json.loads((root / "samples.json").read_text())
    for entry in samples["rounds_raw"]["C"]:
        entry["warmup"].pop("probe_cold")
    save(root, "samples.json", samples)
    seal(root)
    b07.read_run(root, "ABCD")
    samples["rounds_raw"]["C"][0]["warmup"].pop("probe_repeat")
    save(root, "samples.json", samples)
    seal(root)
    with pytest.raises(ValueError, match="entry_metadata_mismatch"):
        b07.read_run(root, "ABCD")


@pytest.mark.parametrize("marker", ["INVALID.md", "NOT-OFFICIAL.md"])
def test_disqualified_evidence_rejected_even_with_valid_hashes(tmp_path, marker):
    root = fixture(tmp_path / "run", "ABCD", "2026-01-01T00:00:00+00:00")
    (root / marker).write_text("Concurrent workload invalidates this measurement")
    with pytest.raises(ValueError, match="disqualified_evidence"):
        b07.read_run(root, "ABCD")
