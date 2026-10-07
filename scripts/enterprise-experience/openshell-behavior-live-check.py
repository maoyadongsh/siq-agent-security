#!/usr/bin/env python3
"""Owned OpenShell ELF attribution and echo differential; no deployment-grade promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = Path("/home/maoyd/siq-research-engine/var/openshell/toolchains/v0.0.83/bin/openshell")
XDG = Path("/home/maoyd/siq-research-engine/var/openshell/xdg")
GATEWAY = "siq-openshell-scope-validation"
ENDPOINT = "https://127.0.0.1:17771"
ALLOW, DENY = "/opt/siq-behavior/allow", "/opt/siq-behavior/deny"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--probe-sha256", required=True)
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", args.image)
    assert re.fullmatch(r"[a-f0-9]{64}", args.probe_sha256)
    assert re.fullmatch(r"siq-opt05-[a-f0-9]{12}", args.namespace)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    metadata = XDG / "config/openshell/gateways" / GATEWAY / "metadata.json"
    original_metadata = hashlib.sha256(metadata.read_bytes()).hexdigest()
    assert json.loads(metadata.read_text())["gateway_endpoint"] == ENDPOINT
    baseline = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "USER")}
    os.environ.clear()
    os.environ.update(baseline)
    home = out / "home"
    home.mkdir(mode=0o700)
    os.environ["HOME"] = str(home)
    for name in ("CONFIG", "STATE", "DATA", "CACHE"):
        directory = out / name.lower()
        directory.mkdir(mode=0o700)
        os.environ["XDG_" + name + "_HOME"] = str(directory)
    gateways = out / "config/openshell/gateways"
    gateways.mkdir(parents=True)
    (gateways / GATEWAY).symlink_to(metadata.parent, target_is_directory=True)
    (out / "state/openshell").mkdir(parents=True)
    (out / "state/openshell/tls").symlink_to(XDG / "state/openshell/tls", target_is_directory=True)
    os.environ.update(SIQ_AS_OPENSHELL_CLI_BIN=str(CLI), SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT=ENDPOINT,
                      SIQ_AS_OPENSHELL_GATEWAY_INSECURE="0")
    sys.path.insert(0, str(ROOT / "apps/control-api"))
    import yaml

    from app.adapters.openshell.behavior_channel import (
        AgentObservationV2,
        BehaviorProbeChannel,
    )
    from app.adapters.openshell.behavior_protection import (
        ProtectedProbeTarget,
        RootfulDockerProbeGuard,
    )
    from app.adapters.openshell.behavior_protocol import (
        BehaviorChallengeV2,
        challenge_digest,
        validate_behavior_result,
    )
    from app.adapters.openshell.bounded_command import run_bounded
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.policy_safety import network_rules_to_gateway

    target = "siq-behavior-" + uuid.uuid4().hex[:12]
    checks, received = {}, []
    result = {"passed": False, "schema_version": "openshell-behavior-live-check/v1", "checks": checks,
              "target": target, "namespace": args.namespace, "image_digest": args.image,
              "probe_sha256": args.probe_sha256, "cli_sha256": hashlib.sha256(CLI.read_bytes()).hexdigest(),
              "synthetic_operation_binding": True, "deployment_grade_promoted": False, "model_calls": 0}
    server = None
    thread = None
    stop = threading.Event()
    attempted = False

    def cli(*command, required=True):
        execution = subprocess.run([str(CLI), "--gateway", GATEWAY, *command], stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=60, check=False)
        if required and execution.returncode:
            (out / "cli-error.log").write_text(execution.stdout[:4096] + execution.stderr[:4096])
            raise RuntimeError("owned OpenShell command failed; see private log")
        return execution

    def docker(*command):
        execution = subprocess.run(["/usr/bin/docker", "--host", "unix:///run/docker.sock", *command],
                                   capture_output=True, text=True, timeout=10, check=True)
        return execution.stdout.strip()

    def catalog():
        rows = json.loads(cli("sandbox", "list", "--limit", "1000", "--output", "json").stdout)
        assert isinstance(rows, list)
        return rows

    try:
        cli("gateway", "select", GATEWAY)
        assert catalog() == [], "dedicated owned gateway must be empty"
        policy = {"version": 1, "filesystem_policy": {"include_workdir": True, "read_only": ["/"],
                  "read_write": ["/sandbox", "/tmp", "/dev/null"]}, "landlock": {"compatibility": "hard_requirement"},
                  "process": {"run_as_user": "sandbox", "run_as_group": "sandbox"}, "network_policies": {}}
        policy_file = out / "policy.yaml"
        policy_file.write_text(yaml.safe_dump(policy, sort_keys=False))
        attempted = True
        cli("sandbox", "create", "--name", target, "--from", args.image, "--cpu", "500m", "--memory", "512Mi",
            "--no-auto-providers", "--policy", str(policy_file), "--label", "siq.acceptance=behavior-opt09",
            "--", "/bin/true")
        rows = [r for r in catalog() if r["name"] == target]
        assert len(rows) == 1
        cid = docker("ps", "--no-trunc", "--filter", "label=openshell.ai/sandbox-name=" + target,
                     "--filter", "label=openshell.ai/sandbox-namespace=" + args.namespace, "--format", "{{.ID}}")
        assert re.fullmatch(r"[a-f0-9]{64}", cid)
        sandbox_id = docker("inspect", "--format", '{{index .Config.Labels "openshell.ai/sandbox-id"}}', cid)
        assert rows[0]["id"] == sandbox_id
        # Independent image account lookup; never adopt the probe's claimed UID.
        identity_cidfile = out / "image-identity-container"
        try:
            uid_text = docker("run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--user=sandbox", "--cidfile", str(identity_cidfile),
                "--entrypoint=/usr/bin/id", args.image, "-u")
            assert re.fullmatch(r"[1-9][0-9]{0,9}", uid_text)
            probe_uid = int(uid_text)
        finally:
            if identity_cidfile.exists():
                identity_cid = identity_cidfile.read_text().strip()
                assert re.fullmatch(r"[a-f0-9]{64}", identity_cid)
                subprocess.run(["/usr/bin/docker", "rm", "-f", identity_cid],
                               capture_output=True, timeout=10, check=False)
        result["independently_resolved_probe_uid"] = probe_uid
        protection_target = ProtectedProbeTarget(container_id=cid, image_digest=args.image, namespace=args.namespace,
            sandbox_name=target, sandbox_id=sandbox_id, uid=probe_uid, allow_path=ALLOW, deny_path=DENY,
            probe_sha256=args.probe_sha256, supervisor_profile="openshell-rootful-v0")
        guard = RootfulDockerProbeGuard(protection_target)
        result["observed_container_runtime"] = json.loads(docker("inspect", "--format",
            '{"cap_add":{{json .HostConfig.CapAdd}},"privileged":{{json .HostConfig.Privileged}},'
            '"user":{{json .Config.User}},"userns":{{json .HostConfig.UsernsMode}}}', cid))
        protected = guard.verify()
        (out / "protection.json").write_text(json.dumps(protected, indent=2) + "\n")
        checks["actual_openshell_target_and_program_protection"] = True
        ipam = json.loads(docker("network", "inspect", args.namespace, "--format", "{{json .IPAM.Config}}"))
        host = next(item["Gateway"] for item in ipam if ":" not in item["Gateway"])
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((host, 0))
        server.listen(4)
        server.settimeout(0.2)
        port = server.getsockname()[1]

        def serve():
            while not stop.is_set():
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                with connection:
                    connection.settimeout(2)
                    try:
                        marker = bytearray()
                        while len(marker) < 128 and not marker.endswith(b"\n"):
                            data = connection.recv(128 - len(marker))
                            if not data:
                                break
                            marker.extend(data)
                        if re.fullmatch(rb"SIQ-BEHAVIOR/1 opv-[a-f0-9]{32} [a-f0-9]{64}\n", marker):
                            received.append(bytes(marker).decode())
                            connection.sendall(marker)
                    except OSError:
                        pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        policy["network_policies"] = network_rules_to_gateway(
            [{"effect": "allow", "endpoint": f"{host}:{port}", "binary_paths": [ALLOW]}])
        policy_file.write_text(yaml.safe_dump(policy, sort_keys=False))
        cli("policy", "set", target, "--policy", str(policy_file), "--wait", "--timeout", "30")
        backend = OpenShellCliBackend()
        capabilities = backend.probe()
        snapshot = backend.read_effective_policy(target)
        binding = {"tenant_id": "component-tenant", "environment_id": "component-environment",
            "binding_id": "component-binding", "deployment_id": "component-deployment",
            "operation_id": "component-apply",
            "target": target, "gateway_fingerprint": capabilities.endpoint_fingerprint,
            "policy_revision": snapshot.revision, "policy_digest": snapshot.policy_digest,
            "image_digest": args.image, "probe_sha256": args.probe_sha256,
            "protected_execution_sha256": protected["protected_execution_sha256"]}
        # Explicit operator-approved profile for this owned v0.0.83 gateway.
        # Never derive an authorized endpoint from workload HTTP_PROXY.
        transport = {"mode": "http_connect", "proxy_ipv4": "10.200.0.1", "proxy_port": 3128}
        result["approved_transport"] = transport
        now = datetime.now(UTC)
        challenge = BehaviorChallengeV2.model_validate({"schema_version": "openshell-behavior-challenge/v2",
            "verification_id": "opv-" + uuid.uuid4().hex, "nonce": secrets.token_hex(32), "binding": binding,
            "receiver_ipv4": host, "receiver_port": port, "allow_path": ALLOW, "deny_path": DENY,
            "transport": transport,
            "attempts": 3, "timeout_ms": 2000, "issued_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")})

        def readback():
            actual = backend.read_effective_policy(target)
            observed = guard.verify()
            return {"binding": {**binding, "policy_revision": actual.revision, "policy_digest": actual.policy_digest,
                                "protected_execution_sha256": observed["protected_execution_sha256"]},
                    "transport": dict(transport), "enforcement_mode": actual.enforcement_mode, "allow_rules": [
                        {"endpoint": rule["endpoint"], "program_path": path}
                        for rule in actual.network for path in rule["binary_paths"]]}

        before = readback()
        started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        observations = []
        def observed_runner(argv, **kwargs):
            execution = run_bounded(argv, **kwargs)
            if execution[0] == 0:
                try:
                    report = AgentObservationV2.model_validate_json(execution[1]).model_dump()
                except ValueError:
                    report = {"unparseable": True, "stdout_sha256": hashlib.sha256(execution[1].encode()).hexdigest()}
                result.setdefault("agent_reports", []).append(report)
            return execution

        channel = BehaviorProbeChannel(backend._build_command, runner=observed_runner)
        for round_index in range(3):
            assert readback() == before
            for kind in ("control_before", "allow", "deny", "control_after"):
                if kind in ("allow", "deny"):
                    item = channel.run_arm(challenge, round_index=round_index, kind=kind, expected_uid=probe_uid)
                else:
                    item = channel.control(challenge, round_index=round_index, kind=kind)
                observations.append(item)
                (out / "observations.json").write_text(json.dumps(observations, indent=2) + "\n")
        observed = {"schema_version": "openshell-behavior-result/v3", "verification_id": challenge.verification_id,
            "nonce": challenge.nonce, "challenge_sha256": challenge_digest(challenge), "started_at": started,
            "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "before": before, "after": readback(), "observations": observations}
        accepted, reason = validate_behavior_result(observed, challenge.model_dump(), readback(),
                                                    now=datetime.now(UTC), run_state="running")
        (out / "challenge.json").write_text(json.dumps(challenge.model_dump(), indent=2) + "\n")
        (out / "observation-result.json").write_text(json.dumps(observed, indent=2) + "\n")
        result["candidate_validation"] = {"accepted": accepted, "reason": reason}
        assert accepted, reason
        checks["three_round_actual_allow_deny_controls_accepted"] = True
        assert len(received) == 9
        checks["receiver_observed_only_nine_allowed_control_arrivals"] = True
        policy["network_policies"] = network_rules_to_gateway(
            [{"effect": "allow", "endpoint": f"{host}:{port}", "binary_paths": [ALLOW, DENY]}])
        policy_file.write_text(yaml.safe_dump(policy, sort_keys=False))
        cli("policy", "set", target, "--policy", str(policy_file), "--wait", "--timeout", "30")
        assert not validate_behavior_result(observed, challenge.model_dump(), readback(),
                                            now=datetime.now(UTC), run_state="running")[0]
        checks["real_policy_change_invalidates_old_observations"] = True
        # Observe the same formerly denied program after explicit authorization.
        updated = challenge.model_dump()
        current_time = datetime.now(UTC)
        updated.update(verification_id="opv-" + uuid.uuid4().hex, nonce=secrets.token_hex(32),
                       binding=readback()["binding"],
                       issued_at=current_time.isoformat().replace("+00:00", "Z"),
                       expires_at=(current_time + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
        new_challenge = BehaviorChallengeV2.model_validate(updated)
        (out / "explicit-allow-challenge.json").write_text(json.dumps(updated, indent=2) + "\n")
        authorized = channel.run_arm(new_challenge, round_index=0, kind="deny", expected_uid=probe_uid)
        assert authorized["outcome"] == "connected"
        result["formerly_denied_after_explicit_allow"] = authorized
        checks["same_elf_path_connects_after_explicit_policy_allow"] = True
        result["passed"] = True
    finally:
        if server is not None:
            stop.set()
            server.close()
        if thread is not None:
            thread.join(timeout=3)
            checks["receiver_stopped"] = not thread.is_alive()
        if attempted:
            cli("sandbox", "delete", target, required=False)
            for _ in range(20):
                remaining = catalog()
                if not any(r["name"] == target for r in remaining):
                    break
                time.sleep(0.25)
            checks["owned_sandbox_deleted"] = not any(r["name"] == target for r in remaining)
            checks["dedicated_gateway_empty_after_cleanup"] = remaining == []
        checks["original_metadata_unchanged"] = hashlib.sha256(metadata.read_bytes()).hexdigest() == original_metadata
        result["passed"] = result["passed"] and all(checks.values())
        result["receiver_markers"] = received
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": len(checks)}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
