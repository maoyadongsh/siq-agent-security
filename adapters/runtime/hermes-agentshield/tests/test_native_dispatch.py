"""Mandatory final boundary: exact parameters, real reads and actual effects."""

# Keep exception assertions visually separate from the guarded execution scope.
# ruff: noqa: SIM117

import concurrent.futures
import contextlib
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

directory = Path(__file__).parents[1]
package_spec = importlib.util.spec_from_file_location("siq_dispatch_test_package", directory / "native_dispatch.py",
                                                     submodule_search_locations=[str(directory)])
native = importlib.util.module_from_spec(package_spec)
sys.modules[package_spec.name] = native
package_spec.loader.exec_module(native)
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux native profile")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                                    allow_nan=False).encode()).hexdigest()


def fixture_runtime(*, source=None, authorize=None, result=None):
    events, calls, results = [], [], []

    def default_authorize(request, load):
        calls.append((request, load))
        return {"action": "allow", "request_binding": digest(request), "decision_id": "fixture-decision"}

    runtime = native.Runtime("hri-" + "a" * 32, "fixture", source or events.append,
                             authorize or default_authorize, result or results.append)
    return runtime, events, calls, results


def call(runtime, params=None, *, task="task", session="session", tool="read_file", cid="call"):
    return runtime.call(tool, {} if params is None else params, task, session, cid)


@pytest.mark.parametrize("namespace", [
    "legacy", "x" * 191,
    "siq:openshell:pool:" + "a" * 24 + ":qwen-request-2222222222222222:siq_analysis",
])
def test_request_namespace_preserved_in_actual_task_events(namespace):
    events = []
    runtime = native.Runtime("hri-" + "a" * 32, namespace, events.append, lambda *_: None, lambda *_: None)
    with runtime.task("task", "实际会话"):
        pass
    session = namespace + ":" + hashlib.sha256("实际会话".encode()).hexdigest()
    assert len(session.encode()) == len(namespace) + 65 <= 256
    assert [e["session_id"] for e in events] == [session, session]
    assert runtime._session("another-session") != session


@pytest.mark.parametrize("namespace", [
    "", None, 1, "x" * 192, ":leading", "trailing:", "double::colon", "中文",
    "a\nb", "a\x00b", "a\x7fb", "space here", "slash/path", "a\\b",
])
def test_invalid_request_namespace_refused_before_task(namespace):
    with pytest.raises(native.DispatchError, match="^native_dispatch_unavailable$"):
        native.Runtime("hri-" + "a" * 32, namespace, lambda *_: None, lambda *_: None, lambda *_: None)


def test_real_reads_and_switches_preserve_lineage(tmp_path):
    runtime, events, calls, results = fixture_runtime()
    paths = []
    for name in ("reader", "writer"):
        path = tmp_path / name / "SKILL.md"
        path.parent.mkdir()
        path.write_text(name)
        paths.append(path)
    with runtime.task("task", "session"):
        with call(runtime, tool="read_file", cid="no-skill"):
            pass
        for index, path in enumerate(paths + paths[:1]):
            with call(runtime, tool="skill_view", cid=str(index)):
                assert runtime.read_skill(path) == path.parent.name
            with call(runtime, cid="after-" + str(index)):
                pass
        with call(runtime, tool="skill_view", cid="cache"):
            runtime.verify_cache("task", paths[0])
    sources = [event for event in events if event["kind"] == "skill_source"]
    assert calls[0][1] is None
    assert sources[0]["parent_load_id"] is None
    assert sources[1]["parent_load_id"] == sources[0]["load_id"]
    assert sources[2]["parent_load_id"] == sources[1]["load_id"]
    assert sources[3]["load_id"] == sources[2]["load_id"]
    assert sources[3]["source"]["cache_hit"] is True
    assert all(r["outcome"] == "returned" for r in results)
    assert events[-1]["kind"] == "task_end"
    with pytest.raises(native.DispatchError), call(runtime, cid="after-end"):
        pytest.fail("ended task executed")


