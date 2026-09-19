import hashlib
import json
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

import readback
import verify


class VerifyReleaseTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='release tests with spaces ')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.version = '0.3.0'
        self.sha = 'a' * 40

    def archive(self, entries):
        path = self.root / 'bundle.zip'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as out:
                for name, mode in entries:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = mode << 16
                    out.writestr(info, b'payload')
        return path

    def test_extract_preserves_executable_fact(self):
        archive = self.archive([('release/run', stat.S_IFREG | 0o755), ('release/doc', stat.S_IFREG | 0o644)])
        out = verify.extract_zip(archive, self.root / 'out', 'release')
        self.assertEqual((out / 'run').read_bytes(), b'payload')
        self.assertTrue((out / 'run').stat().st_mode & 0o111)
        self.assertFalse((out / 'doc').stat().st_mode & 0o111)

    def test_archive_escape_links_duplicates_case_collisions_and_windows_names_rejected(self):
        cases = [[('../escape', stat.S_IFREG | 0o644)], [('/release/file', stat.S_IFREG | 0o644)],
                 [('release/../escape', stat.S_IFREG | 0o644)], [('release/link', stat.S_IFLNK | 0o777)],
                 [('release/a', stat.S_IFREG | 0o644), ('release/A', stat.S_IFREG | 0o644)],
                 [('release/a', stat.S_IFREG | 0o644)] * 2,
                 [('release/CON.txt', stat.S_IFREG | 0o644)], [('release/file:stream', stat.S_IFREG | 0o644)],
                 [('release/file\\escape', stat.S_IFREG | 0o644)], [('release/run', stat.S_IFREG | 0o4755)]]
        for entries in cases:
            with self.subTest(entries=entries):
                archive = self.archive(entries)
                with self.assertRaises(ValueError):
                    verify.extract_zip(archive, self.root / 'never-written', 'release')
                self.assertFalse((self.root / 'never-written').exists())

    def test_archive_size_limit_checked_before_writing(self):
        archive = self.archive([('release/run', stat.S_IFREG | 0o755)])
        with patch.object(verify, 'MAX_ARCHIVE_BYTES', 1), self.assertRaisesRegex(ValueError, 'size limit'):
            verify.extract_zip(archive, self.root / 'never-written', 'release')
        self.assertFalse((self.root / 'never-written').exists())

    def candidate(self):
        directory = self.root / 'assets'
        directory.mkdir()
        for name in verify.assets(self.version):
            (directory / name).write_bytes(b'fixture')
        (directory / 'SOURCE-INFO.json').write_text(json.dumps({'version': self.version,
                                                              'source_sha': self.sha, 'publisher_manifest_verified': True}))
        lines = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
                 for p in sorted(directory.iterdir()) if p.name != 'SHA256SUMS']
        (directory / 'SHA256SUMS').write_text(''.join(lines))
        return directory

    def test_checksum_inventory_tamper_and_source_mismatch_rejected(self):
        directory = self.candidate()
        verify.check_assets(directory, self.version, self.sha)
        with self.assertRaisesRegex(ValueError, 'identity'):
            verify.check_assets(directory, self.version, 'b' * 40)
        sums = directory / 'SHA256SUMS'
        original = sums.read_text()
        sums.write_text(original + original.splitlines()[0] + '\n')
        with self.assertRaises(ValueError):
            verify.check_assets(directory, self.version, self.sha)
        sums.write_text(original)
        (directory / 'siq-agent-security-linux-arm64').write_bytes(b'tampered')
        with patch.object(verify, 'smoke') as smoke:
            with self.assertRaisesRegex(ValueError, 'checksum'):
                verify.verify(directory, self.version, self.sha, native_smoke=True)
            smoke.assert_not_called()

    def test_forged_signature_rejected_by_trusted_verifier(self):
        skill = self.root / 'skill'
        skill.mkdir()
        (skill / 'skill-manifest.json').write_text(json.dumps({'signed_by': verify.public_key(), 'signature': '00' * 64}))
        with self.assertRaisesRegex(ValueError, 'official signature'):
            verify.verify_signature(skill)

    def test_reports_cannot_overwrite_historical_record(self):
        path = self.root / 'report.json'
        verify.write_report(path, {'original': True})
        with self.assertRaises(FileExistsError):
            verify.write_report(path, {'replacement': True})
        self.assertEqual(json.loads(path.read_text()), {'original': True})

    def test_remote_metadata_rejects_wrong_source_tag_draft_or_asset_set(self):
        tag = 'siq-agent-security-v' + self.version
        release = {'tag_name': tag, 'draft': False, 'html_url': f'https://github.com/{readback.REPO}/releases/tag/{tag}',
                   'assets': [{'name': name, 'state': 'uploaded'} for name in verify.assets(self.version)]}
        ref = {'type': 'commit', 'sha': self.sha}
        readback.check_metadata(release, ref, self.version, self.sha)
        for changes in ({'draft': True}, {'tag_name': 'old'}, {'assets': []}):
            with self.assertRaises(ValueError):
                readback.check_metadata({**release, **changes}, ref, self.version, self.sha)
        with self.assertRaises(ValueError):
            readback.check_metadata(release, {**ref, 'sha': 'b' * 40}, self.version, self.sha)


if __name__ == '__main__':
    unittest.main()
