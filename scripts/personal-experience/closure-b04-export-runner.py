#!/usr/bin/env python3
"""B04 supplemental HTTP isolation leg. No native-host or real-expiry claim.

Creates an isolated daemon and two genuine runtime-bound tasks through public
APIs. Does not modify the clock, existing evidence, production state or profiles.
The earlier real-wall-clock expiry leg remains a separate immutable source.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("b04_expiry", HERE / "closure-b04-expiry-seed-runner.py")
expiry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(expiry)


def verify_export(doc, trusted_public_key):
    # cryptography is already a control-api development dependency. The trust
    # anchor comes from the selected daemon's local CLI, never from the download.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        if doc["public_key_base64"] != trusted_public_key:
            return False
        unsigned = {k: v for k, v in doc.items() if k != "signature"}
        canonical = json.dumps(unsigned, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(trusted_public_key, validate=True))
        key.verify(bytes.fromhex(doc["signature"]), canonical)
        return True
    except (ValueError, KeyError, TypeError, InvalidSignature):
        return False


def check_exports(harness, check, phase, canaries, trusted_public_key=None):
    page = harness.api("/v1/task-activities")
    check(phase + "_two_tasks", len(page["items"]) >= 2 and page["next_offset"] is None)
    snapshot = page["snapshot"]
    groups = []
    for index, item in enumerate(page["items"]):
        route = "/v1/task-activities/" + item["activity_id"]
        query = "?snapshot=" + snapshot
        detail = harness.api(route + query)
        check(f"{phase}_{index}_bounded_detail", detail["next_offset"] is None)
        expected = [(r["seq"], r["hash"]) for r in detail["receipts"]]
        check(f"{phase}_{index}_nonempty", bool(expected))
        groups.append({row[1] for row in expected})
        for kind in ("export", "trace-export"):
            target = route + "/" + kind + query
            doc = harness.api(target)
            label = f"{phase}_{index}_{kind}"
            check(label + "_scope", doc["activity_id"] == item["activity_id"]
                  and doc["snapshot"] == snapshot
                  and [(r["seq"], r["source_hash"]) for r in doc["receipts"]] == expected)
            if trusted_public_key is not None:
                check(label + "_signature", verify_export(doc, trusted_public_key))
            if kind == "trace-export":
                check(label + "_sources", all((r["seq"], r["receipt_hash"]) in expected
                                             for r in doc["sources"]))
            serialized = json.dumps(doc)
            check(label + "_private_data_absent", all(c not in serialized for c in canaries)
                  and "raw-task-content" not in serialized and '"ciphertext"' not in serialized)
            # Global admin auth recognizes the legacy decision token (403),
            # but runtime-identity credentials are valid only on their dedicated
            # runtime routes and are unrecognized here (401): authz.go.
            credentials = (("missing", None, 401), ("runtime", harness.runtime_credential, 401),
                           ("decision", harness.decision_credential, 403))
            for credential_kind, credential, code in credentials:
                actual, body = harness.probe(target, token=credential)
                check(label + f"_auth_{credential_kind}_{code}", actual == code
                      and all(c not in json.dumps(body) for c in canaries))
            code, body = harness.probe(target + "&task_id=foreign", token=harness.admin)
            check(label + "_injected_scope", code == 400
                  and body.get("error") == "task_activity_query_invalid")
    check(phase + "_disjoint", all(not a.intersection(b)
          for i, a in enumerate(groups) for b in groups[i + 1:]))
    return page


def run(binary: Path, out: Path):
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(out, 0o700)
    checks = []

    def check(name, ok):
        checks.append({"id": name, "passed": bool(ok)})
        if not ok:
            raise AssertionError(name)  # category only; never response payload

    failure = None
    failure_location = None
    with tempfile.TemporaryDirectory(prefix="siq-b04-export-") as root:
        harness = expiry.B04Harness(Path(root), argparse.Namespace(port=None))
        shutil.copy2(binary, harness.binary)
        canaries = ["b04-expiry-fixture-payload-for-export-a",
                    "b04-expiry-fixture-payload-for-export-b"]
        try:
            harness.start()
            check("default_disabled", harness.raw_status()["status"] == "disabled")
            trusted_public_key = harness.command([str(harness.binary), "pubkey"]).strip()
            harness.decision_credential = (harness.state / "token").read_text().strip()
            harness.issue_runtime()
            canaries.extend([harness.admin, harness.runtime_credential, harness.decision_credential])
            harness.activate(86400, 67108864)
            legs = []
            for name in ("export-a", "export-b"):
                binding = harness.enroll(name)
                task = binding["task_id"]
                harness.decide(name, name + "-read")
                grant = harness.create_grant(task, 3600, 86400)
                permit = harness.request_permit(name, task, grant, "parameters")
                harness.capture(name, task, permit, "parameters", name)
                records = harness.search_records(task)
                check(name + "_capture", len(records) == 1)
                legs.append((name, task, grant, records[0]))
            check_exports(harness, check, "before", canaries, trusted_public_key)
            name, task, grant, record = legs[0]
            # Using a genuine other task ID is distinct from unknown activity 404.
            code, denied = harness.probe(
                f"/v1/raw-task-content/records/{record['record_id']}/read",
                token=harness.admin, method="POST",
                body={"schema_version": "local-raw-task-content-record-read/v1",
                      "task_id": legs[1][1]})
            check("cross_task_raw_read_rejected", code == 503
                  and denied.get("error") == "raw_task_content_unavailable"
                  and all(c not in json.dumps(denied) for c in canaries))  # existing contract
            harness.revoke_grant(grant["grant_id"], grant["signature"])
            body = {"schema_version": "local-raw-task-content-capture-permit-create/v1",
                    "platform": expiry.PLATFORM, "agent_id": harness.agent,
                    "session_id": name, "task_id": task, "grant_id": grant["grant_id"],
                    "expected_grant_signature": grant["signature"], "kind": "parameters",
                    "ttl_seconds": expiry.PERMIT_TTL_SECONDS}
            code, result = harness.probe("/v1/raw-task-content/capture-permits",
                token=harness.runtime_credential, method="POST", body=body)
            check("revoked_new_capture_rejected", code == 409
                  and result.get("error") == "raw_task_content_authority_revoked")
            check("revoked_history_readable", bool(harness.read_record(record["record_id"], task)))
            current = check_exports(harness, check, "revoked", canaries, trusted_public_key)
            before = expiry.state_digest_snapshot(harness.state)
            purge = harness.purge_expired()
            after = expiry.state_digest_snapshot(harness.state)
            check("unexpired_purge_zero_write", purge["deleted_records"] == 0 and before == after)
            check_exports(harness, check, "after_purge", canaries, trusted_public_key)
            result = harness.api(f"/v1/raw-task-content/records/{record['record_id']}/delete",
                {"schema_version": "local-raw-task-content-record-delete/v1", "task_id": task,
                 "confirm_record_id": record["record_id"]})
            check("delete_only_selected_record", result["deleted"] is True
                  and harness.search_records(task) == [] and len(harness.search_records(legs[1][1])) == 1)
            check_exports(harness, check, "deleted", canaries, trusted_public_key)
            harness.decide(legs[1][0], "new-snapshot-receipt")
            for index, item in enumerate(current["items"]):
                for kind in ("export", "trace-export"):
                    code, result = harness.probe(
                        f"/v1/task-activities/{item['activity_id']}/{kind}?snapshot={current['snapshot']}",
                        token=harness.admin)
                    check(f"stale_{kind}_{index}", code == 409
                          and result.get("error") == "task_activity_snapshot_changed")
            check_exports(harness, check, "refreshed", canaries, trusted_public_key)
        except Exception as exc:  # noqa: BLE001 -- archive failure category and clean owned resources
            failure = type(exc).__name__  # no raw exception, response or log capture
            frames = traceback.extract_tb(exc.__traceback__)
            frame = frames[-2] if len(frames) > 1 and frames[-1].name in ("check", "require") else frames[-1]
            failure_location = {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
        finally:
            harness.stop()
    report = {"schema_version": "closure-b04-export-review/v1",
              "recorded_at": datetime.now(UTC).isoformat(),
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "evidence_level": "http_real_daemon_synthetic_runtime_bound_tasks",
              "passed": failure is None, "error_type": failure, "failure_location": failure_location,
              "checks": {entry["id"]: entry["passed"] for entry in checks},
              "not_measured": ["native host capture", "new real-wall-clock expiry",
                               "concurrent snapshot mutation during response assembly"],
              "signature_validation": "independent Ed25519 verification anchored in the selected state CLI pubkey"}
    payload = (json.dumps(report, indent=2) + "\n").encode()
    with (out / "report.json").open("xb") as f:
        os.chmod(f.name, 0o600)
        f.write(payload)
    with (out / "SHA256SUMS").open("x") as f:
        os.chmod(f.name, 0o600)
        f.write(hashlib.sha256(payload).hexdigest() + "  report.json\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks), "error_type": failure}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.binary.resolve(strict=True), args.out))
