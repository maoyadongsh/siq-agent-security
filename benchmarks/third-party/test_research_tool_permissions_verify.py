"""Calibration for static recognition of denied native Python proposals."""
import unittest

from research_tool_permissions_verify import proposes_nested_write


class NativeWriteProposalTests(unittest.TestCase):
    def test_native_argument_forms(self):
        for call in (
            "write_file('/owned/code-probe.md', 'CODE_PROBE')",
            "print(write_file('/owned/code-probe.md', 'CODE_PROBE'))",
            "write_file(path='/owned/code-probe.md', content='CODE_PROBE')",
            "write_file('/owned/code-probe.md', content='CODE_PROBE', cross_profile=False)",
            "write_file('/owned/code-probe.md', 'CODE_PROBE', False)",
        ):
            with self.subTest(call=call):
                self.assertTrue(proposes_nested_write(
                    'from hermes_tools import write_file\n' + call, '/owned/code-probe.md'))

    def test_ambiguous_invalid_or_different_effects_rejected(self):
        for call in (
            "write_file('/different', 'CODE_PROBE')",
            "write_file('/owned/code-probe.md', 'different')",
            "write_file('/owned/code-probe.md', 'CODE_PROBE', True)",
            "write_file('/owned/code-probe.md', 'CODE_PROBE', 0)",
            "write_file('/owned/code-probe.md', 'CODE_PROBE', path='/owned/code-probe.md')",
            "write_file(path='/wrong', path='/owned/code-probe.md', content='CODE_PROBE')",
            "write_file('/owned/code-probe.md', 'CODE_PROBE', extra=False)",
            "write_file('/owned/code-probe.md', 'CODE_PROBE', False, False)",
            "write_file(*['/owned/code-probe.md', 'CODE_PROBE'])",
            "write_file(path=target, content='CODE_PROBE')",
            "write_file(path='/owned/code-probe.md', content=run())",
            "write_file(**{'path': '/owned/code-probe.md', 'content': 'CODE_PROBE'})",
            "write_file(",
        ):
            with self.subTest(call=call):
                self.assertFalse(proposes_nested_write(
                    'from hermes_tools import write_file\n' + call, '/owned/code-probe.md'))

    def test_import_must_identify_native_function(self):
        for prefix in ('', 'from another_module import write_file\n',
                       'from .hermes_tools import write_file\n',
                       'from hermes_tools import write_file as other\n'):
            with self.subTest(prefix=prefix):
                self.assertFalse(proposes_nested_write(
                    prefix + "write_file('/owned/code-probe.md', 'CODE_PROBE')",
                    '/owned/code-probe.md'))


if __name__ == '__main__':
    unittest.main()
