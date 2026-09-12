import base64
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import skills_distribution_smoke as smoke


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for name, content, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(content) if kind == tarfile.REGTYPE else 0
            member.mode = 0o755
            if kind == tarfile.SYMTYPE:
                member.linkname = "../../outside"
            bundle.addfile(member, io.BytesIO(content))
    return output.getvalue()


class SkillsSmokeTests(unittest.TestCase):
    def test_archive_digest_mismatch_rejected(self):
        data = b"exact downloaded bytes"
        pin = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        }
        smoke.verify_download(data, pin)
        with self.assertRaisesRegex(ValueError, "digest"):
            smoke.verify_download(data + b"tampered", pin)
        pin["integrity"] = "sha512-" + base64.b64encode(bytes(64)).decode()
        with self.assertRaisesRegex(ValueError, "integrity"):
            smoke.verify_download(data, pin)

    def test_extract_preserves_bytes_and_executable_mode(self):
        data = archive([("package/bin/cli.mjs", b"do not execute", tarfile.REGTYPE)])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "package"
            smoke.extract_archive(data, target, "package")
            self.assertEqual((target / "bin/cli.mjs").read_bytes(), b"do not execute")

    def test_archive_escape_link_special_and_duplicate_rejected(self):
        cases = [
            [("package/../../escape", b"bad", tarfile.REGTYPE)],
            [("/absolute", b"bad", tarfile.REGTYPE)],
            [("package/C:/escape", b"bad", tarfile.REGTYPE)],
            [("package/back\\slash", b"bad", tarfile.REGTYPE)],
            [("package/link", b"", tarfile.SYMTYPE)],
            [("package/fifo", b"", tarfile.FIFOTYPE)],
            [("package/a", b"a", tarfile.REGTYPE), ("package/a", b"b", tarfile.REGTYPE)],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    smoke.extract_archive(archive(entries), Path(directory) / "out", "package")

    def test_archive_extraction_budget(self):
        data = archive([("package/a", b"1234", tarfile.REGTYPE)])
        with tempfile.TemporaryDirectory() as directory:
            smoke.extract_archive(data, Path(directory) / "exact", "package", max_bytes=4)
            with self.assertRaisesRegex(ValueError, "limit"):
                smoke.extract_archive(data, Path(directory) / "over", "package", max_bytes=3)

    def test_environment_drops_secrets_and_runtime_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"GITHUB_TOKEN": "secret", "NODE_OPTIONS": "--require evil",
                                            "HOME": "real-home", "CODEX_HOME": "real-codex"}):
                env = smoke.child_environment(Path(directory))
            for name in ("GITHUB_TOKEN", "NODE_OPTIONS", "HOME", "CODEX_HOME"):
                self.assertNotIn(name, env)
            self.assertEqual(env["DO_NOT_TRACK"], "1")
            self.assertEqual(env["DISABLE_TELEMETRY"], "1")
            self.assertEqual(env["SIQ_SKILLS_TEST_HOME"], str(Path(directory) / "home"))

    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_version_probe_ignores_inherited_node_options(self):
        with patch.dict("os.environ", {"NODE_OPTIONS": "--definitely-unsupported-siq-option"}):
            version = smoke.node_version(shutil.which("node"))
        self.assertRegex(version, r"^v\d+\.\d+\.\d+$")

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "run"
            smoke.prepare_output(target)
            (target / "result.json").write_text("previous evidence")
            with self.assertRaises(FileExistsError):
                smoke.prepare_output(target)
            self.assertEqual((target / "result.json").read_text(), "previous evidence")

    def test_uninstall_requires_directory_and_lock_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / "skill"
            lock = root / "skills-lock.json"
            lock.write_text('{"version":1,"skills":{}}')
            smoke.verify_removed(installed, lock)
            installed.mkdir()
            with self.assertRaisesRegex(ValueError, "directory"):
                smoke.verify_removed(installed, lock)
            installed.rmdir()
            lock.write_text('{"version":1,"skills":{"siq-agent-security":{}}}')
            with self.assertRaisesRegex(ValueError, "lock"):
                smoke.verify_removed(installed, lock)

    def test_install_json_uses_display_label_and_exact_target(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "skills/siq-agent-security"
            row = {"name": "siq-agent-security", "status": "installed", "agents": ["OpenClaw"],
                   "mode": "copy", "scope": "project", "path": str(installed)}
            smoke.validate_install_rows([row], "openclaw", installed)
            row["path"] = str(installed.parent / "unexpected")
            with self.assertRaisesRegex(ValueError, "placement"):
                smoke.validate_install_rows([row], "openclaw", installed)

    def test_committed_pin_is_exact_and_complete(self):
        pin = smoke.load_pin(smoke.PIN_PATH)
        self.assertEqual(pin["upstream"]["version"], "1.5.26")
        self.assertEqual(len(pin["upstream"]["commit"]), 40)
        names = {item["name"] for item in pin["packages"]}
        self.assertEqual(names, {"skills", "tar", "yaml", "@isaacs/fs-minipass", "chownr",
                                 "minipass", "minizlib", "yallist"})
        invalid = json.loads(json.dumps(pin))
        invalid["packages"][0]["url"] = "https://attacker.invalid/package.tgz"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pin.json"
            path.write_text(json.dumps(invalid))
            with self.assertRaisesRegex(ValueError, "registry"):
                smoke.load_pin(path)

    def test_malformed_pin_preserves_failed_main_report(self):
        for content in ([], {"schema_version": 1, "upstream": {}, "packages": None}):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pin = root / "bad-pin.json"
                pin.write_text(json.dumps(content))
                output = root / "attempt"
                with (patch.object(smoke, "PIN_PATH", pin), patch("sys.argv", ["smoke", "--out-dir", str(output)]),
                      patch("sys.stdout", new_callable=io.StringIO)):
                    self.assertEqual(smoke.main(), 1)
                self.assertEqual(json.loads((output / "result.json").read_text())["result"], "failed")

    def test_output_cannot_be_created_inside_source_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / smoke.SKILL_PATH / "new-report"
            with patch.object(smoke, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "source"):
                    smoke.prepare_output(output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
