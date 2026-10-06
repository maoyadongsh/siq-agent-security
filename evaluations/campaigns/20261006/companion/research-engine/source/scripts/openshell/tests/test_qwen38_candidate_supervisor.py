from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import signal
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from scripts.openshell import (
    broker_admission_registry as admission,
    broker_request_identity as identity,
    qwen38_candidate_gateway_owner as owner_module,
    qwen38_candidate_host_guard as host,
    qwen38_candidate_lease as lease_module,
    qwen38_candidate_renewal as renewal,
    qwen38_candidate_run_guard as guard_module,
    qwen38_candidate_supervisor as supervisor,
)

KEY = bytes(range(32))
NONCE = "a" * 16
NAME = "siq-qwen38-scoped-" + NONCE
REAL_LOAD_AUTHORITY = supervisor._load_authority


def test_business_broker_is_owned_after_first_tick_and_closed_before_containment(bundle, monkeypatch):
    order = []
    stop = threading.Event()
    class Broker:
        failed = threading.Event()
        def __init__(self, **kwargs):
            assert kwargs["registry"].path == bundle.registry.path
            assert kwargs["scope"] == bundle.scope
            assert kwargs["stop"] is stop
            order.append("constructed")
        def start(self):
            order.append("started")
            stop.set()
        def assert_running(self):
            order.append("ready")
        def close(self):
            assert not bundle.effects.exists()
            order.append("closed")
    monkeypatch.setattr(supervisor.qwen38_business_broker, "BusinessBroker", Broker)
    worker = supervisor.Supervisor(bundle.run)
    record = worker._record
    def observe(phase, **kwargs):
        if phase == "running":
            assert order == ["constructed", "started", "ready"]
            assert kwargs["business_broker_ready"] is True and kwargs["ticks"] == 1
        record(phase, **kwargs)
    monkeypatch.setattr(worker, "_record", observe)
    worker.supervise(stop, business_broker=True)
    assert order == ["constructed", "started", "ready", "closed"]
    _contained(bundle)


@pytest.mark.parametrize("failure", ["construct", "start", "poll", "close"])
def test_business_broker_failure_still_contains_sandbox(bundle, monkeypatch, failure, caplog):
    stop = threading.Event()
    class Broker:
        failed = threading.Event()
        def __init__(self, **kwargs):
            if failure == "construct":
                raise RuntimeError("private-broker-credentials")
        def start(self):
            if failure == "start":
                raise RuntimeError("private-broker-credentials")
            stop.set()
        def assert_running(self):
            if failure == "poll":
                raise RuntimeError("private-broker-credentials")
        def close(self):
            if failure == "close":
                raise RuntimeError("private-broker-credentials")
    monkeypatch.setattr(supervisor.qwen38_business_broker, "BusinessBroker", Broker)
    with pytest.raises(supervisor.SupervisorError, match="failed_closed"):
        supervisor.Supervisor(bundle.run).supervise(stop, business_broker=True)
    _contained(bundle)
    assert "private-broker-credentials" not in (bundle.run / "supervisor-state.json").read_text()
    assert 'private-broker-credentials' not in caplog.text
    expected = 'close_business_broker' if failure == 'close' else 'business_broker'
    assert 'supervisor_failure stage=' + expected + ' category=unclassified' in caplog.text


def test_failure_diagnostics_never_export_exception_text_or_unknown_stage(caplog):
    supervisor._report_failure('runtime_identity',
        supervisor.qwen38_request_identity.RequestIdentityError('private identity token'))
    supervisor._report_failure('private database URL', RuntimeError('private database password'))
    assert 'stage=runtime_identity category=runtime_identity' in caplog.text
    assert 'stage=unknown category=unclassified' in caplog.text
    assert 'private' not in caplog.text


def test_logging_handler_failure_does_not_bypass_original_containment(bundle, monkeypatch):
    def broken_log(*args, **kwargs):
        raise OSError('private log location')
    def broken_authority(*args, **kwargs):
        raise RuntimeError('private database password')
    monkeypatch.setattr(supervisor.logger, 'warning', broken_log)
    monkeypatch.setattr(supervisor, '_load_authority', broken_authority)
    with pytest.raises(supervisor.SupervisorError, match='^supervisor_failed_closed$'):
        supervisor.Supervisor(bundle.run).supervise(threading.Event())
    _contained(bundle)