@pytest.mark.parametrize("change", ["wrong-binding", "missing-decision", "extra", "redact", "failure", "ack"])
def test_untrusted_response_prevents_effect_and_poison_task(tmp_path, change):
    marker = tmp_path / "effect"

    def authorize(request, _):
        value = {"action": "allow", "request_binding": digest(request), "decision_id": "receipt"}
        if change == "wrong-binding":
            value["request_binding"] = "0" * 64
        elif change == "missing-decision":
            del value["decision_id"]
        elif change == "extra":
            value["extra"] = True
        elif change == "redact":
            value["action"] = "redact"
        elif change == "failure":
            raise ValueError("private data")
        elif change == "ack":
            return {"accepted": True}
        return value

    runtime, *_ = fixture_runtime(authorize=authorize)
    with runtime.task("task", "session"):
        for cid in ("call", "later"):
            with pytest.raises(native.DispatchError, match="^native_dispatch_unavailable$"):
                with call(runtime, cid=cid):
                    marker.write_text("must not execute")
    assert not marker.exists()


@pytest.mark.parametrize("action", ["deny", "hold"])
def test_denial_is_not_a_host_failure_but_call_never_replays(tmp_path, action):
    count = 0

    def authorize(request, _):
        nonlocal count
        count += 1
        return {"action": action if count == 1 else "allow", "request_binding": digest(request), "decision_id": "receipt"}

    runtime, *_ = fixture_runtime(authorize=authorize)
    with runtime.task("task", "session"):
        with pytest.raises(native.DispatchError, match="native_dispatch_denied"):
            with call(runtime):
                pytest.fail("denial executed")
        with pytest.raises(native.DispatchError), call(runtime):
            pytest.fail("same call replayed")
        with call(runtime, cid="new"):
            (tmp_path / "allowed").write_text("allowed")
    assert count == 2
    assert (tmp_path / "allowed").read_text() == "allowed"


def test_authorizer_cannot_mutate_handler_parameters():
    original = {"path": "allowed", "nested": {"value": "actual"}}

    def authorize(request, _):
        binding = digest(request)
        request["params"]["path"] = "forbidden"
        original["nested"]["value"] = "changed"
        return {"action": "allow", "request_binding": binding, "decision_id": "receipt"}

    runtime, *_ = fixture_runtime(authorize=authorize)
    with runtime.task("task", "session"), call(runtime, original) as checked:
        assert checked == {"path": "allowed", "nested": {"value": "actual"}}


@pytest.mark.parametrize("scenario", ["missing-task", "wrong-session", "missing-call", "nested-call", "subagent", "expired", "repeat-task"])
def test_lifecycle_failures_cannot_run(scenario):
    runtime, *_ = fixture_runtime()
    if scenario == "subagent":
        with pytest.raises(native.DispatchError):
            with runtime.task("task", "session", "parent-session"):
                pytest.fail("unproven parent accepted")
        return
    with runtime.task("task", "session"):
        kwargs = {}
        outer = contextlib.nullcontext()
        if scenario == "missing-task":
            kwargs["task"] = "unknown"
        elif scenario == "wrong-session":
            kwargs["session"] = "another"
        elif scenario == "missing-call":
            kwargs["cid"] = None
        elif scenario == "nested-call":
            outer = call(runtime, cid="outer")
        elif scenario == "expired":
            runtime.tasks["task"].until = 0
        elif scenario == "repeat-task":
            with pytest.raises(native.DispatchError):
                with runtime.task("task", "session"):
                    pytest.fail("task reset")
            return
        with outer, pytest.raises(native.DispatchError):
            with call(runtime, **kwargs):
                pytest.fail("invalid lifecycle executed")


def test_cache_drift_cannot_fall_back_to_no_skill(tmp_path):
    runtime, *_ = fixture_runtime()
    path = tmp_path / "SKILL.md"
    path.write_text("first")
    with runtime.task("task", "session"):
        with call(runtime, tool="skill_view"):
            runtime.read_skill(path)
        path.write_text("other")
        with call(runtime, tool="skill_view", cid="cache"):
            with pytest.raises(native.DispatchError):
                runtime.verify_cache("task", path)
        with pytest.raises(native.DispatchError), call(runtime, cid="later"):
            pytest.fail("source error reset lineage")


def test_observation_failure_keeps_effect_but_prevents_retry(tmp_path):
    def fail(_):
        raise RuntimeError("private diagnostic")

    runtime, *_ = fixture_runtime(result=fail)
    path = tmp_path / "actual-effect"
    with runtime.task("task", "session"):
        with pytest.raises(native.DispatchError, match="^native_dispatch_unavailable$"):
            with call(runtime):
                path.write_text("already done")
        with pytest.raises(native.DispatchError), call(runtime, cid="new"):
            pytest.fail("uncertain task continued")
    assert path.read_text() == "already done"


