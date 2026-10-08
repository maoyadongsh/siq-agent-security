#!/usr/bin/env python3
"""Owned, offline Docker probe for kernel guard + real credential channel.

This verifies components against a pinned image, not OpenShell or business IAM.
No production service, model, provider environment or user asset is involved.
"""

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from build_native_overlay import IMAGE

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "adapters/runtime/hermes-agentshield"
PYTHON = "/opt/siq/hermes/venv/bin/python"
spec = importlib.util.spec_from_file_location("siq_guard_probe", ADAPTER / "host_runtime.py",
                                             submodule_search_locations=[str(ADAPTER)])
guard_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard_module
spec.loader.exec_module(guard_module)
channel = sys.modules[spec.name + ".native_channel"]

BOOTSTRAP = '''import pathlib, sys, time
sys.path.insert(0, "/siq-code")
from native_channel import HermesChannel
path = pathlib.Path("/siq-channel/native-host.sock")
deadline = time.monotonic() + 90
while not path.exists():
    if time.monotonic() >= deadline:
        raise SystemExit(2)
    time.sleep(.05)
response = HermesChannel(path, timeout=5).exchange({"kind": "guard-probe"})
if response != {"accepted": True}:
    raise SystemExit(3)
print("guard-channel-accepted", flush=True)
time.sleep(180)
'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def docker(*args, timeout=15):
    result = subprocess.run(["/usr/bin/docker", *args], capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("runtime_guard_probe_docker_failed")
    return result.stdout


def inspect(cid):
    # Deliberately exclude Config.Env and unneeded service state.
    fields = ("Id", "Image", "State.Pid", "State.Running", "HostConfig.ReadonlyRootfs",
              "HostConfig.Privileged", "HostConfig.CapDrop", "HostConfig.CapAdd",
              "HostConfig.SecurityOpt", "HostConfig.NetworkMode", "HostConfig.RestartPolicy.Name",
              "Config.User", "Mounts", "Path", "Args")
    raw = docker("inspect", "--format", "\n".join("{{json ." + field + "}}" for field in fields), cid)
    rows = raw.decode().splitlines()
    if len(rows) != len(fields):
        raise RuntimeError("runtime_guard_probe_inspect_failed")
    return dict(zip(fields, map(json.loads, rows), strict=True))


def remove_owned(cidfile):
    if cidfile.exists():
        cid = cidfile.read_text().strip()
        if len(cid) == 64 and all(c in "0123456789abcdef" for c in cid):
            subprocess.run(["/usr/bin/docker", "rm", "-f", cid], capture_output=True, timeout=15, check=False)


@contextlib.contextmanager
def owned_container(base, mounts, *, writable_code=False, shadow=None):
    cidfile = base / "cid"
    cidfile.unlink(missing_ok=True)  # Only this probe's private temporary file.
    args = ["run", "-d", "--rm", "--pull=never", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
            "--cidfile", str(cidfile)]
    for mount in mounts:
        readonly = "" if writable_code and mount["kind"] == "code" else ",readonly"
        args += ["--mount", f"type=bind,src={mount['source']},dst={mount['target']}{readonly}"]
    if shadow:
        args += ["--mount", f"type=bind,src={shadow},dst=/siq-code/shadow,readonly"]
    args += ["--entrypoint", PYTHON, IMAGE, "-I", "-B", "/siq-code/bootstrap.py"]
    try:
        docker(*args)
        cid = cidfile.read_text().strip()
        yield cid, inspect(cid)
    finally:
        remove_owned(cidfile)


def run(output):
    if sys.platform != "linux" or os.getuid() == 0:
        raise RuntimeError("runtime_guard_probe_requires_nonroot_linux")
    checks = {}

    def rejected(name, action):
        try:
            value = action()
        except guard_module.RuntimeGuardError as error:
            assert str(error) == "native_runtime_unverified"
            checks[name] = True
        else:
            if isinstance(value, guard_module.RuntimeGuard):
                value.close()
            raise AssertionError("runtime_guard_probe_expected_rejection:" + name)

    with tempfile.TemporaryDirectory(prefix="siq-kernel-guard-") as scratch:
        base = Path(scratch)
        for name in ("code", "skill", "channel"):
            (base / name).mkdir(mode=0o700)
        code = base / "code"
        (code / "bootstrap.py").write_text(BOOTSTRAP)
        shutil.copyfile(ADAPTER / "native_channel.py", code / "native_channel.py")
        (base / "skill/SKILL.md").write_text("Synthetic runtime-guard probe skill.\n")
        for path in (*code.iterdir(), base / "skill/SKILL.md"):
            path.chmod(0o644)
        mounts = [{"source": str(base / name), "target": "/siq-" + name, "kind": name}
                  for name in ("code", "skill", "channel")]
        files = {"/siq-code/" + p.name: digest(p.read_bytes()) for p in code.iterdir()}
        # Independently derive interpreter hash from the fixed image before the
        # guarded launch; do not accept the observed process as its own baseline.
        extract = "import hashlib; print(hashlib.sha256(open('/proc/self/exe','rb').read()).hexdigest())"
        extractor = base / "extractor-id"
        try:
            executable = docker("run", "--rm", "--cidfile", str(extractor), "--pull=never", "--network=none", "--read-only",
                                "--cap-drop=ALL", "--security-opt=no-new-privileges",
                                "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", PYTHON,
                                IMAGE, "-I", "-B", "-c", extract).decode().strip()
        finally:
            remove_owned(extractor)
        guard_module._hash(executable)
        artifact = digest(json.dumps({"image": IMAGE, "files": files, "executable": executable}, sort_keys=True).encode())
        argv_hash = digest(b"\0".join(p.encode() for p in (PYTHON, "-I", "-B", "/siq-code/bootstrap.py")) + b"\0")

        def options(cid, initial, *, check_backend_mounts=True):
            pid = initial["State.Pid"]

            def verify_backend(actual_pid, uid, gid, actual_artifact):
                info = inspect(cid)
                assert (actual_pid, uid, gid, actual_artifact) == (pid, os.getuid(), os.getgid(), artifact)
                assert info["Id"] == cid and info["Image"] == IMAGE and info["State.Pid"] == pid and info["State.Running"]
                assert info["HostConfig.ReadonlyRootfs"] and not info["HostConfig.Privileged"]
                assert info["HostConfig.CapDrop"] == ["ALL"] and not info["HostConfig.CapAdd"]
                assert info["HostConfig.SecurityOpt"] == ["no-new-privileges"]
                assert info["HostConfig.NetworkMode"] == "none" and info["HostConfig.RestartPolicy.Name"] == "no"
                assert info["Config.User"] == f"{uid}:{gid}"
                assert info["Path"] == PYTHON and info["Args"] == ["-I", "-B", "/siq-code/bootstrap.py"]
                if check_backend_mounts:
                    actual = {(m["Source"], m["Destination"], m["RW"], m["Type"]) for m in info["Mounts"]}
                    assert actual == {(m["source"], m["target"], False, "bind") for m in mounts}

            return {"pid": pid, "uid": os.getuid(), "gid": os.getgid(), "artifact_sha256": artifact,
                    "executable_sha256": executable, "argv_sha256": argv_hash, "mounts": mounts,
                    "code_files": files, "verify_backend": verify_backend}

        with owned_container(base, mounts) as (cid, initial):
            opts = options(cid, initial)
            with guard_module.RuntimeGuard(**opts) as guard:
                guard.verify_mount(str(base / "skill"), "/siq-skill")
                checks["actual_process_code_and_readonly_mounts"] = True
                observed = []
                with channel.HostChannel(base / "channel", guard.peer, timeout=5) as host:
                    def dispatch(event):
                        guard.verify()
                        observed.append(event)
                        return {"accepted": True}
                    host.serve_once(dispatch)
                assert observed == [{"kind": "guard-probe"}]
                deadline = time.monotonic() + 2
                while docker("logs", cid).strip() != b"guard-channel-accepted":
                    assert time.monotonic() < deadline, "runtime_guard_probe_missing_client_ack"
                    time.sleep(.05)
                checks["guarded_kernel_credential_channel"] = True

            for key, value in (("argv_sha256", "0" * 64), ("executable_sha256", "0" * 64),
                               ("gid", os.getgid() + 1), ("artifact_sha256", "0" * 64),
                               ("code_files", dict.fromkeys(files, "0" * 64))):
                rejected("wrong_" + key, lambda key=key, value=value: guard_module.RuntimeGuard(**(opts | {key: value})))
            rejected("backend_missing", lambda: guard_module.RuntimeGuard(**(opts | {"verify_backend": None})))
            wrong_source = [m | ({"source": str(base / "skill")} if m["kind"] == "code" else {}) for m in mounts]
            rejected("wrong_host_object", lambda: guard_module.RuntimeGuard(**(opts | {"mounts": wrong_source})))

            for name, mutate, restore in (
                ("undeclared_file", lambda: ((code / "extra.py").write_text("pass\n"), (code / "extra.py").chmod(0o644)), lambda: (code / "extra.py").unlink()),
                ("undeclared_directory", lambda: (code / "extra-dir").mkdir(mode=0o700), lambda: (code / "extra-dir").rmdir()),
                ("code_symlink", lambda: (code / "alias.py").symlink_to("bootstrap.py"), lambda: (code / "alias.py").unlink()),
                ("changed_code", lambda: (code / "bootstrap.py").write_text(BOOTSTRAP + "\n# changed\n"),
                 lambda: (code / "bootstrap.py").write_text(BOOTSTRAP)),
            ):
                with guard_module.RuntimeGuard(**opts) as guard:
                    mutate()
                    try:
                        rejected(name, guard.verify)
                    finally:
                        restore()
                    rejected(name + "_cannot_restore_trust", guard.verify)

            with guard_module.RuntimeGuard(**opts) as guard:
                rejected("unregistered_skill_mount", lambda: guard.verify_mount(str(base / "skill"), "/other-skill"))
            with guard_module.RuntimeGuard(**opts) as guard:
                docker("stop", "--time", "1", cid)
                rejected("exited_process", guard.verify)

        # Leave mount validation deliberately to the kernel checker for these
        # negative cases. The real backend still proves process/image/config.
        # This prevents a Docker RW flag check from masking a broken proc check.
        with owned_container(base, mounts, writable_code=True) as (cid, initial):
            rejected("kernel_rejects_writable_mount", lambda: guard_module.RuntimeGuard(**options(cid, initial, check_backend_mounts=False)))
        (base / "shadow").mkdir(mode=0o700)
        (code / "shadow").mkdir(mode=0o700)
        with owned_container(base, mounts, shadow=base / "shadow") as (cid, initial):
            rejected("kernel_rejects_shadow_mount", lambda: guard_module.RuntimeGuard(**options(cid, initial, check_backend_mounts=False)))

    result = {"schema_version": "siq.native-runtime-guard-probe/v1", "base_image_id": IMAGE,
              "artifact_sha256": artifact, "checks": checks, "model_calls": 0,
              "backend": "owned_offline_docker", "openshell_business_acceptance": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks_passed": len(checks), "model_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
