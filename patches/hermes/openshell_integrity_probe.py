"""Owned OpenShell hook integrity differential; actual Go and Hermes tools."""

import datetime
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import openshell_online_probe as online
from openshell_image_probe import ADAPTER, PYTHON, digest, runtime_parameters

TARGET = "/opt/hermes-agent/siq_native_runtime/native_dispatch.py"


def validate_receipts(authority):
    """Check exact successful calls; the Go owner separately verifies signatures."""
    expected = [("skill_view", "integrity-load"), ("write_file", "integrity-before"),
                ("write_file", "integrity-after-attempts")]
    if (type(authority) is not dict or authority.get("signed_chain_verified") is not True
            or type(authority.get("receipt_count")) is not int or authority["receipt_count"] != 3
            or type(authority.get("receipts")) is not list or len(authority["receipts"]) != 3):
        raise RuntimeError("integrity_receipt_sequence_invalid")
    for receipt, (tool, call) in zip(authority["receipts"], expected, strict=True):
        if (type(receipt) is not dict or receipt.get("schema_version") != "runtime-receipt/v3"
                or receipt.get("tool") != tool or receipt.get("tool_call_id") != call
                or receipt.get("action") != "allow"):
            raise RuntimeError("integrity_receipt_sequence_invalid")


def prepare(output, command):
    return online.prepare(output, command, bootstrap_path=Path(__file__).with_name("openshell_integrity_bootstrap.py"))


