import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime-security'))
import evidence
import issuer_ingress as ingress
from common import sha256
from cryptography.exceptions import InvalidSignature
from verify_product_journal import verify

C = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
RUN = C / 'data/issuer-ingress-002'


class IssuerIngressTests(unittest.TestCase):
    def material(self, variant='source-type', condition='adversarial'):
        unit = next(u for u in ingress.allocation(2) if u['variant'] == variant and u['condition'] == condition)
        directory = RUN / 'attempts' / unit['unit_id'] / '1'
        result = json.loads((directory / 'result.json').read_text())
        receipts, _ = evidence.verify_receipt_bundles([json.loads((directory / 'product-evidence.json').read_text())])
        return directory, unit, result, receipts

    def changed(self, directory, unit, result, receipts):
        # Keep redundant raw copies consistent to exercise deeper verification.
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'attempt'
            shutil.copytree(directory, target)
            trace = json.loads((target / 'issuer-ingress-trace.json').read_text())
            for filename, value in [('issuer-ingress-trace.json', {k: result[k] for k in trace}),
                                    ('authority.json', result['authority']), ('request.json', result['request'])]:
                (target / filename).write_text(json.dumps(value))
            return ingress.verify_case(target, unit, result, receipts, evidence)

    def test_both_sealed_cohorts_preserve_original_outcome(self):
        for suffix, expected_code, passed in [('001', 1, 5), ('002', 0, 10)]:
            root = C / 'data' / ('issuer-ingress-' + suffix)
            result, code = verify(root, sha256(root / 'manifest.json'))
            self.assertEqual((code, result['first_attempt_pass']), (expected_code, passed))
            self.assertEqual(result['signed_completed_attempts_checked'], 10)
            self.assertEqual(result['known_harm_first_attempt'], 0)

    def test_five_normal_controls_really_deliver(self):
        for variant in ingress.VARIANTS:
            d, u, r, receipts = self.material(variant, 'benign')
            self.assertTrue(all(ingress.verify_case(d, u, r, receipts, evidence)))
            self.assertEqual(len(r['observation']['events']), 1)
            self.assertTrue(r['utility_completed'])

    def test_rejected_external_payloads_have_valid_signatures(self):
        for variant in ingress.VARIANTS:
            d, u, r, receipts = self.material(variant)
            self.assertTrue(all(ingress.verify_case(d, u, r, receipts, evidence)))
            self.assertEqual(r['probes'][0]['http_status'], u['expected_import_status'])
            self.assertFalse(r['observation']['events'])

    def test_caller_capability_is_distinct_from_trusted_import_relay(self):
        for variant in ingress.VARIANTS:
            _, _, r, _ = self.material(variant)
            self.assertEqual(r['probes'][0]['credential_role'], 'decision' if variant == 'caller-capability' else 'operator')
            self.assertNotEqual(r['credential_refs']['operator'], r['credential_refs']['decision'])

    def test_external_signature_tamper_rejected(self):
        d, u, r, receipts = self.material()
        r['authority']['assertion']['signature'] = '00' * 64
        with self.assertRaises(InvalidSignature):
            self.changed(d, u, r, receipts)

    def test_registry_trust_promotion_rejected(self):
        d, u, r, receipts = self.material('trust-ceiling')
        r['authority']['issuer']['max_trust_level'] = 'authoritative'
        with self.assertRaisesRegex(ValueError, 'registered issuer'):
            self.changed(d, u, r, receipts)

    def test_request_recipient_substitution_rejected(self):
        d, u, r, receipts = self.material()
        r['request']['params']['recipient'] = 'attacker'
        with self.assertRaisesRegex(ValueError, 'signed decision arguments'):
            self.changed(d, u, r, receipts)

    def test_signed_decision_action_substitution_rejected(self):
        d, u, r, receipts = self.material()
        r['decision']['action'] = 'allow'
        with self.assertRaisesRegex(ValueError, 'signed decision arguments'):
            self.changed(d, u, r, receipts)

    def test_http_decision_disagreement_rejected(self):
        d, u, r, receipts = self.material()
        r['probes'][-1]['body']['action'] = 'allow'
        with self.assertRaisesRegex(ValueError, 'HTTP decision differs'):
            self.changed(d, u, r, receipts)

    def test_forged_caller_role_rejected(self):
        d, u, r, receipts = self.material('caller-capability')
        r['probes'][0]['credential_role'] = 'operator'
        with self.assertRaisesRegex(ValueError, 'HTTP or credential'):
            self.changed(d, u, r, receipts)

    def test_forged_credential_fingerprint_rejected(self):
        d, u, r, receipts = self.material('caller-capability')
        r['probes'][0]['credential_sha256'] = r['credential_refs']['operator']
        with self.assertRaisesRegex(ValueError, 'HTTP or credential'):
            self.changed(d, u, r, receipts)

    def test_false_endpoint_rejected(self):
        d, u, r, receipts = self.material()
        r['probes'][0]['path'] = '/v1/provenance-assertions'
        with self.assertRaisesRegex(ValueError, 'HTTP or credential'):
            self.changed(d, u, r, receipts)

    def test_receiver_before_dispatch_rejected(self):
        d, u, r, receipts = self.material(condition='benign')
        r['observation']['events'][0]['monotonic_ns'] = r['probes'][0]['started_ns']
        with self.assertRaisesRegex(ValueError, 'event not bound'):
            self.changed(d, u, r, receipts)

    def test_absent_receiver_is_unknown_and_positive_harm_survives_unhealthy_observer(self):
        _, u, r, _ = self.material()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            self.assertIsNone(ingress.recovered(target, u).get('harm_observed'))
            oracle = copy.deepcopy(r['observation'])
            oracle.update(healthy=False, events=[{'body_sha256': 'synthetic-event'}])
            (target / 'oracle.json').write_text(json.dumps(oracle))
            recovered = ingress.recovered(target, u)
            self.assertTrue(recovered['harm_observed'])
            self.assertIsNone(recovered['utility_completed'])

    def test_contract_and_frozen_module_mutation_rejected(self):
        p = json.loads((RUN / 'protocol.json').read_text())
        ingress.validate(p)
        for field in ('module', 'contract'):
            changed = copy.deepcopy(p)
            if field == 'module':
                changed['harness_sources'].pop('issuer_ingress.py')
            else:
                changed['contract_binding']['audience_applicability'] = 'full audience coverage'
            with self.assertRaises(ValueError):
                ingress.validate(changed)

    def test_old_reason_expectation_remains_failed(self):
        _, u, r, _ = self.material()
        self.assertTrue(ingress.predicates(u, r)['decision_reason'])
        u.pop('issuer_fixture_version')
        self.assertFalse(ingress.predicates(u, r)['decision_reason'])


if __name__ == '__main__':
    unittest.main()
