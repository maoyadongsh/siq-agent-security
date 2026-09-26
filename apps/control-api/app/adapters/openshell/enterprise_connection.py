"""Control-plane connection only; cannot enumerate or mutate tenant runtime targets."""

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from urllib.parse import urlparse

from app.adapters.openshell.bounded_command import SAFE_ENV_KEYS, run_bounded
from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError


class ConnectionConfigurationError(ValueError):
    pass


class ReadOnlyConnection(OpenShellCliBackend):
    def __init__(self, environment: dict[str, str]):
        self.binary = environment.get("SIQ_AS_OPENSHELL_CLI_BIN", "")
        self.endpoint = environment.get("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "")
        try:
            parsed = urlparse(self.endpoint)
            port = parsed.port
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path not in ("", "/") or parsed.query
                or parsed.fragment or parsed.params or port == 0
                or any(c.isspace() or ord(c) < 32 for c in self.endpoint)
                or environment.get("SIQ_AS_OPENSHELL_ENV_SH")
                or environment.get("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "0") != "0"
                or not Path(self.binary).is_absolute()):
                raise ValueError("invalid_configuration")
            self._binary_identity()
        except (OSError, ValueError):
            raise ConnectionConfigurationError("configuration_rejected") from None
        self.child_env = {k: v for k, v in environment.items() if k in SAFE_ENV_KEYS}
        self.deadline = time.monotonic() + 10
        super().__init__(runner=self._readonly_runner, env_script="")

    def _binary_identity(self):
        info = os.lstat(self.binary)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or not os.access(self.binary, os.X_OK):
            raise ValueError("invalid_binary")
        return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode]

    def _invocation_fingerprint(self):
        try:
            identity = self._binary_identity()
        except (OSError, ValueError):
            raise AdapterError("connection_configuration_changed") from None
        return hashlib.sha256(json.dumps(
            [self.binary, self.endpoint, self.child_env, identity], sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()

    def _readonly_runner(self, args):
        if tuple(args) not in (("gateway", "info"), ("status",), ("--version",)):
            raise AdapterError("connection_operation_refused")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AdapterError("openshell_command_timeout")
        return run_bounded(
            [self.binary, "--gateway-endpoint", self.endpoint, *args],
            timeout=remaining, environment=self.child_env,
        )


def inspect_connection():
    environment = dict(os.environ)
    result = {
        "schema_version": "enterprise-openshell-connection/v1",
        "scope": "control_plane_connection",
        "status": "not_configured",
        "ready_for_deployment": False,
        "version_compatibility": "unverified",
        "credential_scope": "unverified",
        "execution_evidence": "none",
        "endpoint_fingerprint": None,
        "gateway_name_sha256": None,
        "cli_version": "unknown",
        "gateway_version": "unknown",
        "configuration_capabilities": {},
    }
    if not environment.get("SIQ_AS_OPENSHELL_CLI_BIN") or not environment.get("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT"):
        return result
    try:
        connection = ReadOnlyConnection(environment)
        capabilities = connection.probe()
    except ConnectionConfigurationError:
        result["status"] = "configuration_rejected"
        return result
    except AdapterError:
        result["status"] = "probe_failed"
        return result
    if not capabilities.handshake_verified or not capabilities.endpoint_fingerprint:
        result["status"] = "identity_unverified"
        return result
    result.update(
        status="version_unknown" if capabilities.gateway_version == "unknown" else "handshake_verified",
        endpoint_fingerprint=capabilities.endpoint_fingerprint,
        gateway_name_sha256=hashlib.sha256(capabilities.handshake_gateway.encode()).hexdigest(),
        cli_version=capabilities.cli_version, gateway_version=capabilities.gateway_version,
        configuration_capabilities={
            name: capabilities.can_configure(name) for name in ("network.dynamic_update", "enforcement_mode.block")
        },
    )
    return result