def test_child_broker_mode_is_explicit_and_requires_broker_readiness(bundle, monkeypatch):
    worker = supervisor.SupervisorProcess(bundle.run, business_broker=True)
    commands = []
    class Child:
        def poll(self):
            return None
    def spawn(command, **kwargs):
        commands.append(command)
        worker.supervisor._record("running", ticks=1, business_broker_ready=True)
        return Child()
    monkeypatch.setattr(supervisor.subprocess, "Popen", spawn)
    worker.start(timeout_seconds=1)
    assert worker.assert_running()["business_broker_ready"] is True
    assert "--business-broker" in commands[0]
    assert all("postgresql" not in item for item in commands[0])
    worker.supervisor._record("running", ticks=1)
    with pytest.raises(supervisor.SupervisorError, match="not_running"):
        worker.assert_running()


def test_child_broker_mode_does_not_accept_guard_only_readiness(bundle, monkeypatch):
    worker = supervisor.SupervisorProcess(bundle.run, business_broker=True)
    class Child:
        def poll(self):
            return None
    def spawn(*args, **kwargs):
        worker.supervisor._record("running", ticks=1)
        return Child()
    monkeypatch.setattr(supervisor.subprocess, "Popen", spawn)
    with pytest.raises(supervisor.SupervisorError, match="start_not_ready"):
        worker.start(timeout_seconds=.01)


def test_v2_supervise_refuses_legacy_mode_and_still_contains(bundle, monkeypatch):
    worker = supervisor.Supervisor(bundle.run)
    # Constructor/binding validation has independent tests. Exercise the mode
    # gate with the already-owned fixture and real containment controller.
    worker.manifest["schema_version"] = supervisor.API_SCHEMA
    monkeypatch.setattr(supervisor, "_load_authority", lambda *args: pytest.fail("legacy mode reached authority"))
    with pytest.raises(supervisor.SupervisorError, match="failed_closed"):
        worker.supervise(threading.Event(), business_broker=False)
    _contained(bundle)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    root.mkdir(mode=0o700)
    run = root / NONCE
    run.mkdir(mode=0o700)
    monkeypatch.setattr(host, "RUN_ROOT", root)
    inventory_file = tmp_path / "inventory.json"
    inventory_file.write_text("[]")

    def inventory():
        return json.loads(inventory_file.read_text())

    monkeypatch.setattr(supervisor, "_inventory", inventory)
    owner = owner_module.GatewayRunOwner(root=root, list_sandboxes=inventory)
    owner.reserve(run_id="supervised-run", sandbox_name=NAME, sandbox_nonce=NONCE)
    inventory_file.write_text(json.dumps([NAME]))
    owner.activate(run_id="supervised-run", sandbox_name=NAME, sandbox_nonce=NONCE)
    authorized = supervisor._authority_service().issue_authorized_scope(
        tenant_id="test-tenant", user_id="2", project_id="company:scope-600000", market="cn", company_directory="600000-Synthetic",
        data_classification="confidential_local", object_scopes=("company_wiki",),
        ttl_seconds=1800,
    )
    scope = authorized.scope_ref
    supervisor._publish(run / "supervisor.json", {
        "schema_version": supervisor.SCHEMA, "run_id": "supervised-run",
        "sandbox_name": NAME, "sandbox_nonce": NONCE, "scope": scope.as_dict(),
    }, exclusive=True)
    issued = int(time.time()) - 1
    token = identity.sign_identity(
        KEY, audience=identity.DATA_AUDIENCE, gateway=identity.CANDIDATE_GATEWAY,
        profile="siq_analysis", run_id="supervised-run", sandbox_id=NAME, session_id="supervised-run",
        policy_digest="b" * 64, run_nonce_digest=hashlib.sha256(NONCE.encode()).hexdigest(),
        data_classification="confidential_local", scope_ref=scope, now=issued, ttl_seconds=600,
    )
    signed = identity.verify_identity(token, KEY, expected_gateway=identity.CANDIDATE_GATEWAY)
    registry = admission.BrokerAdmissionRegistry(run / "broker-admission.json")
    lease = lease_module.CandidateDataLease(path=run / "candidate-data-lease.json", sandbox_name=NAME, registry=registry)
    lease.activate_initial(token=token, identity=signed, signing_key=KEY, authorization_expires_at=issued + 900)
    granted = run / "test-granted"
    granted.write_text("yes")
    effects = run / "test-effects"

    def load_authority(directory, current_scope):
        assert directory == run and current_scope == scope
        return SimpleNamespace(dispose=lambda: None), lambda _: renewal.AuthorizationWindow(issued + 900) if granted.exists() else None

    def make_guard(**kwargs):
        def cut_model():
            with pytest.raises(admission.AdmissionError):
                with registry.authorize(token, signed):
                    pass
            with effects.open("a") as stream:
                stream.write("model_cut\n")

        def remove():
            assert effects.read_text().endswith("model_cut\n")
            inventory_file.write_text("[]")
            with effects.open("a") as stream:
                stream.write("sandbox_removed\n")
            return True

        kwargs.pop("sandbox_nonce")
        return guard_module.CandidateRunGuard(
            **kwargs, run_cli=lambda *a, **k: pytest.fail("unexpected renewal upload"),
            list_sandboxes=inventory, cut_model_access=cut_model, remove_sandbox=remove,
        )

    monkeypatch.setattr(supervisor, "_load_authority", load_authority)
    monkeypatch.setattr(identity, "read_key_file", lambda _: KEY)
    monkeypatch.setattr(host, "make_host_guard", make_guard)
    return SimpleNamespace(root=root, run=run, owner=owner, registry=registry, lease=lease,
                           token=token, signed=signed, scope=scope, authorized=authorized,
                           granted=granted, effects=effects)


