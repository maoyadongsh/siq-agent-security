#!/usr/bin/env python3
"""Owned, mTLS-authenticated OpenShell fixture; never uses existing gateways.

Standalone preflight is environment evidence only, not a SIQ deployment result.
Official release binaries are verified against the campaign inventory before use.
"""
import argparse
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import Events, clean_environment, sha256, write_json
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class OpenShellFixture:
    def __init__(self, campaign, root, candidate=None):
        self.campaign, self.root = campaign.resolve(), root.resolve()
        self.candidate = candidate
        self.root.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.events = Events(self.root / "events.jsonl", self.root.name)
        self.toolchain = self.campaign / "private/external/openshell-v0.0.104"
        self.name = "siq-tp07-" + secrets.token_hex(6)
        self.target = "tp07-" + secrets.token_hex(6)  # upstream sandbox names <= 19
        self.gateway = self.network_id = self.log = None
        self.cleanup = {}
        self.environment = clean_environment()
        for name in ("CONFIG", "STATE", "DATA", "CACHE"):
            p = self.root / name.lower()
            p.mkdir(mode=0o700)
            self.environment["XDG_" + name + "_HOME"] = str(p)
        self.environment["OPENSHELL_GATEWAY"] = self.name
        self.environment["NO_PROXY"] = "127.0.0.1,localhost"
        self.index = 0

    def command(self, argv, timeout=45, *, environment=None):
        self.index += 1
        prefix = f"command-{self.index:03}"
        self.events.add("command_start", command_id=prefix, argv=argv, timeout=timeout)
        try:
            result = subprocess.run(argv, env=environment or self.environment, cwd=self.root,
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
            (self.root / (prefix + ".stdout")).write_bytes(result.stdout)
            (self.root / (prefix + ".stderr")).write_bytes(result.stderr)
            self.events.add("command_end", command_id=prefix, exit_code=result.returncode,
                            stdout_sha256=hashlib.sha256(result.stdout).hexdigest(), stderr_sha256=hashlib.sha256(result.stderr).hexdigest())
            return result
        except subprocess.TimeoutExpired as exc:
            (self.root / (prefix + ".stdout")).write_bytes(exc.stdout or b"")
            (self.root / (prefix + ".stderr")).write_bytes(exc.stderr or b"")
            self.events.add("command_timeout", command_id=prefix)
            raise RuntimeError("owned_fixture_command_timeout") from None

    def cli(self, *args, timeout=45):
        return self.command([str(self.toolchain / "openshell"), "--gateway", self.name, *args], timeout)

    def certificates(self):
        tls = self.root / "tls"
        tls.mkdir()
        now = datetime.now(timezone.utc)
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self.name + "-ca")])
        ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
              .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .sign(ca_key, hashes.SHA256()))
        (tls / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        for kind in ("server", "client"):
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            names = [x509.NameAttribute(NameOID.COMMON_NAME, self.name + "-" + kind)]
            if kind == "client":
                names.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "openshell-admin"))
            certificate = (x509.CertificateBuilder().subject_name(x509.Name(names)).issuer_name(ca_name)
                           .public_key(key.public_key()).serial_number(x509.random_serial_number())
                           .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
                           .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                           .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if kind == "server" else ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False))
            if kind == "server":
                certificate = certificate.add_extension(x509.SubjectAlternativeName([
                    x509.DNSName("localhost"), x509.DNSName("host.openshell.internal"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            certificate = certificate.sign(ca_key, hashes.SHA256())
            (tls / (kind + ".crt")).write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            (tls / (kind + ".key")).write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                                 serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        client = self.root / "config/openshell/gateways" / self.name / "mtls"
        client.mkdir(parents=True)
        for source, target in (("ca.crt", "ca.crt"), ("client.crt", "tls.crt"), ("client.key", "tls.key")):
            (client / target).write_bytes((tls / source).read_bytes())
        jwt_key = ed25519.Ed25519PrivateKey.generate()
        (tls / "jwt-signing.pem").write_bytes(jwt_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (tls / "jwt-public.pem").write_bytes(jwt_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        (tls / "jwt-kid").write_text(self.name)
        return tls

    def start(self):
        inventory = json.loads((self.campaign / "inventory/openshell-v0104-release.json").read_text())
        for asset in inventory["assets"]:
            for binary in asset["files"]:
                if sha256(self.toolchain / binary["name"]) != binary["sha256"]:
                    raise ValueError("release binary identity differs")
        image = "ghcr.io/nvidia/openshell-community/sandboxes/base:latest"
        result = self.command(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
        if result.returncode:
            raise RuntimeError("base_image_missing")
        self.image_id = result.stdout.decode().strip()
        # Reserve a unique owned network before starting the driver. Driver
        # list/get/reconcile filters use this exact sandbox_namespace label.
        result = self.command(["docker", "network", "create", "--label", "siq.evaluation=tp07-readback", self.name])
        if result.returncode:
            raise RuntimeError("owned_network_create_failed")
        self.network_id = result.stdout.decode().strip()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.endpoint = f"https://127.0.0.1:{port}"
        tls = self.certificates()
        q = json.dumps
        config = f'''[openshell]
version = 1
[openshell.gateway]
bind_address = "127.0.0.1:{port}"
log_level = "warn"
compute_drivers = ["docker"]
disable_tls = false
[openshell.gateway.tls]
cert_path = {q(str(tls / 'server.crt'))}
key_path = {q(str(tls / 'server.key'))}
client_ca_path = {q(str(tls / 'ca.crt'))}
[openshell.gateway.mtls_auth]
enabled = true
[openshell.gateway.auth]
allow_unauthenticated_users = false
[openshell.gateway.gateway_jwt]
signing_key_path = {q(str(tls / 'jwt-signing.pem'))}
public_key_path = {q(str(tls / 'jwt-public.pem'))}
kid_path = {q(str(tls / 'jwt-kid'))}
gateway_id = {q(self.name)}
ttl_secs = 1800
[openshell.drivers.docker]
default_image = {q(image)}
image_pull_policy = "Never"
sandbox_namespace = {q(self.name)}
network_name = {q(self.name)}
supervisor_bin = {q(str(self.toolchain / 'openshell-sandbox'))}
guest_tls_ca = {q(str(tls / 'ca.crt'))}
guest_tls_cert = {q(str(tls / 'client.crt'))}
guest_tls_key = {q(str(tls / 'client.key'))}
sandbox_pids_limit = 256
enable_bind_mounts = false
'''
        (self.root / "gateway.toml").write_text(config)
        self.log = (self.root / "gateway-private.log").open("xb")
        self.gateway = subprocess.Popen([str(self.toolchain / "openshell-gateway"), "--config", str(self.root / "gateway.toml")],
                                        env=self.environment, cwd=self.root, stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        self.events.add("gateway_started", child_pid=self.gateway.pid, endpoint=self.endpoint, namespace=self.name)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if self.gateway.poll() is not None:
                raise RuntimeError("gateway_start_failed")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError("gateway_readiness_timeout")
        registered = self.command([str(self.toolchain / "openshell"), "gateway", "add", self.endpoint, "--name", self.name, "--local"])
        if registered.returncode:
            raise RuntimeError("gateway_registration_failed")
        for args in (("status",), ("gateway", "info"), ("sandbox", "list", "--output", "json")):
            response = self.cli(*args)
            if response.returncode:
                raise RuntimeError("authenticated_gateway_probe_failed")
            if args[0] == "sandbox" and json.loads(response.stdout) != []:
                raise RuntimeError("new_gateway_not_empty")

    def create_sandbox(self):
        policy = self.root / "baseline.yaml"
        policy.write_text('''version: 1
filesystem_policy:
  include_workdir: true
  read_only: [/]
  read_write: [/sandbox, /tmp, /dev/null]
landlock:
  compatibility: hard_requirement
process:
  run_as_user: sandbox
  run_as_group: sandbox
network_policies: {}
''')
        response = self.cli("sandbox", "create", "--name", self.target, "--from", self.image_id,
                            "--cpu", "500m", "--memory", "512Mi", "--no-auto-providers", "--policy", str(policy),
                            "--label", "siq.evaluation=tp07-readback", "--no-tty", "--", "/bin/true", timeout=90)
        return response

    def product_probe(self):
        """Read-only actual SIQ adapter handshake/readback, in a clean process."""
        selected = self.cli("gateway", "select", self.name)
        if selected.returncode:
            raise RuntimeError("owned_gateway_selection_failed")
        candidate = (self.candidate or self.campaign / "private/candidates/5470ab3780f2-fixturefix2") / "apps/control-api"
        code = ("import sys,json,dataclasses; sys.path.insert(0," + repr(str(candidate)) + "); "
                "from app.adapters.openshell.cli_backend import OpenShellCliBackend; "
                "b=OpenShellCliBackend(); c=b.probe(); p=b.read_effective_policy(" + repr(self.target) + "); "
                "print(json.dumps({'capabilities':dataclasses.asdict(c),'readback':dataclasses.asdict(p)}))")
        environment = {**self.environment, "SIQ_AS_OPENSHELL_CLI_BIN": str(self.toolchain / "openshell"),
                       "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT": self.endpoint, "SIQ_AS_OPENSHELL_GATEWAY_INSECURE": "0"}
        return self.command([str(candidate / ".venv/bin/python"), "-c", code], environment=environment)

    def close(self):
        # Stop the reconciler before removing exact namespace-owned containers.
        if self.gateway is not None:
            self.gateway.terminate()
            try:
                self.gateway.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.gateway.kill()
                self.gateway.wait(timeout=5)
            self.cleanup["gateway_stopped"] = self.gateway.poll() is not None
        if self.log is not None:
            self.log.close()
        listed = self.command(["docker", "ps", "-aq", "--filter", "label=openshell.ai/sandbox-namespace=" + self.name])
        removed = []
        if listed.returncode == 0:
            for identifier in listed.stdout.decode().split():
                result = self.command(["docker", "rm", "--force", "--volumes", identifier])
                removed.append({"container_id": identifier, "removed": result.returncode == 0})
        self.cleanup["containers"] = removed
        self.cleanup["container_inventory_checked"] = listed.returncode == 0
        if self.network_id:
            result = self.command(["docker", "network", "rm", self.network_id])
            self.cleanup["network_removed"] = result.returncode == 0
        self.events.add("cleanup", result=self.cleanup)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    fixture = OpenShellFixture(args.campaign, args.out)
    (fixture.root / "harness-source.py").write_bytes(Path(__file__).read_bytes())
    result = {"kind": "environment_preflight", "product_deployment_tested": False, "passed": False}
    write_json(fixture.root / "preregistration.json", {"checks": ["release binaries pinned", "owned namespace empty",
               "authenticated live status", "sandbox create and policy readback"], "runtime_source_sha256": sha256(Path(__file__))})
    try:
        fixture.start()
        result["authenticated_gateway_ready"] = True
        created = fixture.create_sandbox()
        result["create_exit_code"] = created.returncode
        readback = fixture.cli("policy", "get", fixture.target, "--full")
        result["readback_exit_code"] = readback.returncode
        probe = fixture.product_probe()
        result["siq_adapter_probe_exit_code"] = probe.returncode
        if probe.returncode == 0:
            observed = json.loads(probe.stdout)
            write_json(fixture.root / "product-readback.json", observed)
            result["siq_handshake_verified"] = observed["capabilities"]["handshake_verified"]
        result["passed"] = created.returncode == readback.returncode == probe.returncode == 0
    except Exception as exc:  # noqa: BLE001 -- failed preflight retained without credentials
        result["error_type"] = type(exc).__name__
        result["error_code"] = str(exc) if type(exc) is RuntimeError else "setup_failure"
        result["frames"] = [{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(exc.__traceback__)]
    finally:
        fixture.close()
        result["cleanup"] = fixture.cleanup
    write_json(fixture.root / "result.json", result)
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
