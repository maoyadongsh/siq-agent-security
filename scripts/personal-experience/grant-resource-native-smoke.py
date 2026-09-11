#!/usr/bin/env python3
"""Verify a read-only Grant with a write-capable Intent through the real Hermes CLI."""

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

SOURCE = Path(__file__).with_name("hermes-cli-runtime-smoke.py")
loader = importlib.util.spec_from_file_location("public_cli_fixture", SOURCE)
cli_fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(cli_fixture)
require = cli_fixture.fixture.require


class ScopeHarness(cli_fixture.Harness):
    def api(self, path, body=None, **kwargs):
        # Configure the synthetic operator's normal authoring requests before
        # signing/approval. Never edit a deployed Grant or bypass an API check.
        if body is not None and path.endswith("/patch-desired"):
            body = body | {"filesystem": {"read_only": [str(self.workspace)], "read_write": []}}
        elif body is not None and path == "/v1/intents":
            body = body | {
                "allowed_tools": [self.read_tool, self.write_tool],
                "allowed_effects": ["file.read", "file.write"],
            }
        return super().api(path, body, **kwargs)

    def assert_call(self, records, call_id, outcome, *, bound=True):
        if call_id != "write-denied":
            return super().assert_call(records, call_id, outcome, bound=bound)
        own = [row for row in records if row.get("tool_call_id") == call_id]
        require(len(own) == 1, "denied write produced extra records")
        row = own[0]
        require(row["record_type"] == "decision" and row["action"] == "deny", "write not denied")
        require(row["authority_status"] == "valid", "Intent denied instead of Grant")
        require(row["policy_action"] == "deny" and row["reason_code"] == "grant_scope_violation", "wrong denial layer")
        require(row["intent_digest"] == self.digest and bool(row["matched_grant_id"]), "missing authority correlation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--expect-old-bypass", action="store_true", help="Reproduce the old behavior only in generated files"
    )
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    with tempfile.TemporaryDirectory(prefix="siq-grant-resource-native-") as temporary:
        root = Path(temporary)
        harness = ScopeHarness(root, args)
        home = root / "home"
        home.mkdir(mode=0o700)
        harness.env.update({"HOME": str(home), "USERPROFILE": str(home), "LOCALAPPDATA": str(home / "AppData/Local")})
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            if args.expect_old_bypass:
                try:
                    harness.public_cli()
                except RuntimeError:
                    records = harness.receipts()
                    writes = [r for r in records if r.get("tool_call_id") == "write-denied"]
                    require((harness.workspace / "company-a/must-not-exist.txt").exists(), "old bypass not reproduced")
                    require(
                        any(
                            r["record_type"] == "decision"
                            and r["action"] == "allow"
                            and r["authority_status"] == "valid"
                            for r in writes
                        ),
                        "old allow evidence missing",
                    )
                    checks = [
                        "old_readonly_grant_allowed_write_with_valid_intent",
                        "generated_file_side_effect_confirmed",
                    ]
                else:
                    raise RuntimeError("old binary did not exhibit the expected bypass")
            else:
                result = harness.public_cli()
                checks = result["checks"] + ["write_capable_intent_still_limited_by_readonly_grant"]
        finally:
            harness.stop()
    report = {
        "schema_version": "grant-resource-native-smoke/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "expected_old_bypass": args.expect_old_bypass,
        "checks": checks,
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "public_cli_fixture_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "native_cli_sha256": hashlib.sha256(args.hermes_cli.read_bytes()).hexdigest(),
        "scope": "public Hermes CLI, normal hooks, isolated generated profile/files and synthetic operator; "
        "not Skill attribution or OS isolation",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
