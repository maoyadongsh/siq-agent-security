"""Isolated real user-service lifecycle for existing native/browser journeys."""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import tempfile
from contextlib import contextmanager
from pathlib import Path

from installed_user_service_driver import InstalledUserServiceDriver


def manager_environment():
    return subprocess.check_output(["systemctl", "--user", "show-environment"], timeout=15)


@contextmanager
def fixture_directory(args, cleanup):
    root = Path(tempfile.mkdtemp(prefix="siq-background-acceptance-"))
    try:
        yield str(root)
    finally:
        if not args.background_service or cleanup["safe"]:
            shutil.rmtree(root)
        else:
            path = args.out_dir / "private-recovery-location.json"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump({"isolated_root": str(root), "reason": "cleanup_not_confirmed"}, stream)


class IsolatedDriver(InstalledUserServiceDriver):
    def _env(self):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("SIQ_", "AGENTSHIELD_"))}
        return {**env, "SIQ_AGENT_SECURITY_STATE_DIR": self.state_dir}


class BackgroundSetupMixin:
    """Compose with the existing synthetic native-tool harness, not product code."""

    def __init__(self, root, args):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.service_port = sock.getsockname()[1]
        self.manager_before = manager_environment()
        manager = dict(line.split(b"=", 1) for line in self.manager_before.splitlines() if b"=" in line)
        forbidden = [b"HERMES_HOME", b"OPENCLAW_STATE_DIR", b"OPENCLAW_CONFIG_PATH",
                     b"SIQ_AGENT_SECURITY_HERMES_CLI", b"SIQ_AGENT_SECURITY_SIGNING_SEED", b"AGENTSHIELD_SIGNING_SEED"]
        if any(manager.get(key) for key in forbidden):
            raise RuntimeError("shared_manager_framework_override_prevents_isolation")
        super().__init__(root, args)
        home = Path(self.env["HOME"])
        shutil.copytree(root / "hermes", home / ".hermes")
        self.env["HERMES_HOME"] = str(home / ".hermes/profiles/work")
        self.driver = IsolatedDriver(str(self.state), self.service_port, cli_timeout=120)
        self.service_checks = {}
        self.first_identity = None
        self.first_key = None
        self.previous_pid = None
        self.service_started = False
        self.setup_attempted = False

    def config(self, enforcement):
        (self.state / "config.json").write_text(json.dumps({
            "intent_enforcement": enforcement, "enforcement_mode": "block",
            "port": self.service_port, "linux_service_home": str(self.root / "home"),
        }))

    def start(self):
        self.endpoint = f"http://127.0.0.1:{self.service_port}"
        self.env["SIQ_AGENT_SECURITY_ENDPOINT"] = self.endpoint
        self.setup_attempted = True
        started = time.monotonic()
        self.driver.setup(str(self.binary), self.service_port)
        self.setup_seconds = round(time.monotonic() - started, 3)
        self.service_started = True
        identity = self.driver.identity()
        assert identity["binary_digest"] == hashlib.sha256(self.binary.read_bytes()).hexdigest()
        assert identity["active_state"] == "active"
        assert Path(identity["fragment_path"]).resolve() == (self.state / self.driver.unit_name()).resolve()
        assert identity["running_binary_path"] == str(self.binary)
        pid = int(identity["main_pid"])
        assert pid > 1 and hashlib.sha256(Path(f"/proc/{pid}/exe").read_bytes()).hexdigest() == identity["binary_digest"]
        environ = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        assert ("HOME=" + self.env["HOME"]).encode() in environ
        assert ("SIQ_AGENT_SECURITY_STATE_DIR=" + str(self.state)).encode() in environ
        props = self.driver.unit_properties(self.driver.unit_name(), ["UnitFileState"])
        assert props["UnitFileState"] == "linked-runtime"
        key = self.driver.pubkey(str(self.binary))
        stable = {k: identity[k] for k in ("state_directory_id", "binary_digest", "port", "unit_name", "fragment_path", "running_binary_path")}
        if self.first_identity is None:
            self.first_identity, self.first_key = stable, key
        else:
            assert stable == self.first_identity and key == self.first_key
            assert identity["main_pid"] != self.previous_pid
            self.service_checks["restart_preserves_identity_with_new_pid"] = True
        self.driver.setup(str(self.binary), self.service_port)
        assert self.driver.identity() == identity
        self.service_checks["duplicate_setup_reuses_healthy_pid"] = True
        wrong = self.driver.run_cli(str(self.binary), ["setup", "--confirm-setup", "--runtime", "--port",
                                                       str(1 if self.service_port != 1 else 2)], check=False)
        assert wrong["exit"] != 0 and self.driver.identity() == identity
        self.service_checks["conflicting_port_refused_without_restart"] = True
        self.service_checks["runtime_unit_actual_binary_and_isolated_home_verified"] = True
        assert manager_environment() == self.manager_before
        self.admin = self.driver.pair(str(self.binary))
        self.previous_pid = identity["main_pid"]

    def stop(self, *, kill=False):
        assert not kill, "background lifecycle cannot fall back to killing a process"
        if self.service_started:
            self.driver.service_stop(str(self.binary))
            props = self.driver.unit_properties(self.driver.unit_name(), ["ActiveState", "MainPID"])
            assert props == {"ActiveState": "inactive", "MainPID": "0"}
            self.service_started = False
            self.service_checks["supported_service_stop_verified"] = True

    def _teardown(self):
        # Failed initialization may have created no unit at all. Do not call a
        # preparation path that would itself try to create a missing identity.
        if not list(self.state.glob("siq-agent-security-*.service")):
            assert not self.service_started
            return
        self.driver.teardown(str(self.binary))
        unit = self.driver.unit_name()
        result = subprocess.run(["systemctl", "--user", "show", unit, "--property=LoadState", "--property=MainPID"],
                                capture_output=True, text=True, timeout=15, check=False)
        props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        assert props.get("LoadState") == "not-found" and props.get("MainPID") == "0"
        self.service_started = False
        self.service_checks["teardown_unregistered_owned_unit"] = True

    def close(self, *, verify_reentry):
        if not self.setup_attempted:
            return
        try:
            if verify_reentry:
                before = [row["activity_id"] for row in self.api("/v1/task-activities?view=tasks")["items"]]
                assert before
                self._teardown()
                assert (self.state / "config.json").is_file()
                self.start()
                after = [row["activity_id"] for row in self.api("/v1/task-activities?view=tasks")["items"]]
                assert after == before
                self.service_checks["teardown_reentry_retains_run_history"] = True
        finally:
            self._teardown()
            assert manager_environment() == self.manager_before
            self.service_checks["shared_manager_environment_unchanged"] = True
