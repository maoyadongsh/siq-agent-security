"""Owned integration bootstrap: actual Hermes tools, real online SIQ decisions.

No model call, no synthetic authority callback; the test operator supplies two
synthetic Skill packages through real signed import/approval/installation.
"""

import concurrent.futures
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/opt/hermes-agent")
os.environ["HOME"] = "/tmp/siq-native-online"
os.environ["HERMES_HOME"] = "/tmp/siq-native-online/hermes"
os.environ["HERMES_RELAY_ENABLED"] = "false"
os.environ["TERMINAL_ENV"] = "local"
Path(os.environ["HERMES_HOME"]).mkdir(mode=0o700, parents=True)

import siq_native_runtime as native
from model_tools import handle_function_call
from siq_native_runtime.native_channel import HermesChannel
from siq_native_runtime.native_dispatch import DispatchError
from siq_native_runtime.native_online import Callbacks
from tools import skills_tool

skills_tool.SKILLS_DIR = Path("/opt/siq/native-business/skills")
directory = Path("/tmp/siq-native-online/channel")
directory.mkdir(mode=0o700)
subject_agent, namespace, session = sys.argv[1:]
root = Path("/sandbox/native-business")
root.mkdir(mode=0o700)
(root / "input.txt").write_text("owned integration input\n")
print(json.dumps({"native_probe_ready": True, "pid": os.getpid(), "files": [], "channel_directory": str(directory)}), flush=True)
deadline = time.monotonic() + 60
while not (directory / "native-host.sock").exists():
    if time.monotonic() >= deadline:
        raise SystemExit("native_host_not_ready")
    time.sleep(.05)
client = HermesChannel(directory / "native-host.sock", timeout=5,
                       server_credentials=(0, os.getuid(), os.getgid()))
mapped = Callbacks.via_host(client)
runtime = native.Runtime(subject_agent, namespace, mapped.observe, mapped.authorize, mapped.observe)
native.configure(runtime)
checks, outcomes = {}, []


def dispatch(task, tool, params, call):
    result = json.loads(handle_function_call(tool, params, task_id=task, session_id=session, tool_call_id=call))
    # Only record structure and success flags; do not log document content.
    outcomes.append({"task": task, "tool": tool, "call": call, "keys": sorted(result), "error": "error" in result})
    return result


with native.task_scope("reader-task", session):
    loaded = dispatch("reader-task", "skill_view", {"name": "reader"}, "load-reader")
    checks["real_reader_skill_loaded"] = loaded.get("success") is True
    read = dispatch("reader-task", "read_file", {"path": str(root / "input.txt")}, "reader-read")
    checks["reader_real_read_allowed"] = "owned integration input" in json.dumps(read) and "error" not in read
    refused = dispatch("reader-task", "write_file", {"path": str(root / "reader-denied.txt"), "content": "must-not-write"}, "reader-write")
    checks["reader_write_denied_without_effect"] = "error" in refused and not (root / "reader-denied.txt").exists()
    switched = dispatch("reader-task", "skill_view", {"name": "writer"}, "switch-writer")
    checks["real_second_skill_loaded"] = switched.get("success") is True
    refused = dispatch("reader-task", "write_file", {"path": str(root / "switch-denied.txt"), "content": "must-not-write"}, "switched-write")
    checks["switch_preserves_reader_ancestor_limit"] = "error" in refused and not (root / "switch-denied.txt").exists()

with native.task_scope("writer-task", session):
    loaded = dispatch("writer-task", "skill_view", {"name": "writer"}, "load-writer")
    checks["independent_writer_skill_loaded"] = loaded.get("success") is True
    written = dispatch("writer-task", "write_file", {"path": str(root / "writer-allowed.txt"), "content": "real-hermes-authorized-output"}, "writer-write")
    checks["writer_real_write_allowed"] = "error" not in written and (root / "writer-allowed.txt").read_text() == "real-hermes-authorized-output"
    refused = dispatch("writer-task", "write_file", {"path": "/sandbox/outside-denied.txt", "content": "must-not-write"}, "outside-write")
    checks["writer_outside_scope_denied_without_effect"] = "error" in refused and not Path("/sandbox/outside-denied.txt").exists()
    replay = dispatch("writer-task", "write_file", {"path": str(root / "replay-denied.txt"), "content": "must-not-write"}, "writer-write")
    checks["consumed_call_id_cannot_change_parameters_and_replay"] = "error" in replay and not (root / "replay-denied.txt").exists()

