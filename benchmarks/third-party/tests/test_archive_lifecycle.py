import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive import export
from common import sha256, write_json
from verify_models import lifecycle


class ArchiveLifecycleTests(unittest.TestCase):
    def test_replayed_or_reordered_lifecycle_is_rejected(self):
        units = [{"unit_id": "u1"}]
        rows = [{"sequence": i, "event": name, "run_id": "r", "unit_id": "u1", "monotonic_ns": i}
                for i, name in enumerate(("scheduled", "started", "finished"), 1)]
        lifecycle(rows, units)
        for corrupt in ([*rows, rows[-1]], [rows[0], {**rows[1], "event": "finished"}, {**rows[2], "event": "started"}]):
            with self.assertRaises(ValueError):
                lifecycle(corrupt, units)

    def test_secret_in_late_payload_stops_whole_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "export"
            source.mkdir()
            write_json(source / "safe.json", {"synthetic": True})
            write_json(source / "late.json", {"mistake": "test-only-secret"})
            write_json(source / "checksums.json", {n: sha256(source / n) for n in ("safe.json", "late.json")})
            write_json(source / "manifest.json", {"checksums_sha256": sha256(source / "checksums.json")})
            with self.assertRaisesRegex(ValueError, "credential"):
                export(source, destination, [b"test-only-secret"])
            self.assertFalse(destination.exists())
            export(source, destination, [])
            self.assertEqual(json.loads((destination / "safe.json").read_text()), {"synthetic": True})
            (destination / "safe.json").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                export(source, destination, [])


if __name__ == "__main__":
    unittest.main()
