"""Actual Hermes tool effects under protected code; synthetic approved Skill."""

import errno
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/hermes-agent")
os.environ.update(HOME="/tmp/siq-native-integrity", HERMES_HOME="/tmp/siq-native-integrity/hermes",
                  HERMES_RELAY_ENABLED="false", TERMINAL_ENV="local")
Path(os.environ["HERMES_HOME"]).mkdir(mode=0o700, parents=True)

import siq_native_runtime as native
from model_tools import handle_function_call
from siq_native_runtime.native_bootstrap import ImageBootstrap
from siq_native_runtime.native_dispatch import DispatchError
from tools import skills_tool

skills_tool.SKILLS_DIR = Path("/opt/siq/native-business/skills")
agent, namespace, session = sys.argv[1:]
bootstrap = ImageBootstrap(agent, namespace, "/tmp/siq-native-integrity/channel")
root = Path("/sandbox/native-business")
root.mkdir(mode=0o700)
print(json.dumps({"native_probe_ready": True, "files": [], **bootstrap.ready()}), flush=True)
bootstrap.configure(timeout=60)
checks, attempts = {}, []


def stage(name):
    print(json.dumps({"integrity_stage": name}), flush=True)
    deadline = time.monotonic() + 35
    while not (root / (name + ".continue")).exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("integrity_operator_timeout")
        time.sleep(.05)


def dispatch(name, path):
    value = json.loads(handle_function_call("write_file", {"path": str(path), "content": name},
                      task_id="integrity-task", session_id=session, tool_call_id=name))
    return "error" not in value


try:
    with native.task_scope("integrity-task", session):
        loaded = json.loads(handle_function_call("skill_view", {"name": "writer"},
                           task_id="integrity-task", session_id=session, tool_call_id="integrity-load"))
        checks["actual_writer_skill_loaded"] = loaded.get("success") is True
        checks["allowed_write_before_attempts"] = dispatch("integrity-before", root / "before.txt")
        for name in ("siq_native_runtime/native_dispatch.py", "manifest.json"):
            path = Path("/opt/hermes-agent") / name
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            for operation in ("write", "delete", "replace"):
                replacement = root / "synthetic-replacement"
                replacement.write_text("untrusted replacement")
                refused = False
                try:
                    if operation == "write":
                        with path.open("ab") as target:
                            target.write(b"\n# unexpected modification\n")
                    elif operation == "delete":
                        path.unlink()
                    else:
                        os.replace(replacement, path)
                except OSError as error:
                    refused = error.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
                finally:
                    replacement.unlink(missing_ok=True)
                stable = path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == before
                attempts.append({"target": name, "operation": operation, "refused": refused, "unchanged": stable})
        checks["runtime_cannot_mutate_hook_or_manifest"] = all(a["refused"] and a["unchanged"] for a in attempts)
        checks["allowed_write_after_refused_mutations"] = dispatch("integrity-after-attempts", root / "after-attempts.txt")
        stage("before-drift")
        checks["code_drift_refuses_actual_write"] = not dispatch("integrity-drift", root / "drift-denied.txt")
        stage("after-drift")
        checks["restored_bytes_do_not_revive_runtime"] = not dispatch("integrity-restored", root / "restored-denied.txt")
except DispatchError:
    checks["terminal_context_cleanup_refused"] = True
checks["no_denied_file_effect"] = not any((root / n).exists() for n in ("drift-denied.txt", "restored-denied.txt"))
# Required keys are checked independently by the outer host; no vacuous pass.
print(json.dumps({"integrity_result": True, "checks": checks, "attempts": attempts}), flush=True)
time.sleep(30)
