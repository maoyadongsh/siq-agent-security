"""Owned Docker + host bwrap acceptance, no production identity or database access."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps/control-api"
sys.path.insert(0, str(API))

from app.scan_isolation import command  # noqa: E402
from app.scan_transport import exchange  # noqa: E402


def run(args, *, source=None, timeout=30):
    result = subprocess.run(args, input=source, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"acceptance command failed ({args[0]}), exit {result.returncode}: {result.stderr[-1500:]}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Freshly built candidate Control API image")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0 or args.output.exists():
        parser.error("run as non-root and select a new evidence output path")
    image = json.loads(run(["docker", "image", "inspect", args.image]))[0]["Id"]
    name = "siq-scan-acceptance-" + uuid.uuid4().hex[:12]
    report = {"schema_version": "isolated-scan-acceptance/v1", "status": "incomplete", "image_id": image,
              "host_uid": os.geteuid(), "client_uid": 10001, "checks": {}, "cleanup": {}}
    service = None
    container = False
    probe_path = Path(__file__).with_name("container_probe.py")
    probe = probe_path.read_text()
    report["probe_sha256"] = hashlib.sha256(probe.encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="siq-scan-live-") as directory:
        folder = Path(directory)
        folder.chmod(0o710)
        endpoint = folder / "scan.sock"

        def start_service():
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", "app.scan_service", "--socket", str(endpoint),
                 "--client-uid", "10001"], cwd=API,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("host scan service did not start")
                if endpoint.exists():
                    return process
                time.sleep(.05)
            process.terminate()
            process.wait(10)
            raise RuntimeError("host scan service startup deadline")

        def stop_service(process):
            process.terminate()
            _, error = process.communicate(timeout=12)
            if process.returncode != 0 or error or endpoint.exists():
                raise RuntimeError("host scan service cleanup failed")

        def check(phase):
            data = json.loads(run(["docker", "exec", "-i", name, "python", "-", phase], source=probe))
            if not data or any(value is not True for value in data.values()):
                raise RuntimeError("acceptance oracle failed")
            report["checks"].update(data)
            print(phase + ": passed", flush=True)

        try:
            marker = folder / "host-private"
            marker.write_text("synthetic scan acceptance file")
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                port = listener.getsockname()[1]
                code = f'''import os,socket
assert not os.path.exists({str(marker)!r})
try:
 open('/scan/app/forbidden-acceptance-write','w')
 raise AssertionError('writable code')
except OSError: pass
s=socket.socket(); s.settimeout(.2)
assert s.connect_ex(('127.0.0.1',{port})) != 0
print('isolated')'''
                assert exchange(command("bwrap", code=code), b"") == b"isolated\n"
            report["checks"]["native_private_file_readonly_code_network_isolation"] = True
            service = start_service()
            first_inode = endpoint.stat().st_ino
            env = {"SIQ_AS_DEV": "1", "SIQ_AS_ALLOW_SQLITE": "1",
                   "SIQ_AS_DATABASE_URL": "sqlite:////tmp/scan-acceptance.sqlite",
                   "SIQ_AS_SIGNING_KEY_FILE": "/tmp/scan-acceptance.seed",
                   "SIQ_AS_THREAT_SCAN_ISOLATION": "bwrap-service",
                   "SIQ_AS_THREAT_SCAN_SOCKET": "/run/siq-scan/scan.sock",
                   "SIQ_AS_THREAT_SCAN_SERVICE_UID": str(os.geteuid())}
            argv = ["docker", "run", "-d", "--name", name, "--network", "none", "--read-only",
                    "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory=768m", "--pids-limit=256",
                    "--cpus=2", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=128m",
                    "--user", "10001:10001", "--group-add", str(os.getgid()),
                    "--mount", f"type=bind,source={folder},target=/run/siq-scan,readonly"]
            for key, value in env.items():
                argv += ["-e", f"{key}={value}"]
            argv += [image, "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8600"]
            container = True
            run(argv)
            for attempt in range(60):
                try:
                    check("ready")
                    break
                except RuntimeError:
                    running = json.loads(run(["docker", "inspect", name]))[0]["State"]["Running"]
                    if not running or attempt == 59:
                        raise
                    time.sleep(.2)
            info = json.loads(run(["docker", "inspect", name]))[0]
            state = run(["docker", "exec", name, "cat", "/proc/1/status"])
            apparmor = run(["docker", "exec", name, "cat", "/proc/1/attr/current"]).strip()
            assert info["HostConfig"]["Privileged"] is False and info["HostConfig"]["ReadonlyRootfs"] is True
            assert info["HostConfig"]["NetworkMode"] == "none" and info["HostConfig"]["CapDrop"] == ["ALL"]
            assert "Seccomp:\t2" in state and "NoNewPrivs:\t1" in state and "docker-default" in apparmor
            assert all(not mount["RW"] for mount in info["Mounts"] if mount["Type"] == "bind")
            report["runtime"] = {"security_opt": info["HostConfig"]["SecurityOpt"], "apparmor": apparmor,
                                 "network": "none", "rootfs_readonly": True, "cap_drop": ["ALL"],
                                 "seccomp_filter": True, "no_new_privileges": True}
            check("normal")
            denied = """from app.scan_execution import analyze
from app.scan_transport import ScanFailure
try:
 analyze(b'echo denied',filename='x.sh')
 raise AssertionError('unauthorized peer accepted')
except ScanFailure:
 print('denied')
"""
            assert run(["docker", "exec", "--user", f"10002:{os.getgid()}", "-i", name,
                        "python", "-"], source=denied).strip() == "denied"
            report["checks"]["wrong_client_uid_denied"] = True
            folder.chmod(0o730)
            try:
                check("endpoint-drift")
            finally:
                folder.chmod(0o710)
            stop_service(service)
            service = None
            check("unavailable")
            service = start_service()
            report["restart_socket_inode_changed"] = endpoint.stat().st_ino != first_inode
            check("recovered")
        finally:
            try:
                if service is not None:
                    stop_service(service)
                report["cleanup"]["service_stopped_and_socket_removed"] = not endpoint.exists()
            finally:
                if container:
                    logs = subprocess.run(["docker", "logs", "--tail", "35", name],
                                          text=True, capture_output=True, timeout=10)
                    report["synthetic_container_log_tail"] = (logs.stdout + logs.stderr)[-6000:]
                    run(["docker", "rm", "-f", name])
                report["cleanup"]["owned_container_removed"] = not run(
                    ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"]).strip()
                args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    report["cleanup"]["owned_directory_removed"] = not folder.exists()
    report["status"] = "passed"
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
