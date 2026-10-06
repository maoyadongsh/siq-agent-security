"""Native model proposal binding uses Go parameter JSON, not receipt JSON."""
import hashlib
import unittest

from verify_native_business import parameter_digest


class ParameterDigestTests(unittest.TestCase):
    def test_shell_redirection_and_unicode(self):
        params = {'command': 'cat < 输入 > 输出 && true\u2028\u2029', 'timeout': 30, 'background': False}
        expected = ('{"background":false,"command":"cat \\u003c 输入 \\u003e 输出 '
                    '\\u0026\\u0026 true\\u2028\\u2029","timeout":30}').encode()
        self.assertEqual(parameter_digest(params), hashlib.sha256(expected).hexdigest())

    def test_literal_escape_is_not_html_character(self):
        self.assertNotEqual(parameter_digest({'x': '\\u003e'}), parameter_digest({'x': '>'}))

    def test_parameter_change_cannot_reuse_digest(self):
        before = {'command': 'cat > /owned/a', 'timeout': 30}
        for changed in ({**before, 'timeout': 31}, {**before, 'command': 'cat > /owned/b'}):
            self.assertNotEqual(parameter_digest(before), parameter_digest(changed))

    def test_unsupported_numbers_fail_closed(self):
        for value in (1.0, float('nan'), 2**53, -2**53):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parameter_digest({'nested': [value]})


if __name__ == '__main__':
    unittest.main()