def test_parallel_tasks_keep_separate_source_and_actual_calls(tmp_path):
    runtime, _, calls, _ = fixture_runtime()
    barrier = threading.Barrier(2)

    def worker(task):
        path = tmp_path / task / "SKILL.md"
        path.parent.mkdir()
        path.write_text(task)
        with runtime.task(task, "session"):
            with call(runtime, task=task, tool="skill_view"):
                runtime.read_skill(path)
            barrier.wait(timeout=3)
            with call(runtime, task=task, cid="effect"):
                (path.parent / "effect").write_text(task)

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        list(pool.map(worker, ["one", "two"]))
    later = [(req["task_id"], load) for req, load in calls if req["tool_call_id"] == "effect"]
    assert len(later) == 2 and later[0][1] != later[1][1]
    assert all((tmp_path / task / "effect").read_text() == task for task in ("one", "two"))


def test_fork_cannot_reuse_live_runtime(tmp_path):
    runtime, *_ = fixture_runtime()
    with runtime.task("task", "session"):
        pid = os.fork()
        if pid == 0:
            try:
                with call(runtime):
                    (tmp_path / "forbidden").write_text("fork")
            except native.DispatchError:
                os._exit(0)
            os._exit(1)
        assert os.waitpid(pid, 0)[1] == 0
    assert not (tmp_path / "forbidden").exists()


def test_task_end_does_not_wait_forever_for_abandoned_handler():
    runtime, events, _, results = fixture_runtime()
    entered, release = threading.Event(), threading.Event()

    def worker():
        with call(runtime):
            entered.set()
            assert release.wait(3)

    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        try:
            with runtime.task("task", "session"):
                future = pool.submit(worker)
                assert entered.wait(2)
                started = time.monotonic()
            assert time.monotonic() - started < .5
            assert events[-1]["kind"] == "task_end" and events[-1]["in_flight"] is True
            assert events[-1]["failed"] is True
            with pytest.raises(native.DispatchError):
                with call(runtime, cid="new"):
                    pytest.fail("ended task continued")
        finally:
            release.set()
        future.result(timeout=3)
    assert results[-1]["outcome"] == "returned"  # A late result is not erased.


def test_queued_call_stops_when_task_ends():
    runtime, _, calls, _ = fixture_runtime()
    entered, release, queued = threading.Event(), threading.Event(), threading.Event()

    def active():
        with call(runtime):
            entered.set()
            assert release.wait(3)

    def waiting():
        queued.set()
        with pytest.raises(native.DispatchError), call(runtime, cid="queued"):
            pytest.fail("queued tool executed after shutdown")

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        try:
            with runtime.task("task", "session"):
                first = pool.submit(active)
                assert entered.wait(2)
                second = pool.submit(waiting)
                assert queued.wait(2)
            second.result(timeout=1)
            assert len(calls) == 1
        finally:
            release.set()
        first.result(timeout=3)


def test_task_end_on_exception_is_not_reported_as_normal():
    runtime, events, *_ = fixture_runtime()
    with pytest.raises(ValueError), runtime.task("task", "session"):
        raise ValueError("synthetic failure")
    assert events[-1]["kind"] == "task_end" and events[-1]["failed"] is True
    assert not runtime.tasks["task"].active


@pytest.mark.parametrize("managed", [False, True])
def test_bootstrap_explicit_managed_installation_pair(tmp_path, managed):
    runtime, events, _, _ = fixture_runtime()
    runtime = native.Runtime(runtime.agent, runtime.namespace, runtime.observe, runtime.authorize,
                             runtime.result, managed_installations=managed)
    main = tmp_path / "SKILL.md"
    main.write_text("Synthetic installed skill")
    os.link(main, tmp_path / "private-owner-link")
    with runtime.task("task", "session"), call(runtime, tool="skill_view"):
        if managed:
            assert runtime.read_skill(main) == "Synthetic installed skill"
            assert any(event["kind"] == "skill_source" for event in events)
        else:
            with pytest.raises(native.DispatchError):
                runtime.read_skill(main)