def _worker(path):
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        supervisor.Supervisor(path).supervise(stop, interval_seconds=1)
    except supervisor.SupervisorError:
        raise SystemExit(1) from None


def _running(bundle):
    process = multiprocessing.get_context("fork").Process(target=_worker, args=(bundle.run,))
    process.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            assert process.is_alive(), "supervisor exited before readiness"
            try:
                state = supervisor._json(bundle.run / "supervisor-state.json")
                if state["phase"] == "running":
                    return process
            except FileNotFoundError:
                pass
            time.sleep(.02)
        raise AssertionError("supervisor readiness timeout")
    except BaseException:
        process.terminate()
        process.join(timeout=5)
        raise


def _contained(bundle):
    assert bundle.lease.status()["phase"] == "revoked"
    with pytest.raises(admission.AdmissionError):
        with bundle.registry.authorize(bundle.token, bundle.signed):
            pass
    assert bundle.effects.read_text().splitlines() == ["model_cut", "sandbox_removed"]
    assert bundle.owner.status()["phase"] == "active"  # Reprovision/release is a separate operation.


def test_independent_supervisor_observes_authority_withdrawal_and_contains(bundle):
    process = _running(bundle)
    try:
        bundle.granted.unlink()
        process.join(timeout=5)
        assert not process.is_alive() and process.exitcode == 1
        _contained(bundle)
        assert supervisor._json(bundle.run / "supervisor-state.json")["phase"] == "contained"
    finally:
        if process.is_alive():
            process.kill()
        process.join(timeout=5)


def test_sigterm_stops_in_order_and_releases_lifetime_lock(bundle):
    process = _running(bundle)
    process.terminate()
    process.join(timeout=5)
    assert process.exitcode == 0
    _contained(bundle)
    assert supervisor._json(bundle.run / "supervisor-state.json")["phase"] == "stopped"


def test_sigkill_recovery_uses_persisted_binding_without_authority_or_key(bundle, monkeypatch):
    process = _running(bundle)
    process.kill()
    process.join(timeout=5)
    assert process.exitcode == -signal.SIGKILL
    with bundle.registry.authorize(bundle.token, bundle.signed):
        pass  # Demonstrates why the service must run ExecStopPost recovery.
    monkeypatch.setattr(supervisor, "_load_authority", lambda *a: pytest.fail("recovery queried authority"))
    monkeypatch.setattr(identity, "read_key_file", lambda *a: pytest.fail("recovery read signing key"))
    supervisor.Supervisor(bundle.run).recover()
    _contained(bundle)


