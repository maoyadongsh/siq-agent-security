#!/usr/bin/env python3
"""Run the live recovery harness using a private copy of an inactive validation gateway configuration."""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--gateway-template", type=Path, required=True)
    parser.add_argument("--gateway-binary", type=Path, required=True)
    parser.add_argument("--web", type=Path)
    parser.add_argument("--behavior-image")
    parser.add_argument("--probe-sha256")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    original = args.gateway_template.resolve(strict=True)
    binary = args.gateway_binary.resolve(strict=True)
    root = args.output.resolve()
    web = args.web.resolve(strict=True) if args.web else None
    if args.behavior_image:
        import re
        assert web is None and re.fullmatch(r"sha256:[a-f0-9]{64}", args.behavior_image)
        assert args.probe_sha256 and re.fullmatch(r"[a-f0-9]{64}", args.probe_sha256)
    else:
        assert web is not None and (web / "index.html").is_file()
    root.mkdir(mode=0o700)
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    config = tomllib.loads(original.read_text())
    gateway = config["openshell"]["gateway"]
    driver = config["openshell"]["drivers"]["docker"]
    namespace = "siq-opt05-" + uuid.uuid4().hex[:12]
    assert gateway["bind_address"] == "127.0.0.1:17771"
    assert gateway["health_bind_address"] == "127.0.0.1:17772"
    assert gateway["tls"]["require_client_auth"] and gateway["mtls_auth"]["enabled"]
    assert gateway["auth"]["allow_unauthenticated_users"] is False
    gateway["sandbox_namespace"] = namespace
    driver["sandbox_namespace"] = namespace
    driver["network_name"] = namespace
    driver["enable_bind_mounts"] = False
    driver.pop("bind_mount_contract", None)
    driver.pop("bind_mount_project_root", None)
    certs = root / "private-certs"
    created = subprocess.run(
        [
            str(binary),
            "generate-certs",
            "--output-dir",
            str(certs),
            "--server-san",
            "127.0.0.1",
            "--server-san",
            "host.openshell.internal",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert created.returncode == 0, "private certificate generation failed"
    for key, name in [
        ("kid_path", "kid"),
        ("public_key_path", "public.pem"),
        ("signing_key_path", "signing.pem"),
    ]:
        gateway["gateway_jwt"][key] = str(certs / "jwt" / name)
    cert_hashes = {
        str(gateway["tls"][key]): hashlib.sha256(
            Path(gateway["tls"][key]).read_bytes()
        ).hexdigest()
        for key in ("cert_path", "key_path", "client_ca_path")
    }

    def toml_table(table, prefix=()):
        result = []
        if prefix:
            result.append("[" + ".".join(json.dumps(key) for key in prefix) + "]")
        for key, value in table.items():
            if not isinstance(value, dict):
                assert isinstance(value, (str, bool, int, list))
                result.append(json.dumps(key) + " = " + json.dumps(value))
        for key, value in table.items():
            if isinstance(value, dict):
                result.extend(toml_table(value, (*prefix, key)))
        return result

    rendered = "\n".join(toml_table(config)) + "\n"
    assert tomllib.loads(rendered) == config
    candidate = root / "gateway.toml"
    candidate.write_text(rendered)
    candidate.chmod(0o600)
    for port in (17771, 17772):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    environment = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG")}
    (root / "home").mkdir(mode=0o700)
    environment.update(
        HOME=str(root / "home"),
        OPENSHELL_GATEWAY_CONFIG=str(candidate),
        OPENSHELL_DB_URL="sqlite:" + str(root / "openshell.db"),
        OPENSHELL_TELEMETRY_ENABLED="false",
    )
    launch = [
        sys.executable,
        "-c",
        (
            "import os,resource,sys; resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3)); "
            "os.execv(sys.argv[1],[sys.argv[1]])"
        ),
        str(binary),
    ]
    result = {
        "isolated_namespace": namespace,
        "host_bind_mounts": False,
        "live_check_started": False,
    }
    with (root / "gateway.log").open("wb") as log:
        process = subprocess.Popen(
            launch,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            ready = False
            for _ in range(100):
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:17772/healthz", timeout=0.5
                    ) as response:
                        ready = response.status == 200
                    if ready:
                        break
                except OSError:
                    result["health_probe_failures"] = (
                        result.get("health_probe_failures", 0) + 1
                    )
                time.sleep(0.2)
            result["ready"] = ready
            if ready:
                result["live_check_started"] = True
                if args.behavior_image:
                    command = [sys.executable, str(repo / "scripts/enterprise-experience/openshell-behavior-live-check.py"),
                               str(root / "live"), "--image", args.behavior_image, "--probe-sha256", args.probe_sha256,
                               "--namespace", namespace]
                else:
                    command = [sys.executable, str(repo / "scripts/enterprise-experience/openshell-deployment-live-check.py"),
                               str(root / "live"), "--web", str(web)]
                with (root / "acceptance.log").open("wb") as output:
                    accepted = subprocess.run(
                        command,
                        cwd=repo,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        timeout=480,
                        check=False,
                    )
                result["acceptance_exit_code"] = accepted.returncode
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
            result["owned_gateway_stopped"] = process.poll() is not None
            result["original_configuration_unchanged"] = (
                hashlib.sha256(original.read_bytes()).hexdigest() == before
            )
            result["original_tls_files_unchanged"] = all(
                hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
                for p, digest in cert_hashes.items()
            )
            remaining = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    "network=" + namespace,
                    "--format",
                    "{{.ID}}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            result["owned_network_empty"] = not remaining.stdout.strip()
            if result["owned_network_empty"]:
                deleted = subprocess.run(
                    ["docker", "network", "rm", namespace],
                    capture_output=True,
                    check=False,
                )
                result["network_cleanup_returncode"] = deleted.returncode
            result["passed"] = (
                result.get("acceptance_exit_code") == 0
                and result["owned_gateway_stopped"]
                and result["owned_network_empty"]
                and result["original_configuration_unchanged"]
                and result["original_tls_files_unchanged"]
                and result.get("network_cleanup_returncode") == 0
            )
            result["gateway_binary_sha256"] = hashlib.sha256(
                binary.read_bytes()
            ).hexdigest()
            result["template_sha256"] = before
            (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))

    if not result.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
