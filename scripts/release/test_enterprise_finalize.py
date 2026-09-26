import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import enterprise_candidate
import enterprise_finalize as finalize
import package


class EnterpriseFinalizeTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        candidate = self.root / "candidate"
        candidate.mkdir()
        artifacts = []
        for name, filename in (("edge-agent", "edge-agent"), ("directory", "directory-connector")):
            relative = f"bin/arm64/{filename}"
            path = candidate / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"inert fixture binary, never execute")
            path.chmod(0o755)
            artifacts.append({"id": name, "os": "linux", "arch": "arm64", "path": relative,
                              "sha256": package.digest(path), "bytes": path.stat().st_size})
        for relative in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "LICENSES/fixture.txt"):
            path = candidate / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text("synthetic license fixture")
        envelope = {"schema_version": "enterprise-release/v1", "product": "siq-agent-security-enterprise",
                    "source_commit": "a" * 40, "version": "1.2.3", "artifacts": artifacts,
                    "signed_by": enterprise_candidate.PUBLISHER_PUBLIC_KEY}
        (candidate / "publisher-signing-input.json").write_text(
            json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        envelope["signature"] = "0" * 128  # Deliberately invalid; not a release signature.
        release = self.root / "signed.json"
        release.write_text(json.dumps(envelope))
        verifier = self.root / "verifier"
        verifier.write_bytes(b"not executable; mocked only in assembly unit tests")
        self.args = Namespace(candidate_dir=candidate, release=release, verifier=verifier,
                              verifier_sha256=package.digest(verifier), source_sha="a" * 40,
                              version="1.2.3", out_dir=self.root / "output")

    def test_assembly_with_mocked_verification_preserves_bytes(self):
        # Tests assembly mechanics ONLY, not publisher verification.
        with patch.object(finalize, "verify") as verify:
            info = finalize.finalize(self.args)
        self.assertEqual(verify.call_count, 2)
        self.assertFalse(info["published"])
        self.assertFalse(info["installed"])
        self.assertEqual(info["installation_acceptance"], "not_run")
        archive, = self.args.out_dir.glob("*-bundle.zip")
        prefix = "siq-agent-security-enterprise-1.2.3/"
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(bundle.read(prefix + "release.json"), self.args.release.read_bytes())
            self.assertNotIn(prefix + "CANDIDATE.json", bundle.namelist())
            for artifact in json.loads(self.args.release.read_text())["artifacts"]:
                raw = bundle.read(prefix + artifact["path"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact["sha256"])
        self.assertFalse((self.args.candidate_dir / "release.json").exists())

    def test_independent_verifier_failure_never_creates_output(self):
        with (patch.object(finalize, "verify", side_effect=ValueError("verification failed")),
              self.assertRaises(ValueError)):
            finalize.finalize(self.args)
        self.assertFalse(self.args.out_dir.exists())

    def test_staged_verification_failure_never_creates_output(self):
        with (patch.object(finalize, "verify", side_effect=[None, ValueError("staged verification failed")]) as verify,
              self.assertRaisesRegex(ValueError, "staged verification failed")):
            finalize.finalize(self.args)
        self.assertEqual(verify.call_count, 2)
        self.assertFalse(self.args.out_dir.exists())

    def test_verifier_report_requires_exact_types_identity_and_success(self):
        expected = {"schema_version": "enterprise-release-verification/v1", "version": "1.2.3",
                    "source_commit": "a" * 40, "manifest_sha256": "b" * 64,
                    "publisher_signature_verified": True, "artifact_bytes_verified": True, "installed": False}
        valid = json.dumps(expected).encode()
        cases = [(0, valid, True), (1, valid, False), (0, b"x" * 8193, False),
                 (0, b"[]", False), (0, b"not json", False),
                 (0, valid[:-1] + b', "installed": false}', False)]
        for key, value in (("version", "1.2.4"), ("source_commit", "c" * 40),
                           ("manifest_sha256", "d" * 64), ("installed", True),
                           ("publisher_signature_verified", 1), ("artifact_bytes_verified", False),
                           ("installed", 0), ("extra", "unexpected")):
            cases.append((0, json.dumps({**expected, key: value}).encode(), False))
        for code, raw, accepted in cases:
            with self.subTest(code=code, raw=raw[:120]), patch.object(
                finalize.subprocess, "run", return_value=subprocess.CompletedProcess([], code, raw, b""),
            ):
                if accepted:
                    finalize.verify("verifier", "manifest", "bundle", expected)
                else:
                    with self.assertRaises(ValueError):
                        finalize.verify("verifier", "manifest", "bundle", expected)

    def test_verifier_pin_identity_and_existing_output_rejected(self):
        for field, value in (("verifier_sha256", "0" * 64), ("source_sha", "b" * 40), ("version", "1.2.4")):
            old = getattr(self.args, field)
            setattr(self.args, field, value)
            with patch.object(finalize, "verify") as verify, self.assertRaises(ValueError):
                finalize.finalize(self.args)
            verify.assert_not_called()
            setattr(self.args, field, old)
        self.args.out_dir.mkdir()
        with patch.object(finalize, "verify") as verify, self.assertRaises(ValueError):
            finalize.finalize(self.args)
        verify.assert_not_called()

    def test_changed_copy_rejected_even_after_initial_verifier_success(self):
        def tamper(*args):
            (self.args.candidate_dir / "bin/arm64/edge-agent").write_bytes(b"changed")
        with patch.object(finalize, "verify", side_effect=tamper), self.assertRaises(ValueError):
            finalize.finalize(self.args)
        self.assertFalse(self.args.out_dir.exists())

    def test_regular_reader_rejects_links_and_fifo(self):
        for name in ("symlink", "hardlink", "fifo"):
            target = self.root / name
            if name == "symlink":
                target.symlink_to(self.args.release)
            elif name == "hardlink":
                os.link(self.args.release, target)
            else:
                os.mkfifo(target, 0o600)
            with self.assertRaises((ValueError, OSError)):
                finalize.read_regular(target, 2 << 20)

    def test_actual_edge_rejects_forged_publisher_without_output(self):
        # Build a real verifier at a fresh path, not over the inert mock fixture.
        self.args.verifier = self.root / "native-verifier"
        package.run(["go", "build", "-mod=readonly", "-buildvcs=false", "-trimpath", "-o", self.args.verifier, "."],
                    cwd=package.ROOT / "edge/agent", env=enterprise_candidate.build_env(), phase="test verifier build")
        self.args.verifier_sha256 = package.digest(self.args.verifier)
        with self.assertRaisesRegex(ValueError, "verification failed"):
            finalize.finalize(self.args)
        self.assertFalse(self.args.out_dir.exists())


if __name__ == "__main__":
    unittest.main()
