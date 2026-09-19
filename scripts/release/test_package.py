import io
import json
import os
import stat
import tarfile
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import package


class ReleasePackageTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def manifest_fixture(self):
        bins = self.root / "bin"
        bins.mkdir()
        artifacts = []
        version = "0.3.0-rc.1"
        for system, arch in package.TARGETS:
            path = bins / package.artifact_name(system, arch)
            path.write_bytes(f"test binary fixture {system}/{arch}".encode())
            artifacts.append({"os": system, "arch": arch, "sha256": package.digest(path),
                              "bytes": path.stat().st_size,
                              "url": f"{package.RELEASE_BASE}{package.NAME}-v{version}/{path.name}"})
        doc = {"manifest_version": 3, "client_compatibility": {"state_profile": "fixture"},
               "state_compatibility": {"reader_version": 2},
               "skill": {"name": package.NAME, "version": version},
               "binary": {"name": package.NAME, "version": version, "artifacts": artifacts}}
        manifest = self.root / "skill-manifest.json"
        manifest.write_text(json.dumps(doc))
        return manifest, bins, version, doc

    def test_missing_seed_fails_before_build_or_output(self):
        args = Namespace(source_sha="a" * 40, version="0.3.0-rc.1", source_root=self.root,
                         out_dir=self.root / ".tmp" / "candidate", sign=True)
        with patch.dict(os.environ, {}, clear=True), patch.object(package, "run") as run:
            with self.assertRaisesRegex(ValueError, "publisher seed unavailable"):
                package.build(args)
            run.assert_not_called()
        self.assertFalse(args.out_dir.exists())

    def test_build_subprocesses_receive_no_runtime_or_release_secrets(self):
        env = {"PATH": "/tools", "SIQ_AGENT_SECURITY_RELEASE_SEED": "private",
               "AGENTSHIELD_RELEASE_SEED": "legacy", "SIQ_AGENT_SECURITY_STATE_DIR": "/daily",
               "AGENTSHIELD_RULEPACK_PUBKEY": "override", "siq_override": "case"}
        self.assertEqual(package.build_env(env), {"PATH": "/tools"})
        self.assertEqual(env["SIQ_AGENT_SECURITY_RELEASE_SEED"], "private")

    def test_source_and_version_cannot_inject_paths_or_build_flags(self):
        package.validate_inputs("a" * 40, "0.3.0-rc.1")
        for sha, version in (("main", "0.3.0"), ("a" * 40, "../release"),
                             ("a" * 40, "0.3.0 -X main.x=y"), ("a" * 40, "03.0.0")):
            with self.assertRaises(ValueError):
                package.validate_inputs(sha, version)

    def test_source_archive_rejects_escape_links_and_private_files(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
                           ("source/link", tarfile.SYMTYPE), ("source/hardlink", tarfile.LNKTYPE),
                           ("source/.env", tarfile.REGTYPE), ("source/key.seed", tarfile.REGTYPE)):
            with self.subTest(name=name):
                archive = self.root / "source.tar"
                with tarfile.open(archive, "w") as bundle:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.linkname = "../outside" if kind != tarfile.REGTYPE else ""
                    info.size = 1 if kind == tarfile.REGTYPE else 0
                    bundle.addfile(info, io.BytesIO(b"x") if info.size else None)
                target = self.root / "extracted"
                with self.assertRaises(ValueError):
                    package.extract_source(archive, target)
                self.assertFalse(target.exists())

    def test_skill_version_changes_only_in_staging_and_old_signature_is_removed(self):
        source = self.root / "source"
        source.mkdir()
        text = "---\nname: siq-agent-security\nversion: 0.2.0\n---\nBody\n"
        (source / "SKILL.md").write_text(text)
        (source / "skill-manifest.json").write_text("historical")
        target = self.root / "staged"
        package.stage_skill(source, target, "0.3.0-rc.1")
        self.assertIn("version: 0.3.0-rc.1", (target / "SKILL.md").read_text())
        self.assertFalse((target / "skill-manifest.json").exists())
        self.assertEqual((source / "SKILL.md").read_text(), text)
        self.assertEqual((source / "skill-manifest.json").read_text(), "historical")

    def test_pin_validation_rejects_tampering_missing_targets_duplicates_and_old_url(self):
        manifest, bins, version, doc = self.manifest_fixture()
        package.verify_pins(manifest, bins, version)
        original = json.dumps(doc)
        for change in ("tamper", "missing", "duplicate", "old_url", "wrong_version", "legacy"):
            with self.subTest(change=change):
                edited = json.loads(original)
                artifacts = edited["binary"]["artifacts"]
                if change == "tamper":
                    artifacts[0]["sha256"] = "0" * 64
                elif change == "missing":
                    artifacts.pop()
                elif change == "duplicate":
                    artifacts[-1] = artifacts[0]
                elif change == "old_url":
                    artifacts[0]["url"] = artifacts[0]["url"].replace(version, "0.2.0")
                elif change == "wrong_version":
                    edited["skill"]["version"] = "0.2.0"
                else:
                    edited["manifest_version"] = 1
                manifest.write_text(json.dumps(edited))
                with self.assertRaises(ValueError):
                    package.verify_pins(manifest, bins, version)
        manifest.write_text(original)
        next(bins.iterdir()).unlink()
        with self.assertRaisesRegex(ValueError, "binary missing"):
            package.verify_pins(manifest, bins, version)

    def test_archive_preserves_binary_modes_and_exact_skill_bytes(self):
        root = self.root / "bundle"
        root.mkdir()
        (root / "binary").write_bytes(b"binary fixture")
        (root / "binary").chmod(0o755)
        (root / "manifest.json").write_bytes(b'{"signed": "exact bytes"}\n')
        archive = self.root / "bundle.zip"
        package.zip_verified(root, archive, "release")
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(bundle.read("release/manifest.json"), (root / "manifest.json").read_bytes())
            self.assertTrue((bundle.getinfo("release/binary").external_attr >> 16) & stat.S_IXUSR)
        with self.assertRaises(FileExistsError):
            package.zip_verified(root, archive, "release")
        (root / "escape").symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, "nonregular"):
            package.zip_verified(root, self.root / "unsafe.zip", "release")

    def test_unsigned_instructions_do_not_claim_installability(self):
        text = package.installation_text("0.3.0-rc.1", False)
        self.assertIn("Bootstrap intentionally refuses", text)
        self.assertIn("not signed installation", text)


if __name__ == "__main__":
    unittest.main()
