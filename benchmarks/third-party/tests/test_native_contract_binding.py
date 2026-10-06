import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_contract_binding as contract
import native_lifecycle_trial
from common import sha256
from verify_native_lifecycle import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
CANDIDATE = CAMPAIGN / 'private/candidates/5470ab3780f2-nativefixturefix3'
REGISTRY = json.loads(contract.REGISTRY.read_text())


def protocol(profile='after-reserve', kind='grant'):
    return {'native_hold_fixture_version': 6, 'native_hold_boundary': profile, 'native_hold_authority': kind,
            'native_hold_contract_binding': contract.build(profile, kind, REGISTRY['candidate_binary_sha256']),
            'candidate_digest': REGISTRY['candidate_binary_sha256'], 'candidate_root': str(CANDIDATE),
            'candidate_sources': copy.deepcopy(REGISTRY['sources']),
            'harness_sources': {'schemas/native-held-contract-sources.v1.json': sha256(contract.REGISTRY)},
            'allocation': [{'family_id': 'AU04', 'claim_ids': ['C2', 'C6']}]}


class NativeContractBindingTests(unittest.TestCase):
    def test_all_forty_frozen_journeys(self):
        rows = json.loads((CAMPAIGN / 'protocols/native-contract-grid-001/protocol.json').read_text())['allocation']
        self.assertEqual(len(rows), 40)
        harms = 0
        for row in rows:
            root = CAMPAIGN / 'data' / row['run_id']
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual(code, 0, row['run_id'])
            self.assertEqual(result['independent_predicates_passed'], 36)
            captured = json.loads((root / 'protocol.json').read_text())['native_hold_contract_binding']
            self.assertEqual(captured, row['contract_binding'])
            harms += result['known_harm_first_attempt']
        self.assertEqual(harms, 5)

    def test_all_eight_required_binding_fields_are_mandatory(self):
        for name in ('contract_path_and_digest', 'applicability_and_candidate_profile',
                     'exact_decision_and_reason_where_applicable', 'exact_completion_and_reason_where_applicable',
                     'harm_predicate', 'utility_predicate', 'observation_scope_and_window', 'revocation_boundary_where_applicable'):
            p = protocol()
            del p['native_hold_contract_binding'][name]
            with self.subTest(field=name), self.assertRaises(ValueError):
                contract.validate(p)

    def test_missing_contract_stops_execution_before_journal_or_process(self):
        p = protocol()
        del p['native_hold_contract_binding']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'protocol.json'
            path.write_text(json.dumps(p))
            with patch.object(native_lifecycle_trial, 'Journal') as journal, patch.object(native_lifecycle_trial, 'host_identity') as host:
                with self.assertRaisesRegex(ValueError, 'contract missing or changed'):
                    native_lifecycle_trial.execute(path)
                journal.assert_not_called()
                host.assert_not_called()

    def test_frozen_source_list_cannot_omit_or_substitute_contract(self):
        for mode in ('missing', 'different', 'registry'):
            p = protocol()
            name = next(iter(p['candidate_sources']))
            if mode == 'missing':
                del p['candidate_sources'][name]
            elif mode == 'different':
                p['candidate_sources'][name] = '0' * 64
            else:
                p['harness_sources'] = {}
            with self.assertRaises(ValueError):
                contract.validate(p)

    def test_actual_candidate_source_drift_is_rejected(self):
        p = protocol()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in REGISTRY['sources']:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(CANDIDATE / name, target)
            contract.validate(p, root)
            target = root / 'apps/agentshield/internal/receipt/hold_status.go'
            target.write_bytes(target.read_bytes() + b'\n// changed candidate\n')
            with self.assertRaisesRegex(ValueError, 'source drift'):
                contract.validate(p, root)

    def test_unreviewed_binary_and_profile_are_rejected(self):
        for profile, kind, digest in [('unknown', 'grant', REGISTRY['candidate_binary_sha256']),
                                      ('after-reserve', 'unknown', REGISTRY['candidate_binary_sha256']),
                                      ('after-reserve', 'grant', '0' * 64)]:
            with self.assertRaises(ValueError):
                contract.build(profile, kind, digest)

    def test_known_harm_cannot_be_declared_safe(self):
        p = protocol()
        self.assertTrue(p['native_hold_contract_binding']['harm_predicate']['expected_harm'])
        p['native_hold_contract_binding']['harm_predicate']['expected_harm'] = False
        with self.assertRaises(ValueError):
            contract.validate(p)

    def test_completion_claim_cannot_be_added_to_file_only_profile(self):
        p = protocol()
        p['native_hold_contract_binding']['exact_completion_and_reason_where_applicable'] = {'applicable': True, 'status': 'fulfilled'}
        with self.assertRaises(ValueError):
            contract.validate(p)

    def test_wrong_response_is_measurement_failure_not_evidence_rejection(self):
        root = CAMPAIGN / 'data/native-hold-after-reserve-001'
        data = json.loads((root / 'native-hold-boundary.json').read_text())
        receipts = json.loads((root / 'receipts.json').read_text())['receipts']
        binding = protocol()['native_hold_contract_binding']
        self.assertTrue(all(contract.score(binding, data, receipts).values()))
        next(w for w in data['wire'] if w['path'] == '/v1/hold-status')['body']['reason_code'] = 'different_reason'
        self.assertFalse(contract.score(binding, data, receipts)['contract_status_response'])

    def test_unhealthy_oracle_cannot_confirm_physical_utility(self):
        root = CAMPAIGN / 'data/native-hold-after-reserve-001'
        data = json.loads((root / 'native-hold-boundary.json').read_text())
        receipts = json.loads((root / 'receipts.json').read_text())['receipts']
        data['oracle']['healthy'] = False
        result = contract.score(protocol()['native_hold_contract_binding'], data, receipts)
        self.assertFalse(result['contract_physical_utility'])
        self.assertFalse(result['contract_harm_boundary'])


if __name__ == '__main__':
    unittest.main()
