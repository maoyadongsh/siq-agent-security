#!/usr/bin/env python3
"""Real rootful Docker protection checks; synthetic labels, no OpenShell policy claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "sha256:bcf4897ab8f95ec875847998297da98d16a44c8741c62c738d917f0eb8d35097"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--probe-binary", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = args.probe_binary.resolve(strict=True)
    assert source.stat().st_size <= 64 << 20 and source.read_bytes()[:4] == b"\x7fELF"
    expected_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    sys.path.insert(0, str(ROOT / "apps/control-api"))
    from app.adapters.openshell.behavior_protection import (
        ProtectedProbeTarget,
        RootfulDockerProbeGuard,
    )
    from app.adapters.openshell.contracts import AdapterError
    from jsonschema import Draft202012Validator

    owned, checks = [], {}
    result = {"passed": False, "schema_version": "openshell-behavior-protection-docker-check/v1",
              "base_image": BASE, "probe_sha256": expected_sha, "checks": checks,
              "openshell_calls": 0, "model_calls": 0, "synthetic_sandbox_labels": True}

    def run(argv, *, required=True):
        executed = subprocess.run(["/usr/bin/docker", "--host", "unix:///run/docker.sock", *argv],
                                  capture_output=True, text=True, timeout=90, check=False)
        if required and executed.returncode:
            (out / "docker-error.log").write_text(executed.stderr[:4096])
            raise RuntimeError("owned Docker command failed; see private log")
        return executed

    def launch(image, *, mounts=()):
        sandbox = "behavior-" + uuid.uuid4().hex[:12]
        cid = run(["run", "-d", "--rm", "--network=none", "--memory=128m", "--cpus=1", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges", "--user=1000:1000",
                   "--label=openshell.ai/sandbox-namespace=" + sandbox,
                   "--label=openshell.ai/sandbox-name=" + sandbox,
                   "--label=openshell.ai/sandbox-id=" + sandbox,
                   *mounts, "--entrypoint=/bin/sleep", image, "300"]).stdout.strip()
        assert len(cid) == 64
        owned.append(cid)
        return ProtectedProbeTarget(container_id=cid, image_digest=image, namespace=sandbox,
                                    sandbox_name=sandbox, sandbox_id=sandbox, uid=1000,
                                    allow_path="/opt/siq-behavior/allow", deny_path="/opt/siq-behavior/deny",
                                    probe_sha256=expected_sha)

    def reject(name, target):
        try:
            RootfulDockerProbeGuard(target).verify()
        except AdapterError as error:
            assert str(error) == "behavior_program_protection_unverified"
            checks[name] = True
        else:
            raise AssertionError("unsafe target accepted: " + name)

    try:
        assert run(["image", "inspect", BASE, "--format", "{{.Id}}" ]).stdout.strip() == BASE
        context = out / "image-context"
        context.mkdir(mode=0o700)
        shutil.copyfile(source, context / "probe")
        (context / "Dockerfile").write_text(
            f"FROM {BASE}\nUSER root\n"
            "COPY --chown=0:0 probe /opt/siq-behavior/allow\n"
            "COPY --chown=0:0 probe /opt/siq-behavior/deny\n"
            "RUN mkdir -p /opt/siq-behavior-writable && cp /opt/siq-behavior/allow /opt/siq-behavior-writable/probe "
            "&& chmod 0777 /opt/siq-behavior-writable "
            "&& ln -s /opt/siq-behavior/allow /opt/siq-behavior/link "
            "&& cp /bin/true /opt/siq-behavior/wrong "
            "&& chmod 0555 /opt/siq-behavior /opt/siq-behavior/allow /opt/siq-behavior/deny /opt/siq-behavior/wrong\n"
            "USER sandbox\n"
        )
        iid = out / "image-id"
        built = run(["build", "--network=none", "--pull=false", "--iidfile", str(iid), str(context)])
        (out / "build.log").write_text(built.stdout + built.stderr)
        image = iid.read_text().strip()
        result["image_digest"] = image
        target = launch(image)
        guard = RootfulDockerProbeGuard(target)
        initial = guard.verify()
        assert guard.verify() == initial
        schema = json.loads((ROOT / "packages/contracts/openshell-behavior-protection.v1.schema.json").read_text())
        Draft202012Validator(schema).validate(initial["facts"])
        (out / "protected.json").write_text(json.dumps(initial, indent=2) + "\n")
        checks["daemon_observed_static_elf_and_protected_parents"] = True
        checks["unchanged_target_digest_stable_and_schema_valid"] = True
        for name, changed in (
            ("symlink_rejected", replace(target, deny_path="/opt/siq-behavior/link")),
            ("writable_parent_rejected", replace(target, deny_path="/opt/siq-behavior-writable/probe")),
            ("different_program_rejected", replace(target, deny_path="/opt/siq-behavior/wrong")),
            ("wrong_image_rejected", replace(target, image_digest="sha256:" + "0" * 64)),
            ("wrong_namespace_rejected", replace(target, namespace="different")),
            ("wrong_sandbox_id_rejected", replace(target, sandbox_id="different")),
        ):
            reject(name, changed)
        code = (
            "import os,sys\n"
            "try:\n f=os.open('/opt/siq-behavior/allow',os.O_WRONLY);os.close(f)\n"
            "except PermissionError: sys.exit(0)\n"
            "sys.exit(1)\n"
        )
        run(["exec", "--user=1000:1000", target.container_id, "/usr/bin/python3", "-I", "-c", code])
        checks["actual_workload_uid_cannot_open_program_for_write"] = True
        # Alter only our disposable container, then restore and independently re-read.
        run(["exec", "--user=0:0", target.container_id, "/bin/chmod", "0777", target.deny_path])
        reject("writable_program_rejected", target)
        run(["exec", "--user=0:0", target.container_id, "/bin/chmod", "0555", target.deny_path])
        assert guard.verify() == initial
        checks["restored_permissions_reverified"] = True
        mounted = launch(image, mounts=("--mount", f"type=bind,src={source},dst=/opt/siq-behavior/allow,readonly"))
        reject("same_bytes_readonly_overlay_rejected", mounted)
        result["passed"] = True
    finally:
        cleanup = {}
        for cid in reversed(owned):
            cleanup[cid] = run(["rm", "-f", cid], required=False).returncode == 0
        result["owned_containers_removed"] = bool(owned) and all(cleanup.values())
        result["passed"] = result["passed"] and result["owned_containers_removed"]
        (out / "cleanup.json").write_text(json.dumps(cleanup, indent=2) + "\n")
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": len(checks),
                      "owned_containers_removed": result["owned_containers_removed"]}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
