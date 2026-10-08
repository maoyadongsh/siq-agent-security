"""Fixture authentication never ships in the application or targets remote IAM."""
import json
import unittest
from types import SimpleNamespace

from browser_fixture_identity import install_fixture_session


class FixtureIdentityTests(unittest.TestCase):
    def setUp(self):
        self.routes = []
        install_fixture_session(SimpleNamespace(route=lambda pattern, handler: self.routes.append((pattern, handler))))

    def test_route_is_exact_loopback_refresh(self):
        pattern, _ = self.routes[0]
        self.assertIsNotNone(pattern.fullmatch("http://127.0.0.1:5000/api/iam/api/v1/auth/refresh"))
        for url in ["https://iam.example/api/iam/api/v1/auth/refresh",
                    "http://127.0.0.1.evil:5000/api/iam/api/v1/auth/refresh",
                    "http://127.0.0.1:5000/api/v1/policies",
                    "http://127.0.0.1:5000/api/iam/api/v1/auth/login"]:
            self.assertIsNone(pattern.fullmatch(url))

    def test_post_gets_only_synthetic_token(self):
        result = []
        _, handler = self.routes[0]
        handler(SimpleNamespace(
            request=SimpleNamespace(url="http://127.0.0.1:5000/api/iam/api/v1/auth/refresh", method="POST"),
            fulfill=lambda **kwargs: result.append(kwargs), abort=lambda: self.fail("unexpected abort")))
        self.assertEqual(result[0]["status"], 200)
        self.assertEqual(json.loads(result[0]["body"]), {"access_token": "synthetic-browser-fixture-not-a-real-token"})

    def test_wrong_method_aborts(self):
        result = []
        _, handler = self.routes[0]
        handler(SimpleNamespace(
            request=SimpleNamespace(url="http://127.0.0.1:5000/api/iam/api/v1/auth/refresh", method="GET"),
            fulfill=lambda **kwargs: self.fail("unexpected token"), abort=lambda: result.append("aborted")))
        self.assertEqual(result, ["aborted"])


if __name__ == "__main__":
    unittest.main()
