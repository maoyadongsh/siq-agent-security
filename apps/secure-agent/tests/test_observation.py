import unittest

from secure_agent.contracts import AgentError
from secure_agent.security import observation_text


class ObservationTest(unittest.TestCase):
    def test_nested_literal_strings_and_keys_survive_json_escaping(self):
        text = observation_text({"items": [{"key": 'secret="synthetic-value"'}, "安全说明"]})
        self.assertIn('secret="synthetic-value"', text)
        self.assertIn("安全说明", text)
        self.assertIn("items", text)

    def test_utf8_limit_is_not_silently_truncated(self):
        with self.assertRaisesRegex(AgentError, "tool_observation_too_large"):
            observation_text({"text": "安" * 10000})
        # Plain ASCII single-leaf serialization length is 3 + 2*n.
        self.assertEqual(len(observation_text("a" * 32766).encode()), 65535)
        with self.assertRaisesRegex(AgentError, "tool_observation_too_large"):
            observation_text("a" * 32767)
