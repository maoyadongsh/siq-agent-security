"""Offline validation of the SonarCloud CI configuration boundary."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sonarcloud_config import cloud_parameters


SCRIPT = Path(__file__).with_name("sonarcloud_config.py")
VALID = {"SONAR_ORGANIZATION": "example-org", "SONAR_PROJECT_KEY": "example:project.v1"}


class CloudParametersTests(unittest.TestCase):
    def test_missing_configuration_fails_with_only_field_name(self):
        for field in VALID:
            for value in (None, ""):
                env = VALID.copy()
                if value is None:
                    del env[field]
                else:
                    env[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, f"^{field}$"):
                        cloud_parameters(env)

    def test_rejects_whitespace_control_unicode_and_parameter_injection(self):
        for field in VALID:
            for value in (
                " a", "a ", "a b", "a\t", "a\n", "a\r", "a\x00", "a\x1b",
                "a\u200b", "项目", "a/../b", "a\\b", "a=token", 'a"', "a'",
                "$(id)", "`id`", "a;-Dsonar.host.url=https://evil.invalid", "a" * 256,
            ):
                with self.subTest(field=field, value=repr(value)):
                    with self.assertRaisesRegex(ValueError, f"^{field}$"):
                        cloud_parameters({**VALID, field: value})

    def test_rejects_invalid_region(self):
        for region in ("EU", "US", "asia", "eu\n", " us", "us -X", "us\x00"):
            with self.subTest(region=repr(region)):
                with self.assertRaisesRegex(ValueError, "^SONAR_REGION$"):
                    cloud_parameters({**VALID, "SONAR_REGION": region})

    def test_rejects_nonempty_host_override(self):
        for host in ("https://sonarcloud.io", "https://evil.invalid", "\n"):
            with self.subTest(host=repr(host)):
                with self.assertRaisesRegex(ValueError, "^SONAR_HOST_URL$"):
                    cloud_parameters({**VALID, "SONAR_HOST_URL": host})

    def test_empty_host_matches_unset_github_variable(self):
        self.assertEqual(cloud_parameters({**VALID, "SONAR_HOST_URL": ""}), cloud_parameters(VALID))

    def test_eu_default_and_explicit_eu(self):
        expected = {"organization": "example-org", "project_key": "example:project.v1", "region": ""}
        for extra in ({}, {"SONAR_REGION": ""}, {"SONAR_REGION": "eu"}):
            self.assertEqual(cloud_parameters({**VALID, **extra}), expected)

    def test_us_and_full_supported_identifier_range(self):
        self.assertEqual(
            cloud_parameters({"SONAR_ORGANIZATION": "AZaz09_.:-", "SONAR_PROJECT_KEY": "a" * 255, "SONAR_REGION": "us"}),
            {"organization": "AZaz09_.:-", "project_key": "a" * 255, "region": "us"},
        )

    def test_does_not_read_token(self):
        class GuardedEnvironment(dict):
            def get(self, key, default=None):
                if key == "SONAR_TOKEN":
                    raise AssertionError("Token must not be read")
                return super().get(key, default)

            def __getitem__(self, key):
                if key == "SONAR_TOKEN":
                    raise AssertionError("Token must not be read")
                return super().__getitem__(key)

        env = GuardedEnvironment({**VALID, "SONAR_TOKEN": "never-read-this"})
        self.assertNotIn("never-read-this", json.dumps(cloud_parameters(env)))


class CloudConfigCLITests(unittest.TestCase):
    def run_cli(self, configuration):
        env = {"PATH": os.defpath, **configuration, "SONAR_TOKEN": "token-sentinel-do-not-print"}
        return subprocess.run([sys.executable, str(SCRIPT)], env=env, text=True, capture_output=True, check=False)

    def test_cli_append_output_without_token(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.write_text("existing=value\n", encoding="utf-8")
            result = self.run_cli({**VALID, "SONAR_REGION": "us", "GITHUB_OUTPUT": str(output)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "configuration validated\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual(output.read_text(encoding="utf-8"), "existing=value\norganization=example-org\nproject_key=example:project.v1\nregion=us\n")
            self.assertNotIn("token-sentinel", result.stdout + result.stderr)

    def test_cli_invalid_configuration_preserves_output_and_redacts_value(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.write_text("existing=value\n", encoding="utf-8")
            result = self.run_cli({**VALID, "SONAR_PROJECT_KEY": "secret-invalid-value\ninjected=yes", "GITHUB_OUTPUT": str(output)})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "invalid configuration: SONAR_PROJECT_KEY\n")
            self.assertEqual(output.read_text(encoding="utf-8"), "existing=value\n")
            self.assertNotIn("secret-invalid-value", result.stderr)
            self.assertNotIn("token-sentinel", result.stderr)

    def test_cli_output_write_failure_has_no_success_and_no_path(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli({**VALID, "GITHUB_OUTPUT": str(Path(directory) / "missing" / "output")})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "invalid configuration: GITHUB_OUTPUT\n")
            self.assertNotIn(directory, result.stderr)

    def test_cli_without_github_output_returns_only_nonsecret_parameters(self):
        result = self.run_cli(VALID)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"organization": "example-org", "project_key": "example:project.v1", "region": ""})
        self.assertEqual(result.stderr, "")
        self.assertNotIn("token-sentinel", result.stdout)


if __name__ == "__main__":
    unittest.main()