ended = dispatch("writer-task", "write_file", {"path": str(root / "ended-denied.txt"), "content": "must-not-write"}, "after-task-end")
checks["ended_task_cannot_execute"] = "error" in ended and not (root / "ended-denied.txt").exists()

# Both native tasks load before either writes. This forces overlapping lifetime
# and opposite permissions in one process/session, rather than sequential runs.
barrier = threading.Barrier(2)


def concurrent_task(name):
    task = "concurrent-" + name
    with native.task_scope(task, session):
        loaded = dispatch(task, "skill_view", {"name": name}, task + "-load")
        barrier.wait(timeout=15)
        path = root / (task + ".txt")
        result = dispatch(task, "write_file", {"path": str(path), "content": task}, task + "-write")
        allowed = name == "writer"
        return (loaded.get("success") is True and ("error" not in result) == allowed
                and (path.read_text() == task if allowed and path.exists() else not path.exists() and not allowed))


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures = {name: pool.submit(concurrent_task, name) for name in ("reader", "writer")}
    for name, future in futures.items():
        checks["concurrent_" + name + "_keeps_own_permissions"] = future.result(timeout=25)

# The owning host pauses the next actual call, publishes a real signed
# revocation in the Go store, verifies its readback, then forwards the call.
# No test control endpoint or approval credential is exposed to the runtime.
with native.task_scope("context-revoke-task", session):
    loaded = dispatch("context-revoke-task", "skill_view", {"name": "writer"}, "context-load")
    before = dispatch("context-revoke-task", "write_file", {"path": str(root / "context-before.txt"), "content": "before-context-revocation"}, "context-before-revoke")
    checks["context_write_allowed_before_revocation"] = loaded.get("success") is True and "error" not in before
    after = dispatch("context-revoke-task", "write_file", {"path": str(root / "context-revoked-denied.txt"), "content": "must-not-write"}, "context-after-revoke")
    checks["revoked_context_cannot_execute"] = "error" in after and not (root / "context-revoked-denied.txt").exists()

with native.task_scope("grant-revoke-task", session):
    loaded = dispatch("grant-revoke-task", "skill_view", {"name": "writer"}, "grant-load")
    before = dispatch("grant-revoke-task", "write_file", {"path": str(root / "grant-before.txt"), "content": "before-grant-revocation"}, "grant-before-revoke")
    checks["separate_context_still_allowed_before_grant_revocation"] = loaded.get("success") is True and "error" not in before
    after = dispatch("grant-revoke-task", "write_file", {"path": str(root / "grant-revoked-denied.txt"), "content": "must-not-write"}, "grant-after-revoke")
    checks["revoked_skill_grant_cannot_execute"] = "error" in after and not (root / "grant-revoked-denied.txt").exists()

try:
    with native.task_scope("baseline-revoke-task", session):
        loaded = dispatch("baseline-revoke-task", "skill_view", {"name": "reader"}, "baseline-load")
        before = dispatch("baseline-revoke-task", "read_file", {"path": str(root / "input.txt")}, "baseline-before-revoke")
        checks["other_skill_still_allowed_before_agent_revocation"] = loaded.get("success") is True and "owned integration input" in json.dumps(before) and "error" not in before
        after = dispatch("baseline-revoke-task", "read_file", {"path": str(root / "input.txt")}, "baseline-after-revoke")
        checks["revoked_agent_cannot_read"] = "error" in after and "owned integration input" not in json.dumps(after)
except DispatchError:
    # Revoked Agent authentication may also reject task_end. This is a
    # terminal fail-closed condition, never a successful cleanup claim.
    checks["revoked_agent_end_failed_closed"] = True

checks.setdefault("revoked_agent_cannot_read", False)

result = {"native_online_verified": all(checks.values()), "checks": checks, "outcomes": outcomes,
          "model_calls": 0, "actual_hermes_tools": True, "synthetic_skill_content": True,
          "business_entry_acceptance": False,
          "output_sha256": hashlib.sha256((root / "writer-allowed.txt").read_bytes()).hexdigest()
          if (root / "writer-allowed.txt").exists() else None}
print(json.dumps(result), flush=True)
time.sleep(60)  # Host independently reads effects before destroying its sandbox.
