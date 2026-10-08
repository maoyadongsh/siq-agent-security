"""Mandatory dispatch glue for the pinned native profile, never a policy engine.

The protected bootstrap supplies real SIQ callbacks. This module is not loaded
by the legacy plugin; an unconfigured patched host always refuses execution.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import re
import threading
import time
import uuid

from .native_source import SkillSourceReader

MAX_TASKS = 4096
MAX_CALLS = 16384
MAX_PARAMS = 1048576
_current = contextvars.ContextVar("siq_native_dispatch", default=None)
_after_allow = contextvars.ContextVar("siq_native_after_allow", default=None)
_runtime = None
_configuration_lock = threading.Lock()


class DispatchError(RuntimeError):
    """Only fixed categories cross the native tool-result boundary."""


def _unavailable():
    return DispatchError("native_dispatch_unavailable")


def valid_session_namespace(value):
    return (type(value) is str and 1 <= len(value) <= 191
            and re.fullmatch(r"[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)*", value) is not None)


def _text(value, limit=256):
    return (type(value) is str and 0 < len(value.encode("utf-8", errors="strict")) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _json(value, depth=0):
    if depth > 64:
        raise _unavailable()
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise _unavailable()
        for item in value.values():
            _json(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _json(item, depth + 1)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise _unavailable()


def _canonical(value):
    _json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


class _Task:
    def __init__(self, runtime, task, session):
        self.task, self.session = task, session
        self.active, self.failed = True, False
        self.until = time.monotonic() + 3600
        self.lock = threading.RLock()
        self.calls, self.sources = set(), {}
        self.main, self.load = None, None
        self.reader = SkillSourceReader(lambda event: runtime._source(self, event),
                                       managed_link_pair=runtime.managed_installations)


class Runtime:
    def __init__(self, agent_id, session_namespace, observe_source, authorize, observe_result, *,
                 managed_installations=False):
        if (type(agent_id) is not str or not re.fullmatch(r"hri-[a-f0-9]{32}", agent_id)
                or not valid_session_namespace(session_namespace)
                or type(managed_installations) is not bool
                or not all(callable(f) for f in (observe_source, authorize, observe_result))):
            raise _unavailable()
        self.agent, self.namespace = agent_id, session_namespace
        self.observe, self.authorize, self.result = observe_source, authorize, observe_result
        self.managed_installations = managed_installations
        self.pid = os.getpid()
        self.tasks, self.lock = {}, threading.RLock()

    def _process(self):
        if os.getpid() != self.pid:
            raise _unavailable()

    def _session(self, session):
        if not _text(session):
            raise _unavailable()
        return self.namespace + ":" + hashlib.sha256(session.encode()).hexdigest()

    def _live(self, task):
        self._process()
        if not task.active or task.failed or time.monotonic() >= task.until:
            task.failed = True
            raise _unavailable()

    def _event(self, task, kind, **extra):
        return {"schema_version": "native-hermes-lifecycle/v1", "kind": kind,
                "agent_id": self.agent, "task_id": task.task, "session_id": task.session, **extra}

    def _notify(self, task, kind, **extra):
        self._live(task)
        try:
            if self.observe(self._event(task, kind, **extra)) is not None:
                raise _unavailable()
            self._live(task)
        except BaseException:  # noqa: BLE001 — cancellation must invalidate the boundary too.
            task.failed = True
            raise _unavailable() from None

    @contextlib.contextmanager
    def task(self, task_id, session_id, parent_session_id=None):
        self._process()
        if not _text(task_id) or parent_session_id or _current.get() is not None:
            # A parent session is not proof of a parent task or permission chain.
            raise _unavailable()
        session = self._session(session_id)
        with self.lock:
            if task_id in self.tasks or len(self.tasks) >= MAX_TASKS:
                raise _unavailable()
            task = self.tasks[task_id] = _Task(self, task_id, session)
        try:
            self._notify(task, "task_begin")
            yield
        except BaseException:
            task.failed = True
            raise
        finally:
            # An abandoned native handler may still be in flight. Invalidate
            # first, never wait indefinitely for that handler's task lock.
            task.active = False
            available = task.lock.acquire(blocking=False)
            if not available:
                task.failed = True
            try:
                if self.observe(self._event(task, "task_end", failed=task.failed, in_flight=not available)) is not None:
                    raise _unavailable()
            except BaseException:  # noqa: BLE001 — cancellation must invalidate the boundary too.
                task.failed = True
                raise _unavailable() from None
            finally:
                if available:
                    task.reader.close()
                    task.lock.release()

    def _source(self, task, source):
        main = source["skill_file"]["path_sha256"]
        parent = task.load
        load = task.load if main == task.main else "nload-" + uuid.uuid4().hex
        self._notify(task, "skill_source", load_id=load,
                     parent_load_id=parent if load != task.load else None,
                     source=source)
        task.main, task.load = main, load

    def _task(self, task_id, session_id):
        self._process()
        if not _text(task_id):
            raise _unavailable()
        with self.lock:
            task = self.tasks.get(task_id)
        if task is None or task.session != self._session(session_id):
            raise _unavailable()
        self._live(task)
        return task

    @contextlib.contextmanager
    def _execution_lock(self, task):
        # Check cancellation while queued; a stuck native handler must not
        # block later callers indefinitely or admit them after task shutdown.
        deadline = time.monotonic() + 5
        while True:
            self._live(task)
            if task.lock.acquire(timeout=0.05):
                break
            if time.monotonic() >= deadline:
                raise _unavailable()
        try:
            self._live(task)
            yield
        finally:
            task.lock.release()

    @contextlib.contextmanager
    def call(self, tool, params, task_id, session_id, tool_call_id):
        task = self._task(task_id, session_id)
        with self._execution_lock(task):
            self._live(task)
            if _current.get() is not None or not _text(tool, 128) or not _text(tool_call_id):
                raise _unavailable()
            if tool_call_id in task.calls or len(task.calls) >= MAX_CALLS:
                raise _unavailable()
            task.calls.add(tool_call_id)  # Never replay an uncertain authorization.
            try:
                if type(params) is not dict:
                    raise _unavailable()
                raw = _canonical(params)
                if len(raw) > MAX_PARAMS:
                    raise _unavailable()
                frozen = json.loads(raw)
                request = {"platform": "hermes", "agent_id": self.agent, "session_id": task.session,
                           "task_id": task.task, "tool": tool, "tool_call_id": tool_call_id, "params": frozen}
                binding = _hash(request)
                # The callback gets a separate copy, so it cannot accidentally
                # change the bytes subsequently consumed by the native handler.
                decision = self.authorize(json.loads(_canonical(request)), task.load)
                self._live(task)
                if (type(decision) is not dict or set(decision) != {"action", "request_binding", "decision_id"}
                        or decision["request_binding"] != binding or not _text(decision["decision_id"])
                        or decision["action"] not in ("allow", "deny", "hold")):
                    raise _unavailable()
            except BaseException:  # noqa: BLE001 — cancellation must invalidate the boundary too.
                task.failed = True
                raise _unavailable() from None
            if decision["action"] != "allow":
                raise DispatchError("native_dispatch_denied")
            callback = _after_allow.get()
            if callback is not None:
                try:
                    callback()
                except BaseException:  # noqa: BLE001 — a checkpoint failure must not run the tool.
                    task.failed = True
                    raise
            token = _current.set((self, task, tool))
            outcome = "raised"
            try:
                yield frozen
                outcome = "returned"
            finally:
                _current.reset(token)
                try:
                    if self.result(self._event(task, "tool_result", tool_call_id=tool_call_id,
                                               request_binding=binding, decision_id=decision["decision_id"],
                                               outcome=outcome)) is not None:
                        raise _unavailable()
                except BaseException:  # noqa: BLE001 — cancellation must invalidate the boundary too.
                    task.failed = True
                    raise _unavailable() from None
                finally:
                    if not task.active:
                        task.reader.close()

    def read_skill(self, main, content=None):
        current = _current.get()
        if current is None or current[0] is not self or current[2] != "skill_view":
            raise _unavailable()
        task = current[1]
        self._live(task)
        try:
            result = task.reader.read(main, content)
            source = str(main if content is None else content)
            if source in task.sources and task.sources[source] != str(main):
                raise _unavailable()
            task.sources[source] = str(main)
            return result
        except BaseException:  # noqa: BLE001 — cancellation must invalidate the boundary too.
            task.failed = True
            raise _unavailable() from None

    def verify_cache(self, task_id, source):
        current = _current.get()
        if current is None or current[0] is not self or current[2] != "skill_view" or current[1].task != task_id:
            raise _unavailable()
        task = current[1]
        self._live(task)
        try:
            main = task.sources[str(source)]
            task.reader.read(main, source, cache_hit=True)
        except BaseException:  # noqa: BLE001 — cancellation must invalidate the boundary too.
            task.failed = True
            raise _unavailable() from None


def configure(runtime):
    global _runtime
    if type(runtime) is not Runtime:
        raise _unavailable()
    runtime._process()
    with _configuration_lock:
        if _runtime is not None:
            raise _unavailable()
        _runtime = runtime


def _configured():
    if _runtime is None:
        raise _unavailable()
    _runtime._process()
    return _runtime


def task_scope(task_id, session_id, parent_session_id=None):
    return _configured().task(task_id, session_id, parent_session_id)


def call_scope(tool, params, task_id, session_id, tool_call_id):
    return _configured().call(tool, params, task_id, session_id, tool_call_id)


@contextlib.contextmanager
def after_allow(callback):
    """Run callback only after a native allow and before the tool body."""
    if not callable(callback):
        raise _unavailable()
    token = _after_allow.set(callback)
    try:
        yield
    finally:
        _after_allow.reset(token)


def read_skill(main, content=None):
    return _configured().read_skill(main, content)


def verify_cache(task_id, source):
    _configured().verify_cache(task_id, source)


def preprocess_allowed():
    _configured()
    return False  # No inline shell/template authorization in this profile.


def require_registry_dispatch(agent, name):
    """No permission decision: reject host routes lacking a final SIQ boundary."""
    _configured()
    direct = {"todo", "memory", "session_search", "message_agent", "delegate_task", "clarify",
              "read_terminal", "desktop_preview", "drive_preview", "annotate_preview",
              "read_window_below", "tour", "setup_mcp"}
    if (name in direct or name in (getattr(agent, "_context_engine_tool_names", None) or ())
            or (getattr(agent, "_memory_manager", None) is not None
                and agent._memory_manager.has_tool(name))):
        raise DispatchError("native_dispatch_unsupported_host_route")
