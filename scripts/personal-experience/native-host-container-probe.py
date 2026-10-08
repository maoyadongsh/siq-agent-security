#!/usr/bin/env python3
"""Owned, offline container probe of the native metadata channel, not Hermes E2E."""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKER = "/usr/bin/docker"
PROGRAM = r'''
import json,os,socket,subprocess,sys,time
path='/run/siq-native/native-host.sock'
deadline=time.monotonic()+15
while not os.path.exists(path):
    if time.monotonic()>deadline: raise RuntimeError('probe_socket_unavailable')
    time.sleep(.05)
frame=json.dumps({'schema_version':'native-host-event/v1','sequence':1,'event':{'kind':'synthetic-container-probe'}}).encode()
with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as s:
    s.connect(path)
    child=subprocess.run([sys.executable,'-I','-B','-c',
        'import socket,sys; s=socket.socket(fileno=int(sys.argv[1])); s.send(sys.argv[2].encode()); s.close()',
        str(s.fileno()),frame.decode()],pass_fds=(s.fileno(),),capture_output=True,timeout=5)
    if child.returncode: raise RuntimeError('probe_child_failed')
    if s.recv(65536): raise RuntimeError('probe_child_received_success')
with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as s:
    s.connect(path);s.send(frame);reply=json.loads(s.recv(65536))
    if reply.get('result')!={'synthetic_metadata_accepted':True}: raise RuntimeError('probe_parent_denied')
try:
    open('/run/siq-native/forbidden-write','w').close()
    readonly=False
except OSError:
    readonly=True
print(json.dumps({'allowed_process_received_response':True,'tool_child_received_no_success':True,'socket_mount_readonly':readonly}),flush=True)
'''


def docker(*args):
    result = subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=25, check=False)
    if result.returncode:
        raise RuntimeError("native_container_probe_docker_failed")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", args.image_id) or os.getuid() == 0:
        raise RuntimeError("native_container_probe_input_invalid")
    if docker("image", "inspect", args.image_id, "--format", "{{.Id}}") != args.image_id:
        raise RuntimeError("native_container_probe_image_changed")
    source = ROOT / "adapters/runtime/hermes-agentshield/native_channel.py"
    spec = importlib.util.spec_from_file_location("siq_native_channel", source)
    channel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(channel)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-native-host-") as directory:
        name = "siq-native-peer-" + uuid.uuid4().hex[:12]
        container = docker("create", "--pull=never", "--name", name, "--read-only", "--network", "none",
                           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
                           "--mount", f"type=bind,src={directory},dst=/run/siq-native,readonly",
                           "--entrypoint", "/opt/siq/hermes/venv/bin/python", args.image_id,
                           "-I", "-B", "-c", PROGRAM)
        if not re.fullmatch(r"[a-f0-9]{64}", container):
            raise RuntimeError("native_container_probe_identity_invalid")
        try:
            docker("start", container)
            pid = int(docker("inspect", "--format", "{{.State.Pid}}", container))
            with channel.ProcessPin(pid, os.getuid()) as peer, channel.HostChannel(Path(directory), peer, timeout=5) as host:
                observed = []
                try:
                    host.serve_once(lambda event: observed.append(event) or {"synthetic_metadata_accepted": True})
                    checks["inherited_socket_child_rejected"] = False
                except channel.ChannelError:
                    checks["inherited_socket_child_rejected"] = not observed
                host.serve_once(lambda event: observed.append(event) or {"synthetic_metadata_accepted": True})
                checks["only_pinned_host_visible_pid_dispatched"] = observed == [{"kind": "synthetic-container-probe"}]
                if docker("wait", container) != "0":
                    raise RuntimeError("native_container_probe_runtime_failed")
                logs = docker("logs", container)
                payload = json.loads(logs)
                if set(payload) != {"allowed_process_received_response", "tool_child_received_no_success", "socket_mount_readonly"}:
                    raise RuntimeError("native_container_probe_output_invalid")
                checks.update(payload)
                time.sleep(.05)
                try:
                    peer.check()
                    checks["container_exit_invalidates_pin"] = False
                except channel.ChannelError:
                    checks["container_exit_invalidates_pin"] = True
        finally:
            docker("rm", "-f", container)  # Only the exact container created above.
    result = {"schema_version": "siq.native-host-container-probe/v1", "image_id": args.image_id,
              "scope": "offline_docker_transport_only", "hermes_execution": False, "openshell_execution": False,
              "model_calls": 0, "checks": checks}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not checks or not all(value is True for value in checks.values()):
        raise RuntimeError("native_container_probe_checks_failed")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