def test_duplicate_worker_recovery_and_gateway_release_are_fenced_while_live(bundle):
    process = _running(bundle)
    try:
        for action in (lambda: supervisor.Supervisor(bundle.run).supervise(threading.Event()),
                       lambda: supervisor.Supervisor(bundle.run).recover()):
            with pytest.raises(supervisor.SupervisorError, match="already_running"):
                action()
        with pytest.raises(owner_module.GatewayOwnerError, match="supervisor_running"):
            bundle.owner.release_after_stop(
                run_id="supervised-run", sandbox_name=NAME, sandbox_nonce=NONCE,
                stop_guard=lambda: pytest.fail("release cut access while supervisor was live"),
            )
        assert not bundle.effects.exists()
    finally:
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
    assert process.exitcode == 0
    bundle.owner.release_after_stop(run_id="supervised-run", sandbox_name=NAME,
                                   sandbox_nonce=NONCE, stop_guard=lambda: None)
    assert bundle.owner.status() is None


def test_old_worker_state_cannot_be_resumed(bundle):
    supervisor._publish(bundle.run / "supervisor-state.json", {"phase": "running"})
    with pytest.raises(supervisor.SupervisorError, match="failed_closed"):
        supervisor.Supervisor(bundle.run).supervise(threading.Event())
    _contained(bundle)


def test_authority_loading_error_still_contains_without_exposing_exception(bundle, monkeypatch):
    def fail(*args):
        raise RuntimeError("secret-database-url")
    monkeypatch.setattr(supervisor, "_load_authority", fail)
    with pytest.raises(supervisor.SupervisorError, match="^supervisor_failed_closed$"):
        supervisor.Supervisor(bundle.run).supervise(threading.Event())
    _contained(bundle)


@pytest.mark.parametrize("change", ["unknown_key", "nonce", "duplicate", "symlink", "mode", "hardlink", "fifo", "lease"])
def test_unknown_or_unsafe_binding_is_not_used_to_cut_other_resources(bundle, tmp_path, change):
    path = bundle.run / "supervisor.json"
    value = json.loads(path.read_text())
    if change == "unknown_key":
        value["extra"] = True
    elif change == "nonce":
        value["sandbox_nonce"] = "b" * 16
    elif change == "duplicate":
        path.write_text('{"scope":{},"scope":{}}')
    elif change == "symlink":
        other = tmp_path / "other.json"
        path.rename(other)
        path.symlink_to(other)
    elif change == "mode":
        path.chmod(0o644)
    elif change == "hardlink":
        os.link(path, tmp_path / "other.json")
    elif change == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif change == "lease":
        lease_path = bundle.run / "candidate-data-lease.json"
        lease = json.loads(lease_path.read_text())
        lease["run_id"] = "other-run"
        lease_path.write_text(json.dumps(lease))
    if change in {"unknown_key", "nonce"}:
        path.write_text(json.dumps(value))
    with pytest.raises((supervisor.SupervisorError, OSError)):
        supervisor.Supervisor(bundle.run)
    assert not bundle.effects.exists()


def test_private_publication_never_overwrites_immutable_input(bundle):
    path = bundle.run / "supervisor.json"
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        supervisor._publish(path, {"different": True}, exclusive=True)
    assert path.read_bytes() == before


def _prepare(bundle, **overrides):
    (bundle.run / "supervisor.json").unlink()
    args = dict(run_id="supervised-run", authorized=bundle.authorized,
                user_id="2", database_url="postgresql://synthetic:private@127.0.0.1/siq_qwen_supervisor_abcdef12")
    args.update(overrides)
    supervisor.prepare(bundle.run, **args)


def test_prepare_and_real_loader_preserve_original_authority_and_restrict_connection(bundle, monkeypatch):
    import sqlmodel

    _prepare(bundle)
    observed = {}
    engine = SimpleNamespace(dispose=lambda: observed.update(disposed=True))

    def create_engine(url, **kwargs):
        observed.update(url=url, **kwargs)
        return engine

    monkeypatch.setattr(sqlmodel, "create_engine", create_engine)
    loaded, callback = REAL_LOAD_AUTHORITY(bundle.run, bundle.scope)
    assert loaded is engine and callable(callback)
    assert observed["url"].drivername == "postgresql+psycopg"
    assert observed["connect_args"] == {"connect_timeout": 5, "options": "-c statement_timeout=5000"}
    assert supervisor._json(bundle.run / "supervisor-authority.json")["snapshot"] == bundle.authorized.snapshot
    for name in ("supervisor.json", "supervisor-authority.json", "supervisor-database.url"):
        assert (bundle.run / name).stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        supervisor.prepare(bundle.run, run_id="supervised-run", authorized=bundle.authorized,
                           user_id="2", database_url="postgresql://127.0.0.1/siq_app")


