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
    def test_host_route_gate_precedes_hooks_checkpoints_and_execute(self):
        source = (
            "def outer():\n"
            "    def _authorized_dispatch(final_args: dict[str, Any]) -> Any:\n"
            "        with dispatch_lock:\n"
            "            _begin_tool_execution(agent)\n"
            "            return execute(final_args)\n"
        )
        transformed = load_builder().transform("agent/tool_executor.py", source)
        gate = transformed.index("require_registry_dispatch(agent, function_name)")
        self.assertLess(gate, transformed.index("with dispatch_lock"))
        self.assertLess(gate, transformed.index("_begin_tool_execution"))
        self.assertLess(gate, transformed.index("return execute(final_args)"))


if __name__ == "__main__":
    unittest.main()