def wait_row(path, key, value, *, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = []
        for line in path.read_text(errors="replace").splitlines():
            if line.startswith('{"' + key + '":'):
                row = json.loads(line)
                if row.get(key) == value:
                    rows.append(row)
        if len(rows) == 1:
            return rows[0]
        if rows:
            raise RuntimeError("integrity_ambiguous_result")
        time.sleep(.05)
    raise RuntimeError("integrity_runtime_timeout")


def verify(prepared, *, peer, cid, namespace, sandbox, init_pid, init_groups, row, command, exec_log):
    backend, runtime = runtime_parameters(prepared, peer=peer, cid=cid, namespace=namespace,
        sandbox=sandbox, init_pid=init_pid, init_groups=init_groups)
    owned = online._owned
    ready = owned.ready
    package = owned.module.__package__
    sys.modules[package + ".host_online"] = owned.module
    spec = importlib.util.spec_from_file_location(package + ".host_session", ADAPTER / "host_session.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    now = datetime.datetime.now(datetime.UTC)
    host = module.HostSession(owned.verifier, ready["endpoint"])
    checks = {}
    root = Path(f"/proc/{peer}/root/sandbox/native-business")
    original = prepared["files"][TARGET]
    changed = False
    # Only exact Docker object returned by the owning runner and verified by
    # HostSession is mutated. Daily containers and source files are untouched.
    def mutation(restore):
        program = ("import pathlib,os,hashlib; p=pathlib.Path(" + repr(TARGET) + "); "
                   "raw=p.read_bytes(); suffix=b'\\n# owned integrity fault\\n'; "
                   + ("assert raw.endswith(suffix); raw=raw[:-len(suffix)]; " if restore else
                      "assert hashlib.sha256(raw).hexdigest()==" + repr(original) + "; raw+=suffix; ")
                   + "os.chmod(p,0o644); p.write_bytes(raw); os.chmod(p,0o444); "
                     "print(hashlib.sha256(p.read_bytes()).hexdigest())")
        value = command(["/usr/bin/docker", "exec", "--user", "0:0", cid,
                         PYTHON, "-I", "-B", "-c", program]).stdout.decode().strip()
        if len(value) != 64 or (value == original) != restore:
            raise RuntimeError("integrity_injection_readback_failed")
        return value
    try:
        host.start(backend=backend, runtime=runtime, subject=ready["subject"], installs=ready["installs"],
                   channel_directory=row["channel_directory"], credential=Path(ready["credential_path"]).read_text(),
                   supervisor_pid=os.getpid(), expires_at=now + datetime.timedelta(seconds=120),
                   authorization_expires_at=now + datetime.timedelta(seconds=85))
        wait_row(exec_log, "integrity_stage", "before-drift")
        checks["independent_allowed_effects"] = (
            (root / "before.txt").read_text() == "integrity-before" and
            (root / "after-attempts.txt").read_text() == "integrity-after-attempts")
        host._guard.verify()
        checks["guard_verified_after_runtime_mutation_attempts"] = True
        changed_digest = mutation(False)
        changed = True
        (root / "before-drift.continue").touch(exist_ok=False)
        wait_row(exec_log, "integrity_stage", "after-drift")
        checks["independent_drift_effect_absent"] = not (root / "drift-denied.txt").exists()
        checks["runtime_guard_permanently_closed"] = host._guard._closed
        mutation(True)
        changed = False
        (root / "after-drift.continue").touch(exist_ok=False)
        observed = wait_row(exec_log, "integrity_result", True)
        required = {"actual_writer_skill_loaded", "allowed_write_before_attempts",
                    "runtime_cannot_mutate_hook_or_manifest", "allowed_write_after_refused_mutations",
                    "code_drift_refuses_actual_write", "restored_bytes_do_not_revive_runtime", "no_denied_file_effect"}
        if (not required.issubset(observed["checks"]) or
                set(observed["checks"]) - required - {"terminal_context_cleanup_refused"} or
                not all(v is True for v in observed["checks"].values())):
            raise RuntimeError("integrity_execution_failed")
        attempts = observed["attempts"]
        expected_attempts = {(p, a) for p in ("siq_native_runtime/native_dispatch.py", "manifest.json")
                            for a in ("write", "delete", "replace")}
        if (len(attempts) != 6 or {(a["target"], a["operation"]) for a in attempts} != expected_attempts
                or not all(a["refused"] is True and a["unchanged"] is True for a in attempts)):
            raise RuntimeError("integrity_mutation_matrix_failed")
        checks["independent_restored_effect_absent"] = not (root / "restored-denied.txt").exists()
        checks["actual_hook_bytes_restored"] = digest(Path(f"/proc/{peer}/root{TARGET}").read_bytes()) == original
        try:
            host._guard.verify()
        except sys.modules[package + ".host_runtime"].RuntimeGuardError:
            checks["closed_guard_does_not_recover"] = host._guard._closed
        else:
            checks["closed_guard_does_not_recover"] = False
    finally:
        try:
            if changed:
                mutation(True)
        finally:
            try:
                host.close()
            except sys.modules[package + ".host_runtime"].RuntimeGuardError:
                # Directory context exit rechecks the now-invalid target. The
                # production control owner likewise retries terminal cleanup;
                # do not mistake this negative verification for probe success.
                checks["cleanup_recheck_reported_invalid_runtime"] = host._guard._closed
                host.close()
    checks["host_session_resources_closed"] = (
        host._guard._closed and host._fence._pin is None and host._directory is None
        and not host._loop._thread.is_alive())
    (owned.root / "finish").touch(exist_ok=True)
    owned.process.wait(timeout=10)
    if owned.process.returncode:
        raise RuntimeError("integrity_authority_verification_failed")
    authority = json.loads((owned.root / "authority-result.json").read_text())
    validate_receipts(authority)
    checks["actual_signed_receipt_chain_verified"] = True
    checks.update(observed["checks"])
    if not all(v is True for v in checks.values()):
        raise RuntimeError("integrity_checks_failed")
    result = {"schema_version": "siq.hook-integrity-openshell-probe/v1", "checks": checks, "attempts": attempts,
              "image_id": prepared["image"], "artifact_sha256": prepared["artifact"], "files": prepared["files"],
              "injected_target": TARGET, "before_sha256": original, "injected_sha256": changed_digest,
              "receipt_count": authority["receipt_count"], "model_calls": 0, "synthetic_skill_content": True,
              "actual_hermes_tools": True, "business_entry_acceptance": False}
    (owned.output / "integrity-result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
