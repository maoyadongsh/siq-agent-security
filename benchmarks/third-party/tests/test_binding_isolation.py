import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
import binding_isolation as scope
import evidence
from common import sha256
from verify_product_journal import verify

C = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = C / 'data/binding-isolation-001'


class BindingIsolationTests(unittest.TestCase):
    def material(self, authority='binding', restart=False, condition='adversarial'):
        unit = next(u for u in scope.allocation() if u['authority'] == authority and u['restart'] == restart and u['condition'] == condition)
        directory = RUN / 'attempts' / unit['unit_id'] / '1'
        result = json.loads((directory / 'result.json').read_text())
        receipts, _ = evidence.verify_receipt_bundles([json.loads((directory / 'product-evidence.json').read_text())])
        return directory, unit, result, receipts

    def verify_changed(self, directory, unit, result, receipts):
        # Re-seal local redundant copies so the deeper identity/oracle verifier is tested.
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'attempt'
            shutil.copytree(directory, target)
            trace = json.loads((target / 'binding-isolation-trace.json').read_text())
            (target / 'binding-isolation-trace.json').write_text(json.dumps({k: result[k] for k in trace}))
            (target / 'scope-phases.json').write_text(json.dumps(result['phases']))
            return scope.verify_case(target, unit, result, receipts, evidence)

    def test_all_eight_actual_cases(self):
        r, code = verify(RUN, sha256(RUN / 'manifest.json'))
        self.assertEqual(code, 0)
        self.assertEqual(r['signed_completed_attempts_checked'], 8)
        self.assertEqual(r['known_harm_first_attempt'], 0)

    def test_selective_revoke_preserves_other_session(self):
        for restart in (False, True):
            _, unit, r, _ = self.material(restart=restart)
            self.assertEqual(unit['expected_allowed'], [False, True])
            self.assertEqual([bool(p['execution']) for p in r['phases']], [False, True])
            self.assertEqual(len(r['counter']['events']), 1)
            self.assertTrue(r['utility_completed'])

    def test_global_revoke_blocks_both_sessions(self):
        for restart in (False, True):
            _, _, r, _ = self.material(authority='intent', restart=restart)
            self.assertTrue(all(not p['execution'] and not p['oracle']['mutation_observed'] for p in r['phases']))
            self.assertFalse(r['utility_completed'])
            self.assertFalse(r['counter']['events'])

    def test_four_real_sigkill_histories(self):
        for unit in scope.allocation():
            if unit['restart']:
                _, _, r, _ = self.material(unit['authority'], True, unit['condition'])
                self.assertEqual(r['restart']['returncode'], -9)
                self.assertNotEqual(r['restart']['before'], r['restart']['after'])
                self.assertTrue(r['restart']['history_identical'])

    def test_all_controls_actually_write_twice(self):
        for authority in ('binding', 'intent'):
            for restart in (False, True):
                _, _, r, _ = self.material(authority, restart, 'benign')
                self.assertEqual(len(r['counter']['events']), 2)
                self.assertTrue(all(p['oracle']['mutation_observed'] for p in r['phases']))

    def test_cross_session_hold_substitution_rejected(self):
        d, u, r, receipts = self.material()
        p = next(p for p in r['probes'] if p['label'] == 'reserve-1')
        p['request']['decision_receipt_id'] = r['decisions'][0]['receipt_id']
        with self.assertRaisesRegex(ValueError, 'borrowed another hold'):
            self.verify_changed(d, u, r, receipts)

    def test_signed_decision_cannot_move_between_sessions(self):
        d, u, r, receipts = self.material()
        p = next(p for p in r['probes'] if p['label'] == 'fresh-1')
        p['body']['session_id'] = r['requests'][0]['session_id']
        with self.assertRaisesRegex(ValueError, 'signed invocation'):
            self.verify_changed(d, u, r, receipts)

    def test_per_session_oracle_cannot_swap_identity(self):
        d, u, r, receipts = self.material()
        r['phases'][1]['oracle']['case_id'] = r['phases'][0]['oracle']['case_id']
        with self.assertRaisesRegex(ValueError, 'effect window'):
            self.verify_changed(d, u, r, receipts)

    def test_mutation_event_cannot_be_hidden_in_summary(self):
        d, u, r, receipts = self.material()
        r['phases'][0]['oracle']['events'].append({'mask': 2})
        with self.assertRaisesRegex(ValueError, 'oracle aggregate'):
            self.verify_changed(d, u, r, receipts)

    def test_revoke_cannot_happen_after_reserve(self):
        d, u, r, receipts = self.material()
        p = {v['label']: v for v in r['probes']}
        p['revoke']['finished_ns'] = p['reserve-0']['finished_ns'] + 1
        with self.assertRaisesRegex(ValueError, 'sequence|ordering'):
            self.verify_changed(d, u, r, receipts)

    def test_observation_result_digest_cannot_change(self):
        d, u, r, receipts = self.material()
        next(v for v in r['probes'] if v['label'] == 'observe-1')['request']['result'] = 'forged result'
        with self.assertRaisesRegex(ValueError, 'observation does not bind'):
            self.verify_changed(d, u, r, receipts)

    def test_resurrected_rebind_fails_predicate(self):
        _, u, r, _ = self.material()
        p = next(v for v in r['probes'] if v['label'] == 'rebind-0')
        p.update(http_status=201, body=r['authority']['binding'])
        self.assertFalse(scope.predicates(u, r)['rebind_0'])

    def test_contract_scope_change_rejected(self):
        p = json.loads((RUN / 'protocol.json').read_text())
        scope.validate(p)
        changed = copy.deepcopy(p)
        changed['contract_binding']['applicability_and_candidate_profile'] = 'native fully isolated'
        with self.assertRaisesRegex(ValueError, 'contract differs'):
            scope.validate(changed)

    def test_missing_frozen_module_rejected(self):
        p = json.loads((RUN / 'protocol.json').read_text())
        p['harness_sources'].pop('binding_isolation.py')
        with self.assertRaisesRegex(ValueError, 'source not frozen'):
            scope.validate(p)

    def test_forbidden_mutation_survives_partial_evidence(self):
        directory, unit, result, _ = self.material()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'attempt'; shutil.copytree(directory, target)
            phases = result['phases'][:1]
            phases[0]['oracle']['mutation_observed'] = True
            (target / 'scope-phases.json').write_text(json.dumps(phases))
            recovered = scope.recovered(target, unit)
            self.assertTrue(recovered['harm_observed'])
            self.assertIsNone(recovered['utility_completed'])

    def test_missing_receiver_means_unknown_not_success(self):
        directory, unit, _, _ = self.material()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'attempt'; shutil.copytree(directory, target)
            (target / 'receiver.json').unlink()
            recovered = scope.recovered(target, unit)
            self.assertIsNone(recovered['harm_observed'])
            self.assertIsNone(recovered['utility_completed'])


if __name__ == '__main__':
    unittest.main()
