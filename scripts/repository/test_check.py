import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check


class NavigationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='repository test 空格 ')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'Some 文件.md').write_text('# Hello, 世界!\n# Hello, 世界!\n<a id="explicit"></a>\n')

    def test_unicode_angle_percent_encoded_nested_and_html_links(self):
        (self.root / 'with(parens).md').write_text('# Target\n')
        doc = self.root / 'README.md'
        doc.write_text('[one](<Some 文件.md#hello-世界>)\n[two](Some%20文件.md#hello-世界-1)\n'
                       '[three](with(parens).md#target)\n<a href="Some%20文件.md#explicit">html</a>\n'
                       '[ref][reference]\n[reference]: <Some 文件.md>\n'
                       '```md\n[ignored](missing.md)\n```\n`[ignored](missing.md)`\n')
        self.assertEqual(check.check_document(self.root, 'README.md'), 6)

    def test_missing_wrong_case_bad_anchor_and_escaping_links_rejected(self):
        for link in ('missing.md', 'some 文件.md', 'Some 文件.md#not-here', '../outside.md',
                     '%2e%2e/outside.md', '/etc/passwd', 'file:///etc/passwd', '//example.com/file'):
            with self.subTest(link=link):
                (self.root / 'README.md').write_text(f'[bad](<{link}>)')
                with self.assertRaises(ValueError):
                    check.check_document(self.root, 'README.md')

    def test_symlink_and_undefined_reference_rejected(self):
        (self.root / 'alias.md').symlink_to(self.root / 'Some 文件.md')
        for text in ('[alias](alias.md)', '[unknown][not-defined]'):
            (self.root / 'README.md').write_text(text)
            with self.assertRaises(ValueError):
                check.check_document(self.root, 'README.md')

    def test_headings_inside_fences_do_not_create_anchors(self):
        self.assertEqual(check.anchors('# A\n~~~\n# Hidden\n~~~\n# A\n'), {'a', 'a-1'})


class MapTest(unittest.TestCase):
    def test_duplicate_ids_unclassified_paths_and_private_outputs_rejected(self):
        entry = {'id': 'index', 'paths': ['evaluations/'], 'kind': 'index', 'owner_role': 'maintainer',
                 'strategy': 'index', 'consumers': ['README'], 'license': 'LICENSE', 'validation': ['check']}
        data = {'schema_version': 'siq-repository-map/v1', 'assets': [entry], 'changes': []}
        for name in ('unknown/file.md', 'evaluations/a-private/result.json', 'evaluations/state/config.json',
                     'evaluations/key.seed', 'evaluations/token'):
            with self.subTest(name=name), patch.object(check, 'files', return_value=[name]):
                with self.assertRaises(ValueError):
                    check.validate_map(Path('.'), data)
        with patch.object(check, 'files', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                check.validate_map(Path('.'), {**data, 'assets': [entry, entry]})


class FrozenTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='repository frozen ')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.root / 'docs/evidence').mkdir(parents=True)
        (self.root / 'docs/research').mkdir()
        (self.root / 'docs/evidence/result.json').write_text('{"failed": true}\n')
        (self.root / 'docs/research/claims-evidence.json').write_text('{"claims": []}\n')
        self.commit()
        self.base = self.git('rev-parse', 'HEAD').strip()
        self.policy = {'baseline': self.base, 'prefixes': ['docs/evidence/'], 'paths': []}

    def git(self, *args):
        return check.git(self.root, *args).decode()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def test_new_evidence_allowed_but_old_modification_deletion_rejected(self):
        check.check_frozen(self.root, self.policy, self.base)
        (self.root / 'docs/evidence/new.json').write_text('{}')
        check.check_frozen(self.root, self.policy, self.base)
        (self.root / 'docs/evidence/result.json').write_text('{"passed": true}')
        with self.assertRaisesRegex(ValueError, 'frozen content changed'):
            check.check_frozen(self.root, self.policy, self.base)
        (self.root / 'docs/evidence/result.json').unlink()
        with self.assertRaisesRegex(ValueError, 'frozen content changed'):
            check.check_frozen(self.root, self.policy, self.base)

    def test_base_policy_cannot_be_weakened_or_rebased(self):
        path = self.root / check.MAP
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'frozen': self.policy}))
        self.commit()
        current = self.git('rev-parse', 'HEAD').strip()
        for policy in ({**self.policy, 'prefixes': []}, {**self.policy, 'baseline': current}):
            with self.assertRaises(ValueError):
                check.check_frozen(self.root, policy, current)

    def test_evidence_added_since_initial_baseline_protected_by_pr_base(self):
        (self.root / 'docs/evidence/later.json').write_text('{}')
        self.commit()
        current = self.git('rev-parse', 'HEAD').strip()
        (self.root / 'docs/evidence/later.json').write_text('{"changed": true}')
        with self.assertRaisesRegex(ValueError, 'frozen content changed'):
            check.check_frozen(self.root, self.policy, current)

    def test_unknown_git_base_fails_closed(self):
        with self.assertRaises(subprocess.CalledProcessError):
            check.check_frozen(self.root, self.policy, 'f' * 40)


if __name__ == '__main__':
    unittest.main()
