"""Opt-in systemd integration using one disposable runtime-only user unit.

Never enables login startup or changes a pre-existing unit. Requires a trusted
native SIQ_TEST_BINARY and SIQ_TEST_SYSTEMD=1; this is Linux service evidence,
not intelligent-agent platform acceptance.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("SIQ_TEST_SYSTEMD") != "1"
    or not os.environ.get("SIQ_TEST_BINARY"),
    reason="requires explicit native binary and opt-in Linux user systemd environment",
)


def test_real_user_service_restart_and_cleanup(tmp_path):
    systemctl = shutil.which("systemctl")
    assert systemctl, "systemctl unavailable"
    # Both executable and state paths exercise systemd quoting, not just a
    # renderer's string comparison. No real user instance is selected.
    binary = tmp_path / 'binary % space'
    shutil.copy2(os.environ["SIQ_TEST_BINARY"], binary)
    binary.chmod(0o700)
    state = tmp_path / 'state $HOME %h "quoted" space'
    env = {**os.environ, "SIQ_AGENT_SECURITY_STATE_DIR": str(state)}
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    subprocess.run(
        [str(binary), "init", "--port", str(port)], env=env,
        capture_output=True, timeout=15, check=True,
    )
    identity = (state / "local-instance.json").read_bytes()
    configuration = (state / "config.json").read_bytes()
    prepared = subprocess.run(
        [str(binary), "service-prepare"], env=env,
        capture_output=True, text=True, timeout=10, check=True,
    )
    record = json.loads(prepared.stdout)
    name = record["unit_name"]
    unit = state / name

    def control(*args, check=True):
        return subprocess.run(
            [systemctl, "--user", *args], capture_output=True, text=True,
            timeout=45, check=check,
        )

    def property_value(key):
        return control("show", name, "--property=" + key, "--value").stdout.strip()

    def ready():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = subprocess.run(
                [str(binary), "status"], env=env, capture_output=True,
                text=True, timeout=7, check=False,
            )
            if result.returncode == 0:
                assert json.loads(result.stdout)["status"] == "ready"
                assert property_value("ActiveState") == "active"
                return
            assert property_value("ActiveState") != "failed", "isolated service failed"
            time.sleep(0.1)
        pytest.fail("isolated service never became ready")

    assert property_value("LoadState") == "not-found", "generated unit name already exists"
    linked = False
    try:
        # Mark cleanup eligible before invocation: link may succeed even if
        # reload/readback fails, and ownership is rechecked in finally.
        linked = True
        for _ in range(2):
            subprocess.run(
                [str(binary), "service-register", "--runtime"], env=env,
                capture_output=True, text=True, timeout=45, check=True,
            )
        assert property_value("UnitFileState") == "linked-runtime"
        assert property_value("ActiveState") == "inactive"
        assert property_value("MainPID") == "0"
        # A request to change scope must not silently create a persistent link.
        conflict = subprocess.run(
            [str(binary), "service-register"], env=env,
            capture_output=True, text=True, timeout=20, check=False,
        )
        assert conflict.returncode != 0
        assert property_value("UnitFileState") == "linked-runtime"
        assert Path(property_value("FragmentPath")).resolve(strict=True) == unit
        assert property_value("StandardOutput") == "null"
        assert property_value("StandardError") == "null"
        subprocess.run(
            [str(binary), "service-start"], env=env,
            capture_output=True, timeout=45, check=True,
        )
        ready()
        pid = property_value("MainPID")
        assert int(pid) > 0
        # Repeated start must not create another process or regenerate state.
        subprocess.run(
            [str(binary), "service-start"], env=env,
            capture_output=True, timeout=45, check=True,
        )
        assert property_value("MainPID") == pid
        reused = subprocess.run(
            [str(binary), "start"], env=env, capture_output=True,
            text=True, timeout=10, check=True,
        )
        assert json.loads(reused.stdout)["status"] == "ready"
        refused = subprocess.run(
            [str(binary), "service-stop"], env=env,
            capture_output=True, timeout=10, check=False,
        )
        running_removal = subprocess.run(
            [str(binary), "service-unregister", "--confirm-unregister"], env=env,
            capture_output=True, timeout=15, check=False,
        )
        assert running_removal.returncode != 0
        assert refused.returncode != 0
        assert property_value("MainPID") == pid
        subprocess.run(
            [str(binary), "service-status"], env=env,
            capture_output=True, timeout=15, check=True,
        )
        subprocess.run(
            [str(binary), "service-stop", "--confirm-stop"], env=env,
            capture_output=True, timeout=45, check=True,
        )
        subprocess.run(
            [str(binary), "service-start"], env=env,
            capture_output=True, timeout=45, check=True,
        )
        ready()
        assert property_value("MainPID") != pid
        assert (state / "local-instance.json").read_bytes() == identity
        assert (state / "config.json").read_bytes() == configuration
        # Pairing is obtained interactively; never print or persist its output.
        paired = subprocess.run(
            [str(binary), "pair"], env=env, capture_output=True, timeout=10, check=False,
        )
        assert paired.returncode == 0
        subprocess.run(
            [str(binary), "service-stop", "--confirm-stop"], env=env,
            capture_output=True, timeout=45, check=True,
        )
        subprocess.run(
            [str(binary), "service-status"], env=env,
            capture_output=True, timeout=15, check=True,
        )
        assert property_value("ActiveState") == "inactive"
        assert property_value("Result") == "success"
        assert not (state / "serve.lock").exists()
        retained = {p: p.read_bytes() for p in [
            state / "local-instance.json", state / "config.json",
            state / "user-service.json", state / "keys" / "signing.seed", unit,
        ]}
        for _ in range(2):
            subprocess.run(
                [str(binary), "service-unregister", "--confirm-unregister"], env=env,
                capture_output=True, timeout=45, check=True,
            )
        assert property_value("LoadState") == "not-found"
        linked = False
        for path, content in retained.items():
            assert path.read_bytes() == content

    finally:
        if linked:
            # Only act on the uniquely named unit if its loaded source is ours.
            assert Path(property_value("FragmentPath")).resolve(strict=True) == unit, (
                "unit ownership changed; cleanup refused"
            )
            stopped = control("stop", name, check=False)
            assert stopped.returncode == 0 or property_value("LoadState") == "bad-setting"
            assert property_value("MainPID") == "0", "owned service did not stop"
            control("disable", "--runtime", name)
            control("daemon-reload")
            assert property_value("LoadState") == "not-found"