@pytest.mark.parametrize("url", [
    "sqlite:///private", "postgresql://remote.example/siq_app", "postgresql://localhost/siq_app",
    "postgresql://127.0.0.1/unrelated", "postgresql://127.0.0.1/siq_app?host=remote.example",
    "postgresql://127.0.0.1/siq_app?options=secret", "malformed-private-url",
])
def test_prepare_rejects_unowned_database_without_persisting_credentials(bundle, url):
    with pytest.raises(supervisor.SupervisorError, match="^supervisor_database_target_invalid$"):
        _prepare(bundle, database_url=url)
    assert not (bundle.run / "supervisor-database.url").exists()
    assert not (bundle.run / "supervisor.json").exists()


@pytest.mark.parametrize("change", ["principal", "snapshot", "revoked_lease", "scope"])
def test_prepare_cannot_admit_changed_authority_or_inactive_lease(bundle, change):
    kwargs = {}
    if change == "principal":
        kwargs["user_id"] = "3"
    elif change == "snapshot":
        bundle.authorized.snapshot["expires_at"] += 1
    elif change == "revoked_lease":
        bundle.lease.recover_fail_closed()
    else:
        state = bundle.lease.status()
        state["scope_sha256"] = "0" * 64
        supervisor._publish(bundle.run / "candidate-data-lease.json", state)
    with pytest.raises((supervisor.SupervisorError, supervisor._authority_service().DataScopeAuthorizationError)):
        _prepare(bundle, **kwargs)
    assert not (bundle.run / "supervisor-database.url").exists()


def test_real_loader_disposes_engine_when_snapshot_is_tampered(bundle, monkeypatch):
    import sqlmodel

    _prepare(bundle)
    authority = supervisor._json(bundle.run / "supervisor-authority.json")
    authority["snapshot"]["expires_at"] += 1
    supervisor._publish(bundle.run / "supervisor-authority.json", authority)
    disposed = []
    monkeypatch.setattr(sqlmodel, "create_engine", lambda *a, **k: SimpleNamespace(dispose=lambda: disposed.append(True)))
    with pytest.raises(supervisor._authority_service().DataScopeAuthorizationError):
        REAL_LOAD_AUTHORITY(bundle.run, bundle.scope)
    assert disposed == [True]


def test_process_stop_never_recovers_while_child_is_still_live(bundle, monkeypatch):
    worker = supervisor.SupervisorProcess(bundle.run)
    def timeout(**kwargs):
        raise subprocess.TimeoutExpired("synthetic", 1)
    worker.process = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=timeout)
    monkeypatch.setattr(worker.supervisor, "recover", lambda: pytest.fail("recovered while child was live"))
    with pytest.raises(supervisor.SupervisorError, match="still_running"):
        worker.stop(timeout_seconds=1)


def test_process_readiness_requires_own_live_child_even_if_state_says_running(bundle, monkeypatch):
    worker = supervisor.SupervisorProcess(bundle.run)
    for key in ("STEP_API_KEY", "PGPASSWORD", "PYTHONPATH"):
        monkeypatch.setenv(key, "private-test-sentinel")
    def launch(*args, **kwargs):
        assert "private" not in json.dumps(args) + json.dumps(kwargs.get("env", {}))
        worker.supervisor._record("running", ticks=1)
        return SimpleNamespace(poll=lambda: 1)
    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(supervisor.SupervisorError, match="start_not_ready"):
        worker.start(timeout_seconds=1)


def test_database_disposal_failure_cannot_skip_containment_or_expose_driver_error(bundle, monkeypatch):
    def fail():
        raise RuntimeError("private-driver-error")
    monkeypatch.setattr(supervisor, "_load_authority", lambda *a: (SimpleNamespace(dispose=fail), lambda _: None))
    with pytest.raises(supervisor.SupervisorError, match="^supervisor_failed_closed$"):
        supervisor.Supervisor(bundle.run).supervise(threading.Event())
    _contained(bundle)
    assert "private-driver-error" not in (bundle.run / "supervisor-state.json").read_text()
