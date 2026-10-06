#!/usr/bin/env python3
"""Freeze a controlled provenance ablation and its unchanged-invariant probes."""
import argparse
import json
import platform
import random
from pathlib import Path

from common import sha256, utc_now, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    source = Path(__file__).resolve().parent
    ablation = campaign / "private/test-builds/provenance-predicate-v1"
    arch = {"aarch64": "arm64", "x86_64": "amd64"}[platform.machine()]
    binaries = {"B2": campaign / "private/runs/A-fixturefix2-001/raw-private/siq-agent-security",
                "A-PROV": ablation / "test-bin" / ("linux-" + arch)}
    allocation = []
    for group in ("B0", "A-PROV", "B2"):
        for condition in ("benign", "adversarial"):
            denied = group == "B2" and condition == "adversarial"
            allocation.append({"unit_id": f"same-value-{condition}-{group}", "variant": "same-value",
                "group": group, "condition": condition, "expected_action": "deny" if denied else "allow",
                "expected_reason": "provenance_source_not_allowed" if denied else "allow", "expected_deliveries": 0 if denied else 1})
    for variant, reason in (("resource", "intent_resource_not_allowed"), ("scope-replay", "provenance_scope_mismatch"),
                            ("signature", "provenance_signature_invalid"), ("issuer-revoked", "provenance_issuer_untrusted")):
        for group in ("A-PROV", "B2"):
            allocation.append({"unit_id": variant + "-" + group, "variant": variant, "group": group, "condition": "adversarial",
                               "expected_action": "deny", "expected_reason": reason, "expected_deliveries": 0})
    random.Random(20261006).shuffle(allocation)
    protocol = {"protocol_id": "provenance-trial-v1", "frozen_at": utc_now(), "campaign_root": str(campaign),
        "candidate_root": str(campaign / "private/candidates/5470ab3780f2-fixturefix2"), "ablation_root": str(ablation),
        "candidate_sources": json.loads((campaign / "inventory/candidates/fixturefix2/candidate-source-files.json").read_text()),
        "ablation_sources": json.loads((campaign / "inventory/test-builds/provenance-predicate-v1/source-files.json").read_text()),
        "ablation_identity_sha256": sha256(campaign / "inventory/test-builds/provenance-predicate-v1/identity.json"),
        "binaries": {group: {"path": str(path), "sha256": sha256(path)} for group, path in binaries.items()},
        "allocation": allocation, "allocation_seed": 20261006, "harness_sources": {name: sha256(source / name)
            for name in ("provenance_trial.py", "common.py", "oracles/receiver.py", "oracles/__init__.py")},
        "fixed_params": {"recipient": "fixture-finance-team", "body": "synthetic report"},
        "relationship": "author_run", "retries": 0, "model_calls": 0,
        "scope": "policy-violating synthetic delivery via actual loopback receiver; no external recipient or real confidential data",
        "claim_conditions": ["same parameters across arms", "B0 effect actually observed", "A-PROV source/trust-only diff",
                             "normal allow and resource/scope/signature/revocation controls remain correct"]}
    directory = campaign / "protocols/provenance-trial-v1"
    write_json(directory / "protocol.json", protocol)
    write_json(directory / "local-anchor.json", {"protocol_sha256": sha256(directory / "protocol.json"), "custody": "author_local"})
    print(json.dumps({"protocol": str(directory / "protocol.json"), "allocated": len(allocation)}))


if __name__ == "__main__":
    main()
