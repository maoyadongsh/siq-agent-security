#!/usr/bin/env python3
"""Host process for periodic candidate authorization and fail-closed recovery."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.openshell import (  # noqa: E402
    broker_admission_registry,
    broker_lifecycle,
    broker_request_identity,
    enterprise_data_scope,
    probe_qwen38_provider as provider,
    qwen38_business_broker,
    qwen38_candidate_gateway_owner,
    qwen38_candidate_host_guard as host,
    qwen38_candidate_lease,
    qwen38_request_forward,
    qwen38_request_identity,
    qwen38_request_relay,
)

SCHEMA = "siq.openshell.qwen38-supervisor.v1"
API_SCHEMA = "siq.openshell.qwen38-supervisor.v2"
IDENTITY_SCHEMA = "siq.openshell.qwen38-supervisor.v3"
RELAY_SCHEMA = "siq.openshell.qwen38-supervisor.v4"
FORWARD_SCHEMA = "siq.openshell.qwen38-supervisor.v5"
RELAY_SCHEMAS = {RELAY_SCHEMA, FORWARD_SCHEMA}
IDENTITY_SCHEMAS = {IDENTITY_SCHEMA, *RELAY_SCHEMAS}
API_SCHEMAS = {API_SCHEMA, *IDENTITY_SCHEMAS}
MANIFEST_KEYS = {"schema_version", "run_id", "sandbox_name", "sandbox_nonce", "scope"}
MAX_BYTES = 16384


class SupervisorError(RuntimeError):
    """Constant category only; never include private inputs or driver errors."""


logger = logging.getLogger(__name__)
_FAILURE_STAGES = frozenset({
    'startup_validation', 'load_authority', 'signing_material', 'guard_configuration',
    'owner_binding', 'guard_tick', 'runtime_identity', 'relay', 'forward',
    'business_broker', 'state_publication', 'wait', 'close_forward', 'close_relay',
    'close_business_broker', 'business_broker_failed', 'containment', 'dispose_engine',
})
_FAILURE_TYPES = {
    'SupervisorError': 'supervisor_contract',
    'CandidateRunGuardError': 'run_guard',
    'CandidateLeaseError': 'data_lease',
    'DataScopeAuthorizationError': 'business_authority',
    'ExecutionLeaseError': 'execution_lease',
    'RequestIdentityError': 'runtime_identity',
    'SelfIdentityError': 'authority_service',
    'RequestRelayError': 'relay',
    'RequestForwardError': 'forward',
    'BusinessBrokerError': 'business_broker',
}


def _report_failure(stage, exc=None):
    """Diagnostic-only categories; neither secrets nor log failures affect fencing."""
    try:
        logger.warning('supervisor_failure stage=%s category=%s',
            stage if stage in _FAILURE_STAGES else 'unknown',
            _FAILURE_TYPES.get(type(exc).__name__, 'unclassified'))
    except Exception:
        # Continue the original containment path even if a logging handler fails.
        pass


def _directory(path: Path) -> None:
    info = path.lstat()
    if (path.resolve(strict=True) != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise SupervisorError("supervisor_private_directory_invalid")


def _file_info(info, limit=MAX_BYTES):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
            or info.st_size > limit):
        raise SupervisorError("supervisor_private_file_invalid")


def _read(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        _file_info(info)
        data = os.read(descriptor, MAX_BYTES + 1)
        if len(data) != info.st_size:
            raise SupervisorError("supervisor_private_file_changed")
        return data
    finally:
        os.close(descriptor)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SupervisorError("supervisor_duplicate_json_key")
        value[key] = item
    return value


def _json(path):
    return json.loads(_read(path), object_pairs_hook=_unique)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish(path: Path, value: dict, *, exclusive=False) -> None:
    """Publish private JSON; immutable inputs never replace an existing object."""
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _publish_bytes(path, payload, exclusive=exclusive)


def _publish_bytes(path: Path, payload: bytes, *, exclusive=False) -> None:
    if not payload or len(payload) > MAX_BYTES:
        raise SupervisorError("supervisor_private_file_invalid")
    _directory(path.parent)
    if not exclusive and path.exists():
        _file_info(path.lstat())
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path, follow_symlinks=False)
        else:
            if path.is_symlink():
                raise SupervisorError("supervisor_private_file_invalid")
            os.replace(temporary, path)
        temporary.unlink(missing_ok=True)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _inventory():
    return [item.get("name") for item in provider._sandboxes()]


def _authority_service():
    api_root = str(provider.ROOT / "apps/api")
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    from services import openshell_data_scope
    return openshell_data_scope


def _api_lease_service():
    _authority_service()
    from services import qwen38_runtime_lease
    return qwen38_runtime_lease


def _database_url(value):
    from sqlalchemy.engine import make_url

    try:
        url = make_url(value)
        if (url.drivername not in {"postgresql", "postgresql+psycopg"}
                or url.host not in {"127.0.0.1", "::1"}
                or not re.fullmatch(r"(?:siq_app|siq_qwen_(?:guard|supervisor)_[0-9a-f]{8,16})", url.database or "")
                or url.query):
            raise ValueError
        return url.set(drivername="postgresql+psycopg")
    except Exception:
        raise SupervisorError("supervisor_database_target_invalid") from None


def prepare(directory: Path, *, run_id: str, authorized, user_id: str, database_url: str,
            api_execution_lease=None, agentshield_identity=None, agentshield_relay=None, hermes_forward=None) -> None:
    """Persist the owning business service's existing authority; never issue one."""
    service = _authority_service()
    if not isinstance(authorized, service.AuthorizedDataScope):
        raise SupervisorError("supervisor_authority_invalid")
    scope = authorized.scope_ref
    service.revalidate_authorized_scope(
        authorized, user_id=user_id, tenant_id=scope.tenant_id,
        project_id=scope.project_id, market=scope.market, company_directory=scope.company_directory,
    )
    url = _database_url(database_url)
    if (not directory.is_absolute() or directory.parent != host.RUN_ROOT
            or re.fullmatch(r"[0-9a-f]{16}", directory.name) is None
            or not isinstance(run_id, str) or broker_request_identity.SAFE_ID_RE.fullmatch(run_id) is None
            or scope.data_classification != "confidential_local" or not isinstance(user_id, str)):
        raise SupervisorError("supervisor_binding_invalid")
    _directory(host.RUN_ROOT)
    _directory(directory)
    value = {"schema_version": SCHEMA, "run_id": run_id,
             "sandbox_name": "siq-qwen38-scoped-" + directory.name,
             "sandbox_nonce": directory.name, "scope": scope.as_dict()}
    if api_execution_lease is not None:
        lease_service = _api_lease_service()
        binding = lease_service.parse(api_execution_lease)
        lease_service.require_scope(binding, scope=scope, user_id=user_id, runtime_run_id=run_id)
        if run_id != "qwen-request-" + directory.name:
            raise SupervisorError("supervisor_api_lease_run_mismatch")
        value.update(schema_version=API_SCHEMA, api_execution_lease=binding.as_dict())
    if agentshield_identity is not None:
        if api_execution_lease is None:
            raise SupervisorError("supervisor_identity_requires_api_binding")
        reference = qwen38_request_identity.validate_reference(agentshield_identity)
        prepared = qwen38_request_identity.PreparedIdentity(directory, reference["record_sha256"])
        qwen38_request_identity.check(prepared, run_id=run_id, scope=scope, execution_binding=api_execution_lease)
        value.update(schema_version=IDENTITY_SCHEMA, agentshield_identity=reference)
    if agentshield_relay is not None:
        if agentshield_identity is None:
            raise SupervisorError("supervisor_relay_requires_identity")
        value.update(schema_version=RELAY_SCHEMA,
                     agentshield_relay=qwen38_request_relay.validate_reference(agentshield_relay))
        qwen38_request_relay.RequestRelay(directory, value, scope)
    if hermes_forward is not None:
        if agentshield_relay is None:
            raise SupervisorError("supervisor_forward_requires_relay")
        value.update(schema_version=FORWARD_SCHEMA, hermes_forward=qwen38_request_forward.validate_reference(hermes_forward))
    owner = qwen38_candidate_gateway_owner.GatewayRunOwner(root=host.RUN_ROOT, list_sandboxes=_inventory).status()
    if (owner is None or owner["phase"] != "active"
            or any(owner[key] != value[key] for key in ("run_id", "sandbox_name", "sandbox_nonce"))):
        raise SupervisorError("supervisor_gateway_owner_mismatch")
    lease = qwen38_candidate_lease.CandidateDataLease(
        path=directory / "candidate-data-lease.json", sandbox_name=value["sandbox_name"],
        registry=broker_admission_registry.BrokerAdmissionRegistry(directory / "broker-admission.json"),
    ).status()
    if (lease is None or lease["phase"] != "active" or lease["expires_at"] <= int(time.time())
            or lease["run_id"] != run_id or lease["scope_sha256"] != scope.digest
            or lease["run_nonce_sha256"] != hashlib.sha256(directory.name.encode()).hexdigest()):
        raise SupervisorError("supervisor_lease_binding_mismatch")
    # Manifest is the commit marker. A partial preparation is never started and
    # remains private for the owning lifecycle's fail-closed cleanup.
    _publish_bytes(directory / "supervisor-database.url",
                   url.render_as_string(hide_password=False).encode(), exclusive=True)
    _publish(directory / "supervisor-authority.json", {
        "user_id": user_id, "snapshot": authorized.snapshot, "snapshot_sha256": authorized.snapshot_sha256,
    }, exclusive=True)
    _publish(directory / "supervisor.json", value, exclusive=True)
    Supervisor(directory)


