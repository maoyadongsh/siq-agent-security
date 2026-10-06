import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from evaluation_archive import MANIFEST, PREFIX, verify_migration


class EvaluationRelocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for args in [('init', '-q'), ('config', 'user.name', 'Fixture'),
                     ('config', 'user.email', 'fixture@example.invalid'), ('config', 'commit.gpgsign', 'false')]:
            self.git(*args)
        old = self.root / PREFIX / '20261006/data/result.json'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'{"result":"historical"}\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Frozen fixture')
        self.source = self.git('rev-parse', 'HEAD').strip()
        self.target = self.root / 'evaluations/campaigns/20261006/data/result.json'
        self.target.parent.mkdir(parents=True)
        old.rename(self.target)
        old.parent.rmdir(); old.parent.parent.rmdir(); (self.root / PREFIX).rmdir()
        self.manifest = {'schema': 'siq-evaluation-relocation/v1', 'source_commit': self.source,
                         'source_prefix': PREFIX, 'entries': [{
                             'source': PREFIX + '20261006/data/result.json',
                             'destination': self.target.relative_to(self.root).as_posix(),
                             'action': 'move', 'bytes': self.target.stat().st_size,
                             'sha256': hashlib.sha256(self.target.read_bytes()).hexdigest()}]}
        (self.root / MANIFEST).parent.mkdir(parents=True)
        self.save()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True)

    def save(self):
        (self.root / MANIFEST).write_text(json.dumps(self.manifest))

    def verify(self):
        return verify_migration(self.root, self.source)

    def test_exact_relocation(self):
        self.assertEqual(self.verify(), {self.target.relative_to(self.root).as_posix()})

    def test_changed_payload_even_with_rewritten_digest_is_rejected(self):
        self.target.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'relocated bytes changed'):
            self.verify()
        self.manifest['entries'][0].update(bytes=7, sha256=hashlib.sha256(b'changed').hexdigest())
        self.save()
        with self.assertRaisesRegex(ValueError, 'source digest mismatch'):
            self.verify()

    def test_missing_or_duplicate_inventory_is_rejected(self):
        original = self.manifest['entries'][:]
        for entries in ([], original * 2):
            self.manifest['entries'] = entries
            self.save()
            with self.assertRaisesRegex(ValueError, 'incomplete or duplicate'):
                self.verify()

    def test_source_rebinding_and_evidence_retirement_are_rejected(self):
        self.manifest['source_commit'] = '0' * 40
        self.save()
        with self.assertRaisesRegex(ValueError, 'source identity'):
            self.verify()
        self.manifest['source_commit'] = self.source
        self.manifest['entries'][0].update(action='retire', destination=None)
        self.save()
        with self.assertRaisesRegex(ValueError, 'cannot be retired'):
            self.verify()

    def test_old_root_and_symlink_destinations_are_rejected(self):
        (self.root / PREFIX).mkdir()
        with self.assertRaisesRegex(ValueError, 'retired evaluation root'):
            self.verify()
        (self.root / PREFIX).rmdir()
        content = self.target.read_bytes()
        self.target.unlink()
        external = self.root / 'other.json'; external.write_bytes(content)
        self.target.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.verify()

    def test_escaping_target_is_rejected(self):
        self.manifest['entries'][0]['destination'] = 'evaluations/../../outside'
        self.save()
        with self.assertRaisesRegex(ValueError, 'unsafe migration path'):
            self.verify()
