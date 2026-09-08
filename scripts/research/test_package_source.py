import json
import shutil
import tempfile
import unittest
from pathlib import Path

from package_source import ROOT, license_inventory, safe_file


class SourcePackageTests(unittest.TestCase):
    def test_current_license_inventory_and_missing_notice(self):
        inventory = license_inventory(ROOT)
        self.assertIn("LICENSE", inventory)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = set(inventory)
            sources = json.loads((ROOT / "docs/research/third-party-source-inventory.json").read_text())
            dependencies = json.loads((ROOT / "docs/research/third-party-dependency-inventory.json").read_text())
            names.add(sources["mermaid"]["path"])
            names.update(dependencies["lockfiles"])
            names.update(item["path"] for item in sources["patches"])
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, path)
            self.assertEqual(license_inventory(root), inventory)
            (root / "site/vendor/mermaid-LICENSE").unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                license_inventory(root)

    def test_escaping_and_symlinked_license_paths_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "invalid source path"):
                safe_file(root, "../LICENSE")
            (root / "LICENSE").symlink_to(ROOT / "LICENSE")
            with self.assertRaisesRegex(ValueError, "nonregular"):
                safe_file(root, "LICENSE")

    def test_inventory_fails_if_audited_bundle_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in license_inventory(ROOT):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, path)
            p = root / "site/vendor/mermaid-11.4.1.min.js"
            p.write_text("changed vendor input")
            with self.assertRaisesRegex(ValueError, "differs from audited"):
                license_inventory(root)


if __name__ == "__main__":
    unittest.main()
