#!/usr/bin/env python3
"""Exercise product runtime-check APIs with an installed Hermes and isolated profile."""

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("native_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.installer_managed_profile = True
    with tempfile.TemporaryDirectory(prefix="siq-product-runtime-check-") as temporary:
        root = Path(temporary)
        harness = fixture.Harness(root, args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.install_profile()
            catalog = harness.api("/v1/adapter/instances?platform=hermes")
            instance = next(item for item in catalog["instances"] if item["active"])
            before = (Path(harness.env["HERMES_HOME"]) / "config.yaml").read_bytes()
            plan = harness.api(
                "/v1/runtime-checks/preview",
                {"schema_version": "local-runtime-check-preview/v1", "instance_id": instance["instance_id"]},
            )
            fixture.require(not harness.api("/v1/grants")["grants"], "preview created authority")
            started = harness.api(
                "/v1/runtime-checks/start",
                {
                    "schema_version": "local-runtime-check-start/v1",
                    "check_id": plan["check_id"],
                    "plan_digest": plan["plan_digest"],
                    "actor_id": "synthetic-test-operator",
                    "confirm": True,
                },
                expected=202,
            )
            result = started
            for _ in range(140):
                result = harness.api("/v1/runtime-checks/" + plan["check_id"])
                if result["status"] in ("passed", "failed", "invalidated", "cancelled"):
                    break
                time.sleep(1)
            if result["status"] != "passed":
                receipts = harness.api("/v1/receipts?since_seq=-1").get("receipts", [])
                print(
                    json.dumps(
                        {
                            "status": result["status"],
                            "reason": result["reason_code"],
                            "cleanup": result["cleanup"],
                            "receipt_categories": [
                                {key: row.get(key) for key in ("record_type", "action", "reason_code")}
                                for row in receipts
                            ],
                        }
                    )
                )
                raise RuntimeError("product runtime check did not pass")
            grants = harness.api("/v1/grants")["grants"]
            fixture.require(
                grants and all(g["status"] == "revoked" and g["expires_at"] for g in grants),
                "temporary grant not revoked",
            )
            fixture.require(result["cleanup"] == "complete", "temporary cleanup incomplete")
            fixture.require(not any((harness.state / "runtime-check-materials").iterdir()), "test materials retained")
            fixture.require(
                (Path(harness.env["HERMES_HOME"]) / "config.yaml").read_bytes() == before, "host configuration changed"
            )
            config = Path(harness.env["HERMES_HOME"]) / "config.yaml"
            config.write_bytes(before + b"\n# fixture drift\n")
            changed = harness.api("/v1/runtime-checks/" + plan["check_id"])
            fixture.require(changed["status"] == "invalidated", "stale evidence remained passed")
            report = {
                "schema_version": "product-runtime-check-native-smoke/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "checks": {
                    "preview_does_not_create_authority": True,
                    "product_native_check_passes": True,
                    "grant_revoked": True,
                    "materials_cleaned": True,
                    "host_config_preserved": True,
                    "configuration_drift_invalidates_result": True,
                },
                "receipt_count": len(result["receipt_ids"]),
                "scope": "product API and native Hermes CLI; isolated profile and synthetic operator",
            }
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
