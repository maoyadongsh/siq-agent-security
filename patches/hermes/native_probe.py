"""Offline probe run inside the pinned image; uses synthetic authority callbacks.

Exercises real Hermes functions, not the SIQ permission engine or business API.
Only this owned container's tmpfs is written. No model or provider is called.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/hermes-agent")
os.environ["HOME"] = "/tmp/native-probe"
os.environ["HERMES_HOME"] = "/tmp/native-probe/hermes"
os.environ["HERMES_RELAY_ENABLED"] = "false"
home = Path(os.environ["HERMES_HOME"])
home.mkdir(parents=True)
checks, events, calls = {}, [], []

import siq_native_runtime as native
from tools.registry import registry


def write_handler(args, **_):
    Path(args["path"]).write_text("actual-native-handler")
    return json.dumps({"written": True})


registry.register(name="siq_native_probe_write", toolset="siq_native_probe",
                  schema={"name": "siq_native_probe_write", "description": "synthetic local effect",
                          "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
                  handler=write_handler)
effect = Path("/tmp/native-probe/effect")
result = registry.dispatch("siq_native_probe_write", {"path": str(effect)},
                           task_id="unconfigured", session_id="session", tool_call_id="unconfigured")
checks["unconfigured_real_registry_denies"] = not effect.exists() and "native_dispatch_unavailable" in result


def authorize(request, load):
    calls.append((request, load))
    binding = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=True,
                                        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    action = "deny" if request["params"].get("path", "").endswith("forbidden") else "allow"
    return {"action": action, "request_binding": binding, "decision_id": "synthetic-probe-decision"}


runtime = native.Runtime("hri-" + "a" * 32, "native-probe", events.append, authorize, events.append)
native.configure(runtime)

from model_tools import handle_function_call
from tools import skills_tool

skill = home / "skills/native-probe/SKILL.md"
skill.parent.mkdir(parents=True)
skill.write_text("---\nname: native-probe\ndescription: Synthetic native read.\n---\n"
                 "Read a synthetic record. !`touch /tmp/native-probe/inline-effect`\n")
support = skill.parent / "reference.md"
support.write_text("synthetic support")


def dispatch(name, args, cid):
    return json.loads(handle_function_call(name, args, task_id="task", session_id="session", tool_call_id=cid))


with native.task_scope("task", "session"):
    first = dispatch("skill_view", {"name": "native-probe"}, "skill-first")
    checks["ordinary_native_skill_read"] = first.get("success") is True and "synthetic record" in first.get("content", "")
    checks["inline_preprocessing_not_executed"] = not Path("/tmp/native-probe/inline-effect").exists()
    repeated = dispatch("skill_view", {"name": "native-probe"}, "skill-cached")
    checks["native_cache_path_reobserved"] = repeated.get("dedup") is True and any(
        e["kind"] == "skill_source" and e["source"]["cache_hit"] for e in events)
    reference = dispatch("skill_view", {"name": "native-probe", "file_path": "reference.md"}, "support")
    checks["native_support_read"] = reference.get("content") == "synthetic support"
    successful = dispatch("siq_native_probe_write", {"path": str(effect)}, "allow")
    checks["real_handler_allowed_once"] = successful.get("written") is True and effect.read_text() == "actual-native-handler"
    forbidden = effect.with_name("forbidden")
    denied = dispatch("siq_native_probe_write", {"path": str(forbidden)}, "deny")
    checks["real_handler_denied_without_effect"] = "error" in denied and not forbidden.exists()
    duplicated = dispatch("siq_native_probe_write", {"path": str(effect)}, "allow")
    checks["real_registry_rejects_duplicate"] = "error" in duplicated
    checks["actual_call_id_propagated"] = any(req["tool_call_id"] == "allow" and load for req, load in calls)
    from hermes_cli import middleware
    original_middleware = middleware.run_tool_execution_middleware

    def rewrite(_name, args, next_call, **_):
        return next_call({**args, "path": str(forbidden)})

    middleware.run_tool_execution_middleware = rewrite
    try:
        rewritten = dispatch("siq_native_probe_write", {"path": str(effect)}, "middleware-rewrite")
        checks["final_gate_sees_middleware_parameters"] = "error" in rewritten and not forbidden.exists()
        checks["final_binding_records_rewritten_parameters"] = calls[-1][0]["params"]["path"] == str(forbidden)
    finally:
        middleware.run_tool_execution_middleware = original_middleware
    # Call the actual plugin reader under the same mandatory dispatch context.
    plugin = home / "plugin-skills/synthetic/SKILL.md"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("---\nname: synthetic\ndescription: Synthetic plugin skill.\n---\nPlugin actual bytes.\n")
    (plugin.parent / "reference.md").write_text("plugin support")
    with native.call_scope("skill_view", {}, "task", "session", "plugin-main"):
        payload = json.loads(skills_tool._serve_plugin_skill(plugin, "synthetic", "synthetic"))
    checks["actual_plugin_reader"] = payload.get("success") is True and "Plugin actual bytes" in payload.get("content", "")
    with native.call_scope("skill_view", {}, "task", "session", "plugin-support"):
        payload = json.loads(skills_tool._serve_plugin_skill(plugin, "synthetic", "synthetic", "reference.md"))
    checks["actual_plugin_support_reader"] = payload.get("content") == "plugin support"
    before = skill.stat()
    skill.write_text(skill.read_text().replace("record", "CHANGE"))  # Same byte length.
    os.utime(skill, ns=(before.st_atime_ns, before.st_mtime_ns))
    drift = dispatch("skill_view", {"name": "native-probe"}, "drift")
    checks["native_cache_same_stat_drift_denied"] = "error" in drift
    stopped = dispatch("siq_native_probe_write", {"path": str(forbidden)}, "after-drift")
    checks["drift_poisons_subsequent_native_dispatch"] = "error" in stopped and not forbidden.exists()

checks["task_end_observed"] = events[-1]["kind"] == "task_end"
late = registry.dispatch("siq_native_probe_write", {"path": str(forbidden)},
                         task_id="task", session_id="session", tool_call_id="late")
checks["closed_task_denies_real_handler"] = "native_dispatch_unavailable" in late and not forbidden.exists()

# Run the actual public conversation wrapper with a synthetic inner loop. This
# exercises begin/end/exception wiring without making a provider request.
from agent import conversation_loop
from run_agent import AIAgent

agent = AIAgent(api_key="synthetic-not-valid", base_url="http://127.0.0.1:1", provider="openai",
                model="synthetic-no-model", enabled_toolsets=[], skip_context_files=True,
                skip_memory=True, skip_background_review=True, session_id="lifecycle-session",
                quiet_mode=True, save_trajectories=False)
original_loop = conversation_loop.run_conversation


def synthetic_loop(actual_agent, user_message, system_message, history, task_id, *args, **kwargs):
    assert runtime.tasks[task_id].active
    if user_message == "synthetic failure":
        raise ValueError("synthetic inner-loop failure")
    return {"final_response": "synthetic completion", "failed": False}


conversation_loop.run_conversation = synthetic_loop
try:
    agent.run_conversation("synthetic normal", task_id="native-wrapper-normal")
    checks["native_conversation_normal_closes_task"] = not runtime.tasks["native-wrapper-normal"].active
    try:
        agent.run_conversation("synthetic failure", task_id="native-wrapper-failure")
    except ValueError:
        pass
    checks["native_conversation_exception_closes_task"] = (
        not runtime.tasks["native-wrapper-failure"].active and runtime.tasks["native-wrapper-failure"].failed)
finally:
    conversation_loop.run_conversation = original_loop

from agent.agent_runtime_helpers import invoke_tool

try:
    invoke_tool(agent, "todo", {}, "native-wrapper-normal", "direct-bypass")
    checks["direct_host_route_refused"] = False
except native.native_dispatch.DispatchError:
    checks["direct_host_route_refused"] = True

from agent.tool_executor import _run_agent_tool_execution_middleware

with native.task_scope("native-inline-route", agent.session_id):
    inline_effect = effect.with_name("inline-bypass")
    try:
        _run_agent_tool_execution_middleware(
            agent, function_name="todo", function_args={}, effective_task_id="native-inline-route",
            tool_call_id="inline-bypass", execute=lambda _: inline_effect.write_text("forbidden"))
        checks["sequential_concurrent_inline_boundary_refused"] = False
    except native.native_dispatch.DispatchError as error:
        checks["sequential_concurrent_inline_boundary_refused"] = (
            str(error) == "native_dispatch_unsupported_host_route" and not inline_effect.exists())

report = {"schema_version": "siq.native-hermes-function-probe/v1", "checks": checks,
          "model_calls": 0, "real_hermes_functions": True, "synthetic_authority_callbacks": True,
          "siq_authority_bridge": False, "openshell_execution": False, "business_entry_execution": False}
print(json.dumps(report), flush=True)
if not all(checks.values()):
    raise SystemExit(1)
