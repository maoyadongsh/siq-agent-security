import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secure_agent.contracts import AgentError
from secure_agent.models import (
    OrnithProvider,
    StepFunProvider,
    from_environment,
    private_configuration,
)


class ProviderConfigTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "providers.json"
        self.config = {"schema_version": "hackathon-provider-config/v1", "primary": "stepfun", "backup": "ornith",
            "providers": {"stepfun": {"endpoint": "https://api.stepfun.com/step_plan/v1", "model": "step-3.7-flash",
                                       "api_key": "test-only-placeholder"},
                          "ornith": {"endpoint": "http://127.0.0.1:8006/v1", "model": "local-test", "api_key": ""}}}
        self.path.write_text(json.dumps(self.config))
        self.path.chmod(0o600)
        environment = patch.dict(os.environ, {"SIQ_MODEL_CONFIG": str(self.path)}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_primary_and_explicit_backup_have_separate_identities(self):
        self.assertIsInstance(from_environment(), StepFunProvider)
        with patch.dict(os.environ, {"SIQ_MODEL_PROVIDER": "ornith"}):
            self.assertIsInstance(from_environment(), OrnithProvider)

    def test_partial_environment_never_receives_private_file_key(self):
        with patch.dict(os.environ, {"SIQ_MODEL_PROVIDER": "stepfun",
                "SIQ_STEPFUN_ENDPOINT": "https://other.example/v1", "SIQ_STEPFUN_MODEL": "other-model"}), \
                self.assertRaisesRegex(AgentError, "model_api_key_missing"):
            from_environment()

    def test_complete_environment_is_an_independent_bundle(self):
        with patch.dict(os.environ, {"SIQ_MODEL_PROVIDER": "stepfun",
                "SIQ_STEPFUN_ENDPOINT": "http://127.0.0.1:9999/v1", "SIQ_STEPFUN_MODEL": "test"}):
            provider = from_environment()
            self.assertEqual(provider._key, "")
            self.assertEqual(provider.model, "test")

    def test_group_readable_and_foreign_owned_config_rejected(self):
        self.path.chmod(0o640)
        with self.assertRaisesRegex(AgentError, "model_config_permissions_invalid"):
            from_environment()
        self.path.chmod(0o600)
        with patch("os.getuid", return_value=os.getuid() + 1), \
                self.assertRaisesRegex(AgentError, "model_config_permissions_invalid"):
            private_configuration()

    def test_symlink_and_oversized_config_rejected(self):
        link = self.path.with_name("link")
        link.symlink_to(self.path)
        with patch.dict(os.environ, {"SIQ_MODEL_CONFIG": str(link)}), \
                self.assertRaisesRegex(AgentError, "model_config_unreadable"):
            private_configuration()
        self.path.write_text(" " * 16385)
        with self.assertRaisesRegex(AgentError, "model_config_size_invalid"):
            private_configuration()

    def test_unknown_config_fields_and_nonstring_values_rejected(self):
        self.config["providers"]["stepfun"]["api_key"] = True
        self.path.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(AgentError, "model_config_invalid"):
            private_configuration()
        self.config["providers"]["stepfun"]["api_key"] = "test-only-placeholder"
        self.config["allow"] = True
        self.path.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(AgentError, "contract_fields_invalid"):
            private_configuration()


if __name__ == "__main__":
    unittest.main()
