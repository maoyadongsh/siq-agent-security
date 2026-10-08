"""Offline real gateway startup; synthetic socket only, no Authority or model."""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

root = Path("/tmp/native-gateway-probe")
root.mkdir(mode=0o700)
home = root / "hermes"
home.mkdir(mode=0o700)
(home / "config.yaml").write_text("model:\n  default: unused-offline-model\nmemory:\n  memory_enabled: false\n  user_profile_enabled: false\n")
key = secrets.token_hex(32)
environment = {k: v for k, v in os.environ.items() if not k.startswith(("SIQ_AGENT_SECURITY_", "HERMES_"))}
environment.update(HOME=str(root), HERMES_HOME=str(home), HERMES_RUNTIME_HOME=str(home),
                   HERMES_RELAY_ENABLED="false", API_SERVER_KEY=key, API_SERVER_HOST="127.0.0.1",
                   API_SERVER_PORT="28651", TERMINAL_ENV="local")
argv = ["/opt/siq/hermes/venv/bin/python", "-I", "-B", "/opt/hermes-agent/hermes-gateway",
        "hri-" + "a" * 32, "siq:openshell:pool:" + "a" * 24 + ":qwen-request-2222222222222222:siq_analysis",
        str(root / "channel")]
checks = {}
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
log_path = root / "gateway.log"


def health(credential):
    request = urllib.request.Request("http://127.0.0.1:28651/health/detailed",
                                     headers={"Authorization": "Bearer " + credential})
    try:
        with opener.open(request, timeout=1) as response:
            return response.status, json.loads(response.read(65536))
    except urllib.error.HTTPError as error:
        return error.code, {}


with log_path.open("wb") as log:
    child = subprocess.Popen(argv, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("gateway_probe_child_exited_before_ready")
            rows = [line.removeprefix("SIQ_NATIVE_GATEWAY_READY=") for line in log_path.read_text().splitlines()
                    if line.startswith("SIQ_NATIVE_GATEWAY_READY=")]
            if rows:
                ready = json.loads(rows[0])
                break
            time.sleep(.1)
        else:
            raise RuntimeError("gateway_probe_ready_timeout")
        checks["bootstrap_ready_remains_unverified"] = ready["runtime_state"] == "unverified"
        checks["bootstrap_pid_is_gateway_process"] = ready["pid"] == child.pid
        before = Path(f"/proc/{child.pid}/cmdline").read_bytes()
        checks["actual_argv_matches_fixed_entry"] = before == b"\0".join(item.encode() for item in argv) + b"\0"
        # This socket coordinates startup only. No fake allow callback is used,
        # and no task is submitted. It cannot satisfy PID-namespace authentication.
        listener.bind(str(root / "channel/native-host.sock"))
        (root / "channel/native-host.sock").chmod(0o600)
        listener.listen(1)
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("gateway_probe_child_exited_before_health")
            try:
                status, body = health(key)
                if status == 200:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.2)
        else:
            raise RuntimeError("gateway_probe_health_timeout")
        checks["real_gateway_authenticated_health"] = body.get("platform") == "hermes-agent" and body.get("pid") == child.pid
        checks["invalid_api_key_rejected"] = health("invalid-synthetic-key")[0] == 401
        checks["kernel_argv_unchanged_after_gateway_start"] = Path(f"/proc/{child.pid}/cmdline").read_bytes() == before
        checks["api_key_absent_from_argv"] = key.encode() not in before
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        listener.close()
checks["owned_gateway_exited"] = child.poll() is not None
print(json.dumps({"schema_version": "siq.native-hermes-function-probe/v1", "checks": checks,
                  "probe": "native-gateway-startup", "synthetic_startup_socket": True,
                  "authority_verified": False, "business_entry_acceptance": False, "model_calls": 0,
                  "kernel_argv_sha256": hashlib.sha256(before).hexdigest()}), flush=True)
assert all(checks.values())
