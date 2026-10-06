"""A broken preparation step must never silently start an unregistered run."""
import json
from pathlib import Path
import tempfile
import unittest

import research_permissions_run as runner


class FrozenProtocolGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.protocols = self.root / 'protocols'
        self.protocols.mkdir()
        self.research = self.root / 'research'
        self.research.mkdir()
        self.source = self.research / 'probe.py'
        self.source.write_text('owned fixture\n')
        self.batch = 'research-permissions-gate-test'
        self.path = self.protocols / (self.batch + '.json')
        self.document = {'batch': self.batch, 'source_sha256': {
            'benchmarks/third-party/research_permissions_run.py': runner.digest(Path(runner.__file__)),
            str(self.source): runner.digest(self.source)}}

    def save(self):
        self.path.write_text(json.dumps(self.document))

    def test_missing_protocol_rejected(self):
        with self.assertRaisesRegex(ValueError, 'required before live'):
            runner.require_frozen_protocol(self.root, self.batch, self.research)

    def test_exact_freeze_accepted(self):
        self.save()
        self.assertEqual(runner.require_frozen_protocol(self.root, self.batch, self.research),
                         runner.digest(self.path))

    def test_changed_source_rejected(self):
        self.save()
        self.source.write_text('changed fixture\n')
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            runner.require_frozen_protocol(self.root, self.batch, self.research)

    def test_stale_launcher_rejected(self):
        self.document['source_sha256']['benchmarks/third-party/research_permissions_run.py'] = '0' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'launcher is not frozen'):
            runner.require_frozen_protocol(self.root, self.batch, self.research)

    def test_wrong_batch_rejected(self):
        self.document['batch'] = 'another-batch'
        self.save()
        with self.assertRaisesRegex(ValueError, 'identity'):
            runner.require_frozen_protocol(self.root, self.batch, self.research)


if __name__ == '__main__':
    unittest.main()
