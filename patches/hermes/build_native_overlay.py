#!/usr/bin/env python3
"""Build an inert overlay for one pinned Hermes image; never modify the input."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "sha256:fe5bdcebbc09b2099a3b387a675a4e8d879b8491bdc6246d93fbc8abb51e1f02"
SOURCES = {
    "tools/skills_tool.py": "7e258db459eff5906e7a29f1e2c8fc061fbd46aadf5633ac49d1ea5949cfe3e4",
    "tools/registry.py": "f95d011cae75f0426dd77cb1e25df6bebb61a067d795312df297cb877dd616f5",
    "model_tools.py": "5227bfe30f7c3f6eb20d064f648420138031e038d38eac2829d25b749739ad11",
    "run_agent.py": "5b2e7083680e6c728f2306adc73e5f814c444aaa9ff3e3b840206142c67a7149",
    "agent/agent_runtime_helpers.py": "9164dac169ce580d2de3396885c0959c5660620724f01509416ff2136df890e2",
    "agent/tool_executor.py": "5aff6c7e95a280adc5124e7c1f1019b54984b8e7091db48bac35ad5bc2387813",
}


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError("native_overlay_source_shape_changed")
    return text.replace(old, new)


def transform(name, text):
    if name == "tools/skills_tool.py":
        text = replace(text, 'content = skill_md.read_text(encoding="utf-8-sig", errors="replace")\n',
                       'content = __import__("siq_native_runtime").read_skill(skill_md)\n', 2)
        text = replace(text, 'content = target.read_text(encoding="utf-8-sig", errors="replace")',
                       'content = __import__("siq_native_runtime").read_skill(skill_md, target)')
        text = replace(text, 'content = target_file.read_text(encoding="utf-8-sig", errors="replace")',
                       'content = __import__("siq_native_runtime").read_skill(skill_md, target_file)')
        text = replace(text, 'if preprocess:\n', 'if preprocess and __import__("siq_native_runtime").preprocess_allowed():\n', 2)
        text = replace(text, '            try:\n                st = os.stat(src)\n',
                       '            __import__("siq_native_runtime").verify_cache(task_id, src)\n'
                       '            try:\n                st = os.stat(src)\n')
    elif name == "tools/registry.py":
        old = '''        entry = self.get_entry(name, scope=scope)
        if not entry:
            return tool_error(f"Unknown tool: {name}")
        try:
            if entry.is_async:
                from model_tools import _run_async
                result = _run_async(entry.handler(args, **kwargs))
            else:
                result = entry.handler(args, **kwargs)
            return self._normalize_handler_result(name, result)
'''
        new = '''        entry = self.get_entry(name, scope=scope)
        try:
            from siq_native_runtime import call_scope
            native_call_id = kwargs.pop("tool_call_id", None)
            with call_scope(name, args, kwargs.get("task_id"), kwargs.get("session_id"), native_call_id) as checked_args:
                if not entry:
                    return tool_error(f"Unknown tool: {name}")
                if entry.is_async:
                    from model_tools import _run_async
                    result = _run_async(entry.handler(checked_args, **kwargs))
                else:
                    result = entry.handler(checked_args, **kwargs)
                return self._normalize_handler_result(name, result)
'''
        text = replace(text, old, new)
    elif name == "model_tools.py":
        text = replace(text, '                        function_name, next_args,\n                        task_id=task_id,',
                       '                        function_name, next_args,\n                        tool_call_id=tool_call_id,\n                        task_id=task_id,', 2)
    elif name == "run_agent.py":
        text = replace(text, '            with bind_subagent_parent(self), scoped_runtime_main({}):',
                       '            from siq_native_runtime import task_scope\n'
                       '            with bind_subagent_parent(self), scoped_runtime_main({}), task_scope(\n'
                       '                effective_task_id, getattr(self, "session_id", None) or session_id,\n'
                       '                getattr(self, "_parent_session_id", None),\n'
                       '            ):')
    elif name == "agent/agent_runtime_helpers.py":
        text = replace(text, '    if not isinstance(function_args, dict):\n        function_args = {}\n',
                       '    from siq_native_runtime import require_registry_dispatch\n'
                       '    require_registry_dispatch(agent, function_name)\n'
                       '    if not isinstance(function_args, dict):\n        function_args = {}\n')
    elif name == "agent/tool_executor.py":
        # Reject host routes before pre-tool hooks, checkpoints, or execute.
        text = replace(
            text,
            "    def _authorized_dispatch(final_args: dict[str, Any]) -> Any:\n"
            "        with dispatch_lock:\n",
            "    def _authorized_dispatch(final_args: dict[str, Any]) -> Any:\n"
            "        from siq_native_runtime import require_registry_dispatch\n"
            "        require_registry_dispatch(agent, function_name)\n"
            "        with dispatch_lock:\n",
        )
        text = replace(
            text,
            '    if function_name in {"write_file", "patch"} and agent._checkpoint_mgr.enabled:\n'
            "        try:\n"
            "            _ensure_file_checkpoint(\n"
            "                agent,\n"
            "                function_name,\n"
            "                function_args,\n"
            "                effective_task_id,\n"
            "            )\n"
            "        except Exception:\n"
            "            pass\n"
            "\n"
            '    if function_name == "terminal" and agent._checkpoint_mgr.enabled:\n'
            "        try:\n"
            '            command = function_args.get("command", "")\n'
            "            if _is_destructive_command(command):\n"
            '                cwd = function_args.get("workdir") or os.getenv(\n'
            '                    "TERMINAL_CWD", os.getcwd()\n'
            "                )\n"
            "                agent._checkpoint_mgr.ensure_checkpoint(\n"
            '                    cwd, f"before terminal: {command[:60]}"\n'
            "                )\n"
            "        except Exception:\n"
            "            pass\n",
            "    # Checkpoints write only after a native allow.\n",
        )
        text = replace(
            text,
            "        try:\n"
            "            return execute(final_args)\n"
            "        finally:\n",
            "        try:\n"
            "            from siq_native_runtime import after_allow\n"
            "\n"
            "            def _checkpoint_after_allow() -> None:\n"
            "                try:\n"
            '                    if function_name in {"write_file", "patch"} and agent._checkpoint_mgr.enabled:\n'
            "                        _ensure_file_checkpoint(\n"
            "                            agent,\n"
            "                            function_name,\n"
            "                            function_args,\n"
            "                            effective_task_id,\n"
            "                        )\n"
            '                    elif function_name == "terminal" and agent._checkpoint_mgr.enabled:\n'
            '                        command = function_args.get("command", "")\n'
            "                        if _is_destructive_command(command):\n"
            '                            cwd = function_args.get("workdir") or os.getenv(\n'
            '                                "TERMINAL_CWD", os.getcwd()\n'
            "                            )\n"
            "                            agent._checkpoint_mgr.ensure_checkpoint(\n"
            '                                cwd, f"before terminal: {command[:60]}"\n'
            "                            )\n"
            "                except Exception:\n"
            "                    pass\n"
            "\n"
            "            with after_allow(_checkpoint_after_allow):\n"
            "                return execute(final_args)\n"
            "        finally:\n",
        )
    compile(text, name, "exec")
    return text


def build(source, destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError("native_overlay_destination_exists")
    output, hashes = {}, {}
    for name, expected in SOURCES.items():
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1 << 20:
            raise ValueError("native_overlay_source_unavailable")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("native_overlay_source_digest_changed")
        output[name] = transform(name, raw.decode()).encode()
    runtime = ROOT / "adapters/runtime/hermes-agentshield"
    for name in ("native_dispatch.py", "native_source.py", "native_channel.py", "native_online.py", "native_bootstrap.py", "native_gateway.py"):
        raw = (runtime / name).read_bytes()
        compile(raw, name, "exec")
        output["siq_native_runtime/" + name] = raw
    output["siq_native_runtime/__init__.py"] = (
        b"from .native_dispatch import Runtime, configure, task_scope, call_scope, after_allow, read_skill, verify_cache, preprocess_allowed, require_registry_dispatch\n"
    )
    output["hermes-gateway"] = (
        b'import sys\nsys.path.insert(0, "/opt/hermes-agent")\n'
        b'from siq_native_runtime.native_gateway import main\nraise SystemExit(main())\n'
    )
    output["HERMES-LICENSE"] = (Path(__file__).parent / "LICENSE").read_bytes()
    destination.mkdir(mode=0o700)
    try:
        for name, raw in output.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as file:
                file.write(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        manifest = {"schema_version": "siq.native-hermes-overlay/v1", "base_image_id": IMAGE,
                    "source_sha256": SOURCES, "overlay_sha256": hashes,
                    "production_enabled": False, "authority_bridge_connected": False}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest
    except BaseException:
        shutil.rmtree(destination)  # Only the fresh directory created by this build.
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.destination)
