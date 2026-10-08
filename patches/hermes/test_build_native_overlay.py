"""The native overlay must reject host routes before dispatch side effects."""

import importlib.util
import unittest
from pathlib import Path


def load_builder():
    path = Path(__file__).with_name("build_native_overlay.py")
    spec = importlib.util.spec_from_file_location("build_native_overlay", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OverlayDispatchOrderTest(unittest.TestCase):
    def test_unmapped_tool_is_authorized_before_unknown_result(self):
        source = (
            "class Registry:\n"
            "    def dispatch(self, name, args, **kwargs):\n"
            "        entry = self.get_entry(name, scope=scope)\n"
            "        if not entry:\n"
            '            return tool_error(f"Unknown tool: {name}")\n'
            "        try:\n"
            "            if entry.is_async:\n"
            "                from model_tools import _run_async\n"
            "                result = _run_async(entry.handler(args, **kwargs))\n"
            "            else:\n"
            "                result = entry.handler(args, **kwargs)\n"
            "            return self._normalize_handler_result(name, result)\n"
            "        except Exception:\n"
            "            return tool_error('failed')\n"
        )
        transformed = load_builder().transform("tools/registry.py", source)
        allow = transformed.index("with call_scope(")
        unknown = transformed.index('return tool_error(f"Unknown tool: {name}")')
        handler = transformed.index("entry.handler(checked_args, **kwargs)")
        self.assertLess(allow, unknown)
        self.assertLess(unknown, handler)
        self.assertEqual(transformed.count("if not entry:"), 1)
    def test_host_route_gate_precedes_hooks_checkpoints_and_execute(self):
        source = (
            "def outer():\n"
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
            "            pass\n"
            "\n"
            "    def _authorized_dispatch(final_args: dict[str, Any]) -> Any:\n"
            "        with dispatch_lock:\n"
            "            _begin_tool_execution(agent)\n"
            "        try:\n"
            "            return execute(final_args)\n"
            "        finally:\n"
            "            _hb_stop.set()\n"
        )
        transformed = load_builder().transform("agent/tool_executor.py", source)
        gate = transformed.index("require_registry_dispatch(agent, function_name)")
        begin = transformed.index("_begin_tool_execution(agent)")
        callback = transformed.index("def _checkpoint_after_allow")
        checkpoint = transformed.index('if function_name in {"write_file", "patch"}')
        allow = transformed.index("with after_allow(_checkpoint_after_allow)")
        execute = transformed.index("return execute(final_args)")
        self.assertLess(gate, transformed.index("with dispatch_lock"))
        self.assertLess(gate, begin)
        self.assertLess(begin, callback)
        self.assertLess(callback, checkpoint)
        self.assertLess(checkpoint, allow)
        self.assertLess(allow, execute)
        self.assertEqual(transformed.count('if function_name in {"write_file", "patch"}'), 1)
        self.assertEqual(transformed.count("_ensure_file_checkpoint("), 1)


if __name__ == "__main__":
    unittest.main()
