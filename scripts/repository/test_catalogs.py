import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

import catalogs


class CatalogTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'evidence.json').write_text('{"checks": [{"passed": true}, {"passed": false}]}')
        self.proof = {'path': 'evidence.json', 'sha256': hashlib.sha256((self.root / 'evidence.json').read_bytes()).hexdigest()}
        self.record = {'id': 'run', 'kind': 'release-package', 'relationship': 'maintainer',
                       'implementation_candidate': {'identity': 'fixture', 'source_sha': None, 'dirty': 'not_recorded'},
                       'environment': dict.fromkeys(('os', 'arch', 'host_mode', 'model_mode'), 'not_recorded'),
                       'results': [{'metric': 'package_checks_passed', 'value': 1, 'total': 2}],
                       'limits': ['fixture'], 'failure_and_rerun_record': 'original retained',
                       'review_status': 'indexed_existing_evidence', 'evidence': [self.proof]}

    def document(self, record=None):
        return {'schema_version': 'siq-evaluation-catalog/v1', 'records': [record or self.record]}

    def test_original_partial_result_and_unknown_candidate_allowed(self):
        self.assertEqual(catalogs.evaluations(self.root, self.document()), 1)

    def test_missing_candidate_duplicate_ids_bad_denominator_and_false_pass_rejected(self):
        for change in ('candidate', 'denominator', 'false_pass', 'independent', 'digest'):
            row = copy.deepcopy(self.record)
            if change == 'candidate':
                row['implementation_candidate'] = {}
            elif change == 'denominator':
                row['results'][0]['total'] = 0
            elif change == 'false_pass':
                row['results'][0]['value'] = 2
            elif change == 'independent':
                row['kind'] = 'external-reproduction'
            else:
                row['evidence'][0]['sha256'] = '0' * 64
            with self.subTest(change=change), self.assertRaises(ValueError):
                catalogs.evaluations(self.root, self.document(row))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            catalogs.evaluations(self.root, {'schema_version': 'siq-evaluation-catalog/v1',
                                            'records': [self.record, self.record]})

    def test_literature_unverified_inventory_does_not_claim_rights_or_reading(self):
        row = {**self.proof, 'id': 'paper', 'bytes': (self.root / 'evidence.json').stat().st_size,
               'rights_status': 'not_reviewed', 'reading_status': 'not_recorded', 'title_verified': False}
        doc = {'schema_version': 'siq-literature-catalog/v1', 'records': [row]}
        self.assertEqual(catalogs.literature(self.root, doc), 1)
        row['rights_status'] = 'confirmed'
        with self.assertRaisesRegex(ValueError, 'basis'):
            catalogs.literature(self.root, doc)
        row['rights_status'] = 'not_reviewed'
        row['reading_status'] = 'reproduced'
        with self.assertRaisesRegex(ValueError, 'reading claim'):
            catalogs.literature(self.root, doc)


if __name__ == '__main__':
    unittest.main()
