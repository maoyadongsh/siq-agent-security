"""Reject fixture path injection before any run allocation or other effects."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from secure_agent.application import SecureApplication
from secure_agent.contracts import AgentError


class ConfidentialPreflightTest(unittest.TestCase):
    def test_invalid_names_rejected_before_allocation_or_authority(self):
        invalid = (
            "", ".", "..", "../outside.txt", "sub/note.txt", "./.env",
            "/tmp/outside.txt", r"..\outside.txt", r"C:\outside.txt",
            r"C:outside.txt", r"\\server\share\note.txt", "contacts.json",
            ".ENV", ".env ", " .env", ".env:stream", "note\x00.txt",
            "note\n.txt", "x" * 4096, None, 1, True, b".env", Path(".env"), [], {},
        )
        with tempfile.TemporaryDirectory(prefix="siq-preflight-") as directory:
            app = object.__new__(SecureApplication)
            app.daemon = SimpleNamespace(directory=Path(directory))
            app.model = SimpleNamespace(calls=[], transitions=[])
            changed, before = Mock(), Mock()
            for trifecta in (False, True):
                for name in invalid:
                    with self.subTest(trifecta=trifecta, name_type=type(name).__name__, name=repr(name)[:80]):
                        # The tripwires stop the old implementation before it
                        # can write even when this regression is run against it.
                        with patch("secure_agent.application.uuid4", side_effect=AssertionError("allocated run")) as allocation, \
                                patch("secure_agent.application.deploy_application_grant", side_effect=AssertionError("issued authority")) as authority:
                            with self.assertRaisesRegex(AgentError, "^confidential_fixture_path_invalid$"):
                                app.run("fixture", repository="fixture/project", question="review", scope=("README.md",),
                                        trifecta=trifecta, confidential_name=name, changed=changed, before_execution=before)
                            allocation.assert_not_called()
                            authority.assert_not_called()
                        self.assertEqual(list(Path(directory).iterdir()), [])
            changed.assert_not_called()
            before.assert_not_called()

    def test_supported_fixture_names_pass_preflight(self):
        # Stop at the first post-validation operation. Full application tests
        # separately exercise both fixtures against a real isolated daemon.
        app = object.__new__(SecureApplication)
        for trifecta in (False, True):
            for name in (".env", "confidential-note.txt"):
                with (
                    self.subTest(trifecta=trifecta, name=name),
                    patch("secure_agent.application.perf_counter", side_effect=RuntimeError("past preflight")),
                    self.assertRaisesRegex(RuntimeError, "^past preflight$"),
                ):
                    app.run("fixture", repository="fixture/project", question="review", scope=("README.md",),
                            trifecta=trifecta, confidential_name=name)
