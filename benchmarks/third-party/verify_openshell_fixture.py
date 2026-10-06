#!/usr/bin/env python3
"""Verify/export bounded OpenShell environment preflight, not product acceptance."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from common import safe_path, sha256, write_json


def verify(run, anchor):
    if sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("manifest anchor differs")
    manifest = json.loads((run / "manifest.json").read_text())
    for name, digest in manifest["artifacts"].items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("artifact changed: " + name)
    required = {"events.jsonl", "result.json", "preregistration.json", "harness-source.py"}
    if not required <= set(manifest["artifacts"]):
        raise ValueError("missing required capture")
    registration = json.loads((run / "preregistration.json").read_text())
    if sha256(run / "harness-source.py") != registration["runtime_source_sha256"]:
        raise ValueError("runtime source differs")
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    if [e["sequence"] for e in events] != list(range(1, len(events) + 1)):
        raise ValueError("event sequence differs")
    starts, ends = {}, {}
    for event in events:
        if event["event"] == "command_start":
            if event["command_id"] in starts:
                raise ValueError("duplicate command")
            starts[event["command_id"]] = event
        elif event["event"] == "command_end":
            identifier = event["command_id"]
            if identifier not in starts or identifier in ends:
                raise ValueError("command lifecycle differs")
            ends[identifier] = event
            for stream in ("stdout", "stderr"):
                if sha256(safe_path(run, identifier + "." + stream)) != event[stream + "_sha256"]:
                    raise ValueError("command stream differs")
    result = json.loads((run / "result.json").read_text())
    if result.get("kind") != "environment_preflight" or result.get("product_deployment_tested") is not False:
        raise ValueError("preflight scope inflated")
    cleanup = [e["result"] for e in events if e["event"] == "cleanup"]
    if cleanup != [result["cleanup"]]:
        raise ValueError("cleanup projection differs")
    passed = not result.get("error_type") and result.get("authenticated_gateway_ready") is True and (
        result.get("create_exit_code") == result.get("readback_exit_code") == 0)
    if result.get("authenticated_gateway_ready"):
        status = [key for key, row in starts.items() if row["argv"][-1:] == ["status"]]
        if len(status) != 1 or ends[status[0]]["exit_code"] != 0:
            raise ValueError("authenticated status capture absent")
        output = re.sub(r"\x1b\[[0-9;]*m", "", (run / (status[0] + ".stdout")).read_text())
        if not re.search(r"Status:\s+Connected", output) or not re.search(r"Authentication:\s+Authenticated.*mTLS transport", output):
            raise ValueError("authenticated status not observed")
    if "siq_adapter_probe_exit_code" in result:
        passed &= result["siq_adapter_probe_exit_code"] == 0 and result.get("siq_handshake_verified") is True
        if result["siq_adapter_probe_exit_code"] == 0:
            captures = [identifier for identifier, start in starts.items() if "-c" in start["argv"]]
            if len(captures) != 1 or json.loads((run / (captures[0] + ".stdout")).read_text()) != json.loads((run / "product-readback.json").read_text()):
                raise ValueError("product probe projection differs")
    for label, words in (("create_exit_code", ["sandbox", "create"]), ("readback_exit_code", ["policy", "get"])):
        matches = [key for key, row in starts.items() if any(row["argv"][i:i + 2] == words for i in range(len(row["argv"]) - 1))]
        if label in result and (len(matches) != 1 or ends[matches[0]]["exit_code"] != result[label]):
            raise ValueError("runtime operation projection differs")
    if result["passed"] is not bool(passed):
        raise ValueError("preflight outcome differs")
    cleaned = result["cleanup"].get("gateway_stopped") is True and result["cleanup"].get("network_removed") is True and (
        result["cleanup"].get("container_inventory_checked") is True) and all(x["removed"] for x in result["cleanup"]["containers"])
    return {"integrity_verified": True, "preflight_passed": passed, "cleanup_confirmed": cleaned,
            "commands": len(starts), "product_deployment_tested": False,
            "limits": ["author-captured runtime evidence", "no Control API deployment/approval tested in this preflight",
                       "historical capability fields are not current enforcement measurements"]}


def export(source, output, credentials):
    names = {"events.jsonl", "result.json", "preregistration.json", "harness-source.py", "product-readback.json"}
    files = [p for p in source.iterdir() if p.is_file() and (p.name in names or re.fullmatch(r"command-\d+\.(stdout|stderr)", p.name))]
    keys = [p.read_bytes().strip() for p in credentials.glob("*.key")]
    for path in files:
        data = path.read_bytes()
        if b"-----BEGIN PRIVATE KEY-----" in data or any(key and key in data for key in keys):
            raise ValueError("credential in export")
    output.mkdir(parents=True, exist_ok=False)
    for path in files:
        shutil.copyfile(path, output / path.name)
    write_json(output / "manifest.json", {"schema_version": "siq-openshell-preflight/v1",
        "scope": "environment_preflight", "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
    return sha256(output / "manifest.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.run, args.expected_manifest_sha256), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
