#!/usr/bin/env python3
"""Verify Skill import using an isolated real daemon and CLI, without installing or executing Skills."""

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("daemon_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify(public, value):
    public.verify(bytes.fromhex(value["signature"]), canonical({k: v for k, v in value.items() if k != "signature"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-skill-import-") as temp:
        root = Path(temp)
        args.installer_managed_profile = True
        args.hermes_cli = root / "unavailable-hermes-cli"
        h = fixture.Harness(root, args)  # Only isolated daemon lifecycle helpers; never invoke the native worker.
        shutil.copy2(args.binary, h.binary)
        source = root / "source"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: import-smoke\ndescription: Read a synthetic report.\n---\nRead a report.\n"
        )
        (source / "scripts").mkdir()
        marker = root / "must-not-execute"
        script = "#!/bin/sh\ntouch '" + str(marker) + "'\n"
        (source / "scripts/run.sh").write_text(script)
        (source / "scripts/run.sh").chmod(0o700)
        (source / ".git/hooks").mkdir(parents=True)
        (source / ".git/hooks/post-checkout").write_text(script)
        archive = root / "source.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, mode in [
                ("SKILL.md", 0o100600),
                ("scripts/run.sh", 0o100700),
                (".git/hooks/post-checkout", 0o100700),
            ]:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, (source / name).read_bytes())
        cli_args = [
            str(h.binary),
            "import-skill",
            "--path",
            str(source),
            "--actor",
            "fixture-human",
            "--id",
            "si-" + "c" * 32,
        ]
        initial = json.loads(h.command(cli_args))
        fixture.require(not initial["installed"] and not initial["reused"], "CLI misreported candidate")
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(h.command([str(h.binary), "pubkey"]).strip()))
        verify(public, initial["import"])
        verify(public, initial["admission"])
        checks["cli_candidate_and_signatures"] = True
        try:
            h.start()
            locked = subprocess.run(cli_args, cwd=h.workspace, env=h.env, capture_output=True, timeout=10)
            fixture.require(locked.returncode != 0 and not locked.stdout, "CLI bypassed active daemon writer")
            checks["cli_respects_daemon_writer"] = True
            req = {
                "schema_version": "local-skill-import-create/v1",
                "import_id": "si-" + "a" * 32,
                "source_kind": "local_dir",
                "path": str(source),
                "actor_id": "fixture-human",
            }
            decision_token = (h.state / "token").read_text().strip()
            h.api("/v1/skill-imports", req, token=decision_token, expected=403)
            h.api("/v1/skill-imports", req, token="", expected=401)
            checks["http_management_credential_required"] = True
            result = h.api("/v1/skill-imports", req, expected=201)
            verify(public, result["import"])
            verify(public, result["admission"])
            fixture.require(not result["installed"] and not result["reused"], "HTTP misreported candidate")
            record = result["import"]
            payload = h.state / "skill-imports/blobs" / req["import_id"] / "payload"
            manifest = {"directories": [], "files": []}
            for entry in sorted(payload.rglob("*")):
                name = entry.relative_to(payload).as_posix()
                if entry.is_dir():
                    manifest["directories"].append(name)
                else:
                    raw = entry.read_bytes()
                    manifest["files"].append(
                        {
                            "path": name,
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw),
                            "executable": bool(entry.stat().st_mode & 0o111),
                        }
                    )
                    fixture.require(not os.path.samefile(entry, source / name), "copy shares original file identity")
            digest = hashlib.sha256(canonical(manifest)).hexdigest()
            fixture.require(digest == record["artifact_digest"], "independent manifest digest mismatch")
            fixture.require(record["excluded_git_metadata"] and not (payload / ".git").exists(), "Git hooks copied")
            analysis = (payload.parent / "analysis.json").read_bytes()
            fixture.require(hashlib.sha256(analysis).hexdigest() == record["analysis_sha256"], "analysis not bound")
            checks["http_full_manifest_and_analysis_independently_verified"] = True
            checks["independent_copy_and_git_metadata_excluded"] = True
            fixture.require(not marker.exists(), "import executed package contents")
            encoded = json.dumps(result)
            fixture.require(
                str(source) not in encoded and str(marker) not in encoded and decision_token not in encoded,
                "response leaked source path, script content or credential",
            )
            checks["no_execution_or_raw_source_response"] = True
            zipped = h.api(
                "/v1/skill-imports",
                {**req, "import_id": "si-" + "d" * 32, "source_kind": "local_zip", "path": str(archive)},
                expected=201,
            )
            verify(public, zipped["import"])
            fixture.require(zipped["import"]["artifact_digest"] == digest, "ZIP changed normalized payload")
            checks["zip_and_directory_artifacts_match"] = True
            (source / "SKILL.md").write_text("original changed after import")
            retry = h.api("/v1/skill-imports", req)
            fixture.require(retry["reused"] and retry["import"] == record, "retry reimported changed original")
            h.api("/v1/skill-imports", {**req, "actor_id": "another-human"}, expected=409)
            checks["same_id_fixed_retry_and_operator_conflict"] = True
            h.stop()
            h.start()
            recovered = h.api("/v1/skill-imports/" + req["import_id"])
            fixture.require(recovered["import"] == record and recovered["reused"], "restart lost fixed import")
            checks["restart_revalidates_original_signed_record"] = True
            bad_zip = root / "traversal.zip"
            with zipfile.ZipFile(bad_zip, "w") as z:
                z.writestr("SKILL.md", "fixture")
                z.writestr("../escape", "must not extract")
            bad_id = "si-" + "e" * 32
            h.api(
                "/v1/skill-imports",
                {**req, "import_id": bad_id, "source_kind": "local_zip", "path": str(bad_zip)},
                expected=400,
            )
            h.api("/v1/skill-imports/" + bad_id, expected=404)
            fixture.require(not (h.state / "skill-imports/blobs" / bad_id).exists(), "unsafe candidate retained")
            checks["unsafe_zip_rejected_without_published_candidate"] = True
            (payload / "SKILL.md").write_text("replaced fixed copy")
            h.api("/v1/skill-imports/" + req["import_id"], expected=409)
            h.api("/v1/skill-imports", req, expected=409)
            checks["tamper_blocks_read_and_retry"] = True
            fixture.require(not marker.exists(), "package script ran")
            for name in ["grants", "admissions"]:
                fixture.require(not list((h.state / name).glob("*")), "import created global authority")
            records = list((h.state / "skill-imports/records").glob("*.json"))
            fixture.require(len(records) == 3, "import retries duplicated audit")
            for item in records:
                verify(public, json.loads(item.read_text()))
            checks["only_three_unique_signed_import_audits_no_grant_or_install"] = True
        finally:
            h.stop()
    report = {
        "schema_version": "personal-skill-import-smoke/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "method": "isolated_real_linux_daemon_cli_http_synthetic_skills",
        "candidate_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "checks": checks,
        "passed": all(checks.values()),
        "limitations": [
            "No platform installation or runtime execution",
            "No URL fetch or browser UI",
            "No Windows/macOS native verification",
            "Request timeout boundaries use separate Go tests",
        ],
    }
    (args.out_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks)}))


if __name__ == "__main__":
    main()
