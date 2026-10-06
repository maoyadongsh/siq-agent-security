#!/usr/bin/env python3
"""Build an explicitly non-production source/trust-predicate ablation in isolation."""
import argparse
import json
import subprocess
from pathlib import Path

from common import Events, clean_environment, run_command, sha256, utc_now, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    identity = json.loads((campaign / "inventory/candidate.json").read_text())
    commit = identity["source_commit"]
    original = campaign / "private/candidates" / commit[:12]
    target = campaign / "private/test-builds/provenance-predicate-v1"
    inventory = campaign / "inventory/test-builds/provenance-predicate-v1"
    events = Events(campaign / "private/ablation-prepare-v1.jsonl", "ablation-prepare-v1")
    logs = campaign / "private/ablation-build-logs"
    for name, argv, cwd in [
        ("clone", ["git", "clone", "--local", "--no-hardlinks", "--no-checkout", str(original), str(target)], campaign),
        ("checkout", ["git", "checkout", "--detach", commit], target),
        ("remove-remote", ["git", "remote", "remove", "origin"], target),
    ]:
        result = run_command(events, name, argv, cwd, logs)
        if result["exit_code"] != 0:
            raise RuntimeError("ablation clone failed")
    relative = "apps/agentshield/internal/provenance/matcher.go"
    path = target / relative
    source = path.read_text()
    start = source.index("\t\t\tallowed := false\n")
    end_text = '\t\t\tif trustRanks[node.Source.Trust] < trustRanks[c.MinimumTrust] {\n\t\t\t\treturn failure("provenance_trust_insufficient")\n\t\t\t}\n'
    end = source.index(end_text, start) + len(end_text)
    replacement = "\t\t\t// EVALUATION ONLY: source allowlist and minimum trust predicate ablated.\n"
    path.write_text(source[:start] + replacement + source[end:])
    inventory.mkdir(parents=True, exist_ok=False)
    (inventory / "ablation-diff.patch").write_bytes(subprocess.check_output(["git", "diff", "--", relative], cwd=target))
    files = json.loads((campaign / "inventory/candidate-source-files.json").read_text())
    files[relative] = sha256(path)
    write_json(inventory / "source-files.json", files)
    build_id = {"schema_version": "siq-evaluation-ablation/v1", "source_commit": commit, "frozen_at": utc_now(),
                "production_eligible": False, "changed_source": [relative], "patch_sha256": sha256(inventory / "ablation-diff.patch"),
                "source_manifest_sha256": sha256(inventory / "source-files.json"), "root": str(target),
                "ablated": ["parameter source type allowlist", "parameter minimum trust"],
                "preserved": ["required provenance presence", "signatures", "issuer authorization/revocation", "scope and content digest",
                              "derivation graph checks", "Grant/Intent", "identity/SEC", "audit", "EVC"],
                "scope": "isolated research build; not a product release or runtime configuration option"}
    write_json(inventory / "identity.json", build_id)
    module = target / "apps/agentshield"
    results = []
    for name, argv in [("format", ["gofmt", "-l", "."]), ("vet", ["go", "vet", "./..."]),
                       ("tests", ["go", "test", "-count=1", "./..."])]:
        results.append(run_command(events, name, argv, module, logs, timeout=1200, memory_mib=12288))
    for platform in ("linux/amd64", "linux/arm64", "darwin/arm64", "windows/amd64"):
        goos, goarch = platform.split("/")
        env = clean_environment()
        env.update(GOOS=goos, GOARCH=goarch)
        binary = target / "test-bin" / (goos + "-" + goarch + (".exe" if goos == "windows" else ""))
        binary.parent.mkdir(exist_ok=True)
        result = run_command(events, "build-" + goos + "-" + goarch,
                             ["go", "build", "-o", str(binary), "./cmd/agentshield"], module, logs, env=env)
        if result["exit_code"] == 0:
            result["binary"] = str(binary)
            result["binary_sha256"] = sha256(binary)
        results.append(result)
    write_json(inventory / "validation.json", {"commands": results,
               "note": "Original negative tests of the deliberately removed predicate may fail; preserve and inspect exact failures. Do not call this product CI passing."})
    print(json.dumps({"identity": str(inventory / "identity.json"), "results": [{"command": r["command_id"], "exit_code": r["exit_code"]} for r in results]}))


if __name__ == "__main__":
    main()
