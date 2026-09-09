import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verify_release_assets import verify


class ReleaseAssetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.tag = "research-v0.1.0-rc.1"
        self.source = "a" * 40
        self.archive = f"siq-agent-security-{self.tag}.tar.gz"
        (self.directory / self.archive).write_bytes(b"source fixture")
        archive_hash = hashlib.sha256(b"source fixture").hexdigest()
        (self.directory / "SOURCE-INFO.json").write_text(json.dumps({
            "version": self.tag, "source_sha": self.source,
            "archive": self.archive, "archive_sha256": archive_hash,
        }))
        items = [{"name": name, "sha256": hashlib.sha256((self.directory / name).read_bytes()).hexdigest(),
                  "bytes": (self.directory / name).stat().st_size}
                 for name in [self.archive, "SOURCE-INFO.json"]]
        self.record = {"tag": self.tag, "tag_source_sha": self.source, "fresh_download_verified": items}
        (self.directory / "SHA256SUMS").write_text("".join(f'{i["sha256"]}  {i["name"]}\n' for i in items))

    def check(self):
        return verify(self.directory, self.record, self.tag, self.source)

    def test_original_assets_pass(self):
        self.assertEqual(self.check()["source_sha"], self.source)

    def test_replaced_archive_and_checksum_are_rejected(self):
        (self.directory / self.archive).write_bytes(b"attacker bytes")
        checksum = self.directory / "SHA256SUMS"
        checksum.write_text(checksum.read_text().replace(
            self.record["fresh_download_verified"][0]["sha256"], hashlib.sha256(b"attacker bytes").hexdigest()))
        with self.assertRaisesRegex(ValueError, "asset differs"):
            self.check()

    def test_modified_metadata_is_rejected(self):
        (self.directory / "SOURCE-INFO.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "asset differs"):
            self.check()

    def test_extra_checksum_path_is_rejected(self):
        with (self.directory / "SHA256SUMS").open("a") as stream:
            stream.write("0" * 64 + "  ../../other\n")
        with self.assertRaisesRegex(ValueError, "checksum manifest"):
            self.check()

    def test_moved_tag_is_rejected(self):
        self.source = "b" * 40
        with self.assertRaisesRegex(ValueError, "tag/source"):
            self.check()

    def test_unreviewed_tag_is_rejected(self):
        self.tag = "research-v0.1.0-rc.2"
        with self.assertRaisesRegex(ValueError, "tag/source"):
            self.check()

    def test_symlink_is_rejected(self):
        target = self.directory / self.archive
        target.rename(self.directory / "elsewhere")
        target.symlink_to("elsewhere")
        with self.assertRaisesRegex(ValueError, "nonregular"):
            self.check()


if __name__ == "__main__":
    unittest.main()
