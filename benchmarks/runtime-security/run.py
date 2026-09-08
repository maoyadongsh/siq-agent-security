#!/usr/bin/env python3
"""Run actual runtime benchmark pairs in an isolated local fixture."""
import argparse
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import approval_fixture
import effect_fixture
import network_fixture
import recipient_fixture
from evidence import capture
from metrics import STAGES, summarize

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("mcp_fixture", ROOT / "scripts/validate-mcp-provenance.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    public_evidence = []
    with tempfile.TemporaryDirectory(prefix="siq-runtime-benchmark-") as temporary:
        harness = fixture.base.Harness(Path(temporary), SimpleNamespace())
        try:
            evidence = fixture.run(harness, extended=True)
            public_evidence.append(capture(harness, "provenance"))
        finally:
            harness.stop()
    observations = []
    for decision in evidence["decisions"]:
        scenario = json.loads((Path(__file__).parent / "scenarios" /
                               f"{decision['pair_id']}-{decision['kind']}.json").read_text())
        stages = {stage: {"value": None, "evidence_refs": []} for stage in STAGES}
        # A signed decision proves the attempted call. An allow does not prove execution.
        stages["d2"] = {"value": True, "evidence_refs": [decision["receipt_id"]]}
        if any(stages[stage]["value"] != scenario["expected"][stage] for stage in STAGES):
            raise RuntimeError("observed stages differ from scenario expectation")
        if decision["reason_code"] != scenario["expected"]["reason_code"]:
            raise RuntimeError("observed reason differs from scenario expectation")
        if decision["action"] != scenario["expected"]["decision_action"]:
            raise RuntimeError("observed action differs from scenario expectation")
        observations.append({
                             "decision_action": decision["action"],
                             "expected_action": scenario["expected"]["decision_action"],
                             "expected_reason": scenario["expected"]["reason_code"], "category": scenario["category"],"scenario_id": scenario["id"], "iteration": 0, "kind": decision["kind"],
                             "stages": stages, "decision": decision,
                             "scenario_sha256": hashlib.sha256(fixture.canonical(scenario)).hexdigest(),
                             "timings_ms": {}})
    with tempfile.TemporaryDirectory(prefix="siq-effect-benchmark-") as temporary:
        harness = fixture.base.Harness(Path(temporary), SimpleNamespace())
        try:
            effects = effect_fixture.run(harness, fixture.base)
            public_evidence.append(capture(harness, "file"))
        finally:
            harness.stop()
    with tempfile.TemporaryDirectory(prefix="siq-network-benchmark-") as temporary:
        harness = fixture.base.Harness(Path(temporary), SimpleNamespace())
        try:
            effects.extend(network_fixture.run(harness, fixture.base))
            public_evidence.append(capture(harness, "network"))
        finally:
            harness.stop()
    with tempfile.TemporaryDirectory(prefix="siq-recipient-benchmark-") as temporary:
        harness = fixture.base.Harness(Path(temporary), SimpleNamespace())
        try:
            effects.extend(recipient_fixture.run(harness, fixture.base))
            public_evidence.append(capture(harness, "recipient"))
        finally:
            harness.stop()
    with tempfile.TemporaryDirectory(prefix="siq-approval-benchmark-") as temporary:
        harness = fixture.base.Harness(Path(temporary), SimpleNamespace())
        try:
            effects.extend(approval_fixture.run(harness, fixture.base))
            public_evidence.append(capture(harness, "approval"))
        finally:
            harness.stop()
    for observation in effects:
        scenario = json.loads((Path(__file__).parent / "scenarios" /
                               (observation["scenario_id"] + ".json")).read_text())
        if any(observation["stages"][stage]["value"] != scenario["expected"][stage] for stage in STAGES):
            raise RuntimeError("effect outcome differs from scenario")
        if observation["reason_code"] != scenario["expected"]["reason_code"]:
            raise RuntimeError("effect decision reason differs from scenario")
        if observation["decision"] != scenario["expected"]["decision_action"]:
            raise RuntimeError("effect decision action differs from scenario")
        observation.update(decision_action=observation["decision"],
                           expected_action=scenario["expected"]["decision_action"],
                           expected_reason=scenario["expected"]["reason_code"], category=scenario["category"])
        observation["scenario_sha256"] = hashlib.sha256(fixture.canonical(scenario)).hexdigest()
    observations.extend(effects)
    report = {"schema_version": "runtime-security-benchmark/v1", "coverage": "component_fixture",
              "public_evidence": public_evidence, "fixture_evidence": evidence, "observations": observations, "summary": summarize(observations),
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "limitations": ["twenty component attack/benign pairs; native coverage remains pending", "D0/D1 not evaluated",
                              "provenance pairs: D3-D5 not evaluated; file pairs: host observer only", "no internal stage timing yet"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Runtime pairs verified; report: {args.out}")


if __name__ == "__main__":
    main()
