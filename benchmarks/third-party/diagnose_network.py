#!/usr/bin/env python3
"""Read-only diagnostic of the legacy network fixture using a fresh daemon."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from common import sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixture", choices=("network", "approval"), default="network")
    args = parser.parse_args()
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    sys.path.insert(0, str(args.candidate / "benchmarks/runtime-security"))
    import approval_fixture
    import network_fixture
    from evidence import capture

    spec = importlib.util.spec_from_file_location("mcp_diagnostic", args.candidate / "scripts/validate-mcp-provenance.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    decisions = []

    class DiagnosticHarness(fixture.base.Harness):
        def api(self, path, body=None, **kwargs):
            result = super().api(path, body, **kwargs)
            if path == "/v1/decide":
                decisions.append({"request": body, "response": result})
            return result

    state = args.out / "fixture-private"
    state.mkdir(mode=0o700)
    harness = DiagnosticHarness(state, SimpleNamespace(binary=args.binary))
    error, observations, evidence = None, None, None
    try:
        observations = {"network": network_fixture, "approval": approval_fixture}[args.fixture].run(harness, fixture.base)
    except Exception as exc:  # noqa: BLE001 -- Preserve fixture failure; diagnostic does not classify it as success.
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        try:
            evidence = capture(harness, "network-diagnostic")
        finally:
            harness.stop()
    write_json(args.out / "diagnostic.json", {"purpose": "triage only, excluded from frozen baseline",
                                             "binary_sha256": sha256(args.binary), "decisions": decisions,
                                             "error": error, "observations": observations, "public_evidence": evidence})
    print(json.dumps({"error": error, "decisions": [{"action": d["response"].get("action"),
                                                     "reason": d["response"].get("reason_code")}
                                                    for d in decisions]}))


if __name__ == "__main__":
    main()