class SupervisorProcess:
    """Owned child handle, first-tick readiness, and terminal-before-recovery fence."""

    def __init__(self, directory: Path, *, business_broker=False):
        if type(business_broker) is not bool:
            raise SupervisorError("supervisor_broker_mode_invalid")
        self.business_broker = business_broker
        self.supervisor = Supervisor(directory)
        self.process = None

    def start(self, *, timeout_seconds=60, interval_seconds=30):
        if type(interval_seconds) is not int or not 1 <= interval_seconds <= 60:
            raise SupervisorError("supervisor_schedule_invalid")
        if self.process is not None or self.supervisor.state_path.exists():
            raise SupervisorError("supervisor_restart_requires_recovery")
        self.process = subprocess.Popen(
            [str(provider.ROOT / "apps/api/.venv/bin/python"), str(Path(__file__).resolve()),
             "supervise", "--run-directory", str(self.supervisor.directory), "--interval-seconds", str(interval_seconds),
             *(["--business-broker"] if self.business_broker else [])],
            cwd=provider.ROOT, env=provider._environment(), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout_seconds
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                state = _json(self.supervisor.state_path)
                if (state.get("phase") == "running" and state.get("ticks", 0) >= 1
                        and state.get("run_sha256") == hashlib.sha256(self.supervisor.manifest["run_id"].encode()).hexdigest()
                        and (not self.business_broker or state.get("business_broker_ready") is True)
                        and (self.supervisor.manifest["schema_version"] not in IDENTITY_SCHEMAS
                             or state.get("agentshield_identity_ready") is True)
                        and (self.supervisor.manifest["schema_version"] not in RELAY_SCHEMAS
                             or state.get("agentshield_relay_ready") is True)
                        and (self.supervisor.manifest["schema_version"] != FORWARD_SCHEMA
                             or state.get("hermes_forward_ready") is True)
                        and self.process.poll() is None):
                    return
            except FileNotFoundError:
                pass
            time.sleep(.05)
        raise SupervisorError("supervisor_start_not_ready")

    def assert_running(self):
        if self.process is None or self.process.poll() is not None:
            raise SupervisorError("supervisor_not_running")
        state = _json(self.supervisor.state_path)
        if (state.get("phase") != "running" or state.get("ticks", 0) < 1
                or state.get("run_sha256") != hashlib.sha256(self.supervisor.manifest["run_id"].encode()).hexdigest()
                or (self.business_broker and state.get("business_broker_ready") is not True)
                or (self.supervisor.manifest["schema_version"] in IDENTITY_SCHEMAS
                    and state.get("agentshield_identity_ready") is not True)
                or (self.supervisor.manifest["schema_version"] in RELAY_SCHEMAS
                    and state.get("agentshield_relay_ready") is not True)
                or (self.supervisor.manifest["schema_version"] == FORWARD_SCHEMA
                    and state.get("hermes_forward_ready") is not True)
                or self.process.poll() is not None):
            raise SupervisorError("supervisor_not_running")
        return state

    def wait_contained(self, *, timeout_seconds=150):
        if self.process is None:
            raise SupervisorError("supervisor_not_started")
        try:
            code = self.process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            raise SupervisorError("supervisor_still_running") from None
        state = _json(self.supervisor.state_path)
        if code != 1 or state.get("phase") != "contained":
            raise SupervisorError("supervisor_containment_unconfirmed")

    def stop(self, *, timeout_seconds=150):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                # Do not remove state, release ownership or restore the Provider
                # while the worker may still rotate its token.
                raise SupervisorError("supervisor_still_running") from None
        self.supervisor.recover()


class Supervisor:
    def __init__(self, directory: Path):
        if (not directory.is_absolute() or directory.parent != host.RUN_ROOT
                or re.fullmatch(r"[0-9a-f]{16}", directory.name) is None):
            raise SupervisorError("supervisor_run_directory_invalid")
        _directory(host.RUN_ROOT)
        _directory(directory)
        self.directory = directory
        self.manifest = _json(directory / "supervisor.json")
        value = self.manifest
        api_bound = isinstance(value, dict) and value.get("schema_version") in API_SCHEMAS
        identity_bound = isinstance(value, dict) and value.get("schema_version") in IDENTITY_SCHEMAS
        relay_bound = isinstance(value, dict) and value.get("schema_version") in RELAY_SCHEMAS
        forward_bound = isinstance(value, dict) and value.get("schema_version") == FORWARD_SCHEMA
        if (not isinstance(value, dict) or set(value) != MANIFEST_KEYS | ({"api_execution_lease"} if api_bound else set()) | ({"agentshield_identity"} if identity_bound else set()) | ({"agentshield_relay"} if relay_bound else set()) | ({"hermes_forward"} if forward_bound else set())
                or value["schema_version"] not in {SCHEMA, *API_SCHEMAS}
                or value["sandbox_nonce"] != directory.name
                or value["sandbox_name"] != "siq-qwen38-scoped-" + directory.name
                or not isinstance(value["run_id"], str)
                or broker_request_identity.SAFE_ID_RE.fullmatch(value["run_id"]) is None):
            raise SupervisorError("supervisor_binding_invalid")
        self.scope = enterprise_data_scope.parse_scope(value["scope"])
        if self.scope.data_classification != "confidential_local":
            raise SupervisorError("supervisor_scope_invalid")
        if api_bound:
            binding = _api_lease_service().parse(value["api_execution_lease"])
            if value["run_id"] != "qwen-request-" + directory.name or binding.pool_binding_run_id != value["run_id"]:
                raise SupervisorError("supervisor_api_lease_run_mismatch")
        if identity_bound:
            qwen38_request_identity.validate_reference(value["agentshield_identity"])
        if relay_bound:
            qwen38_request_relay.validate_reference(value["agentshield_relay"])
        if forward_bound:
            qwen38_request_forward.validate_reference(value["hermes_forward"])
        self.owner = qwen38_candidate_gateway_owner.GatewayRunOwner(root=host.RUN_ROOT, list_sandboxes=_inventory)
        self.lease = qwen38_candidate_lease.CandidateDataLease(
            path=directory / "candidate-data-lease.json", sandbox_name=value["sandbox_name"],
            registry=broker_admission_registry.BrokerAdmissionRegistry(directory / "broker-admission.json"),
        )
        self.state_path = directory / "supervisor-state.json"
        self._verify_binding()

    def _verify_binding(self):
        value = self.manifest
        owner = self.owner.status()
        if (owner is None or owner["phase"] != "active"
                or any(owner[key] != value[key] for key in ("run_id", "sandbox_name", "sandbox_nonce"))):
            raise SupervisorError("supervisor_gateway_owner_mismatch")
        # A damaged lease can still be revoked by recover; it cannot tick.
        try:
            lease = self.lease.status()
        except (qwen38_candidate_lease.CandidateLeaseError, OSError, ValueError):
            lease = None
        if lease is not None and (
            lease["run_id"] != value["run_id"] or lease["scope_sha256"] != self.scope.digest
            or lease["run_nonce_sha256"] != hashlib.sha256(value["sandbox_nonce"].encode()).hexdigest()
        ):
            raise SupervisorError("supervisor_lease_binding_mismatch")

    @contextmanager
    def _exclusive(self):
        _directory(self.directory)
        path = self.directory / ".supervisor.lock"
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(descriptor)
            _file_info(info)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SupervisorError("supervisor_already_running") from None
            observed = path.lstat()
            if (observed.st_dev, observed.st_ino) != (info.st_dev, info.st_ino):
                raise SupervisorError("supervisor_lock_changed")
            self._verify_binding()
            yield
        finally:
            os.close(descriptor)

    def _guard(self, *, key=b"", reauthorize=lambda _: None):
        # Empty signing material is used only by stop/recover. Those methods
        # never mint a token or call the authorization callback.
        return host.make_host_guard(
            lease=self.lease, scope=self.scope, signing_key=key, reauthorize=reauthorize,
            sandbox_nonce=self.manifest["sandbox_nonce"], host_path=self.directory / "data.identity.next.token",
            operation_lock_path=host.RUN_ROOT / ".run-guard.lock",
        )

    def _identity(self, *, revoke=False):
        if self.manifest["schema_version"] not in IDENTITY_SCHEMAS:
            return
        prepared = qwen38_request_identity.PreparedIdentity(
            self.directory, self.manifest["agentshield_identity"]["record_sha256"])
        action = qwen38_request_identity.revoke if revoke else qwen38_request_identity.check
        action(prepared, run_id=self.manifest["run_id"], scope=self.scope,
               execution_binding=self.manifest["api_execution_lease"])

    def _contain(self, guard, *, recover=False):
        failed = False
        try:
            guard.recover_fail_closed() if recover else guard.stop()
        except BaseException:
            failed = True
        try:
            self._identity(revoke=True)
        except BaseException:
            failed = True
        if self.manifest["schema_version"] in RELAY_SCHEMAS:
            try:
                qwen38_request_relay.assert_absent(self.directory, self.manifest)
            except BaseException:
                failed = True
        if self.manifest["schema_version"] == FORWARD_SCHEMA:
            try:
                qwen38_request_forward.assert_absent()
            except BaseException:
                failed = True
        if failed:
            raise SupervisorError("supervisor_containment_failed") from None

    def _record(self, phase, *, ticks=0, lease=None, business_broker_ready=False):
        value = {"schema_version": SCHEMA, "phase": phase,
                                 "checked_at": int(time.time()), "ticks": ticks,
                                 "run_sha256": hashlib.sha256(self.manifest["run_id"].encode()).hexdigest()}
        invocation = os.environ.get("INVOCATION_ID", "")
        if re.fullmatch(r"[a-f0-9]{32}", invocation):
            value["invocation_sha256"] = hashlib.sha256(invocation.encode()).hexdigest()
        if lease is not None:
            value.update(lease_generation=lease["generation"], lease_expires_at=lease["expires_at"])
        if business_broker_ready:
            value["business_broker_ready"] = True
        if phase == "running" and self.manifest["schema_version"] in IDENTITY_SCHEMAS:
            value["agentshield_identity_ready"] = True
        if phase == "running" and self.manifest["schema_version"] in RELAY_SCHEMAS:
            value["agentshield_relay_ready"] = True
        if phase == "running" and self.manifest["schema_version"] == FORWARD_SCHEMA:
            value["hermes_forward_ready"] = True
        _publish(self.state_path, value)

    def recover(self):
        with self._exclusive():
            try:
                self._contain(self._guard(), recover=True)
            except BaseException:
                self._record("containment_failed")
                raise SupervisorError("supervisor_containment_failed") from None
            self._record("contained")

    def supervise(self, stop: threading.Event, *, interval_seconds=30, business_broker=False):
        if (not isinstance(stop, threading.Event) or type(interval_seconds) is not int
                or not 1 <= interval_seconds <= 60 or type(business_broker) is not bool):
            raise SupervisorError("supervisor_schedule_invalid")
        with self._exclusive():
            guard = self._guard()
            engine = None
            data_broker = None
            relay = None
            forward = None
            failed = False
            ticks = 0
            stage = 'startup_validation'
            try:
                if self.state_path.exists():
                    raise SupervisorError("supervisor_restart_requires_recovery")
                if self.manifest["schema_version"] in API_SCHEMAS and not business_broker:
                    raise SupervisorError("supervisor_api_lease_requires_business_broker")
                self._record("starting")
                stage = 'load_authority'
                engine, reauthorize = _load_authority(self.directory, self.scope)
                stage = 'signing_material'
                key = broker_request_identity.read_key_file(provider.ROOT / broker_lifecycle.IDENTITY_KEY_RELATIVE_PATH)
                stage = 'guard_configuration'
                guard = self._guard(key=key, reauthorize=reauthorize)
                while not stop.is_set():
                    stage = 'owner_binding'
                    self._verify_binding()
                    stage = 'guard_tick'
                    lease = guard.tick()
                    stage = 'runtime_identity'
                    self._identity()
                    if self.manifest["schema_version"] in RELAY_SCHEMAS:
                        stage = 'relay'
                        if relay is None:
                            relay = qwen38_request_relay.RequestRelay(self.directory, self.manifest, self.scope)
                            relay.start()
                        relay.assert_running()
                    if self.manifest["schema_version"] == FORWARD_SCHEMA:
                        stage = 'forward'
                        if forward is None:
                            forward = qwen38_request_forward.RequestForward(self.directory, self.manifest)
                            forward.start()
                        forward.assert_running()
                    if business_broker:
                        stage = 'business_broker'
                        if data_broker is None:
                            data_broker = qwen38_business_broker.BusinessBroker(
                                project_root=provider.ROOT, manifest=self.manifest, scope=self.scope,
                                registry=self.lease.registry, signing_key=key,
                                reauthorize=reauthorize, stop=stop,
                            )
                            data_broker.start()
                        data_broker.assert_running()
                    ticks += 1
                    stage = 'state_publication'
                    self._record("running", ticks=ticks, lease=lease, business_broker_ready=business_broker)
                    stage = 'wait'
                    stop.wait(interval_seconds)
            except BaseException as exc:
                failed = True
                _report_failure(stage, exc)
            finally:
                if forward is not None:
                    try:
                        forward.close()
                    except BaseException as exc:
                        failed = True
                        _report_failure('close_forward', exc)
                if relay is not None:
                    try:
                        relay.close()
                    except BaseException as exc:
                        failed = True
                        _report_failure('close_relay', exc)
                if data_broker is not None:
                    try:
                        data_broker.close()
                        failed = failed or data_broker.failed.is_set()
                        if data_broker.failed.is_set():
                            _report_failure('business_broker_failed')
                    except BaseException as exc:
                        failed = True
                        _report_failure('close_business_broker', exc)
                try:
                    self._contain(guard)
                except BaseException as exc:
                    _report_failure('containment', exc)
                    self._record("containment_failed", ticks=ticks)
                    raise SupervisorError("supervisor_containment_failed") from None
                finally:
                    if engine is not None:
                        try:
                            engine.dispose()
                        except Exception as exc:
                            failed = True
                            _report_failure('dispose_engine', exc)
                self._record("contained" if failed else "stopped", ticks=ticks)
            if failed:
                raise SupervisorError("supervisor_failed_closed") from None


def _load_authority(directory, scope):
    # Same owning repository's business service; never a sibling database or
    # dynamically selected policy implementation.
    from sqlmodel import Session, create_engine

    openshell_data_scope = _authority_service()

    value = _json(directory / "supervisor-authority.json")
    if (not isinstance(value, dict) or set(value) != {"user_id", "snapshot", "snapshot_sha256"}
            or not isinstance(value["user_id"], str)):
        raise SupervisorError("supervisor_authority_invalid")
    authorized = openshell_data_scope.AuthorizedDataScope(
        scope_ref=scope, snapshot=value["snapshot"], snapshot_sha256=value["snapshot_sha256"],
    )
    url = _database_url(_read(directory / "supervisor-database.url").decode("utf-8").strip())
    engine = create_engine(url,
                           connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"})
    try:
        reauthorize = openshell_data_scope.make_local_candidate_reauthorizer(
            lambda: Session(engine), user_id=value["user_id"], authorized=authorized,
        )
        manifest = _json(directory / "supervisor.json")
        if manifest["schema_version"] in API_SCHEMAS:
            lease_service = _api_lease_service()
            binding = lease_service.parse(manifest["api_execution_lease"])
            lease_service.require_scope(binding, scope=scope, user_id=value["user_id"],
                                        runtime_run_id=manifest["run_id"])
            reauthorize = lease_service.fence_authorizer(lambda: Session(engine), binding, reauthorize)
    except BaseException:
        engine.dispose()
        raise
    return engine, reauthorize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("supervise", "recover"))
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--business-broker", action="store_true")
    args = parser.parse_args()
    stop = threading.Event()
    if args.command == "supervise":
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        supervisor = Supervisor(args.run_directory)
        if args.command == "supervise":
            supervisor.supervise(stop, interval_seconds=args.interval_seconds, business_broker=args.business_broker)
        else:
            supervisor.recover()
    except BaseException as exc:
        code = str(exc) if isinstance(exc, SupervisorError) else "supervisor_operation_failed"
        print(json.dumps({"passed": False, "error_code": code, "production_eligible": False}))
        return 1
    print(json.dumps({"passed": True, "command": args.command, "production_eligible": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
