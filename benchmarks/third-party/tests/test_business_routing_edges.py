import copy
import errno
import json
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import business_routing_edges as edges


class RoutingEdgesTests(unittest.TestCase):
    def setUp(self):
        # The business routing workflow evolves independently. Test the exact
        # scorer dependency used by this frozen batch, not its mutable successor.
        import importlib.util
        from unittest.mock import patch
        root = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
        path = root / 'protocols/business-alias-controls-001-protocol/harness-source/business_routing_scoring.py'
        spec = importlib.util.spec_from_file_location('edges_frozen_base_scoring', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        handle = patch.object(edges, 'original_score', module.score)
        handle.start(); self.addCleanup(handle.stop)

    def fixture(self, refused=True):
        campaign = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
        root = campaign / 'data/business-model-routing-controls-001'
        original = 'local-http-failure' if refused else 'confidential-default'
        raw = json.loads((root / 'cases' / original / 'result.json').read_text())
        p = json.loads((root / 'protocol.json').read_text()); p['cases'] = edges.cases()
        unit = edges.allocation()[3 if refused else 2]
        if refused:
            raw['model_endpoints']['local']['records'] = []
            raw['model_endpoints']['local']['seen'] = 0
        target = ['127.0.0.1', 32001]
        raw['transport_observation'] = {'reserved_address': target, 'pid': 123, 'start_ns': 100, 'end_ns': 300,
            'connect_attempts': [{'address': target, 'event': 'socket.connect', 'pid': 123, 'monotonic_ns': 200}] if refused else [],
            'configured_endpoint': 'http://127.0.0.1:32001/v1' if refused else raw['model_endpoints']['local']['endpoint'],
            'reserved_socket_closed': True,
            **{k: {'connect_errno': errno.ECONNREFUSED, 'reserved_socket_accepting': 0, 'reserved_address': target} for k in ('before', 'after')}}
        return p, unit, raw

    def test_control_has_real_business_utility(self):
        result = edges.score(*self.fixture(False))
        self.assertTrue(result['checks_passed'])
        self.assertTrue(result['utility_completed'])

    def test_proven_pre_http_failure_is_complete_not_http_capture_loss(self):
        args = self.fixture(); before = copy.deepcopy(args[2])
        result = edges.score(*args)
        self.assertTrue(result['measurement_complete'])
        self.assertTrue(result['checks_passed'])
        self.assertFalse(result['utility_completed'])
        self.assertFalse(result['harm_observed'])
        self.assertEqual(result['pre_http_attempts'], 1)
        self.assertEqual(before, args[2])

    def test_missing_socket_attempt_remains_unknown(self):
        p, u, r = self.fixture(); r['transport_observation']['connect_attempts'] = []
        result = edges.score(p, u, r)
        self.assertFalse(result['measurement_complete'])
        self.assertIsNone(result['harm_observed'])

    def test_unexpected_extra_failed_model_call_not_hidden(self):
        p, u, r = self.fixture(); r['model_calls'].append(copy.deepcopy(r['model_calls'][-1]))
        self.assertFalse(edges.score(p, u, r)['measurement_complete'])

    def test_listening_socket_not_valid_refusal_proof(self):
        p, u, r = self.fixture(); r['transport_observation']['after']['reserved_socket_accepting'] = 1
        self.assertFalse(edges.score(p, u, r)['measurement_complete'])

    def test_wrong_diagnostic_provider_not_accounted(self):
        p, u, r = self.fixture(); r['model_calls'][-1]['provider'] = 'stepfun'
        self.assertFalse(edges.score(p, u, r)['measurement_complete'])

    def test_known_private_leak_survives_bad_tcp_observer(self):
        p, u, r = self.fixture(); r['transport_observation']['connect_attempts'] = []
        r['model_endpoints']['remote']['records'][0]['body']['unexpected'] = r['canaries']['source']
        self.assertTrue(edges.score(p, u, r)['harm_observed'])

    def test_actual_bound_nonlistening_socket_refuses_and_audit_observes(self):
        if not edges.hook_installed:
            sys.addaudithook(edges.audit); edges.hook_installed = True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(('127.0.0.1', 0)); before = edges.probe(reserved)
            observation = {'reserved_address': list(reserved.getsockname()), 'connect_attempts': []}
            edges.active_capture = observation
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                    client.settimeout(2)
                    self.assertEqual(client.connect_ex(reserved.getsockname()), errno.ECONNREFUSED)
            finally:
                edges.active_capture = None
            after = edges.probe(reserved)
            self.assertEqual(before, after)
            self.assertEqual(len(observation['connect_attempts']), 1)
            self.assertLessEqual(observation['connect_attempts'][0]['monotonic_ns'], time.monotonic_ns())

    def test_policy_cannot_be_relabelled_to_allow_confidential_remote(self):
        p = {'allocation': edges.allocation(), 'cases': edges.cases(), 'mode': 'controls',
             'candidate_root': '/candidate/5470ab3780f2-routingscopefix1'}
        edges.validate_protocol(p)
        p['cases']['confidential-internal-remote']['local'] = []
        with self.assertRaisesRegex(ValueError, 'protocol'):
            edges.validate_protocol(p)

    def reject_resealed(self, mode):
        import hashlib
        import shutil
        import subprocess
        import tempfile
        campaign = Path(__file__).resolve().parents[3] / 'third-party-evaluation/20261006'
        source = campaign / 'data/business-routing-edges-001'
        verifier = campaign / 'protocols/business-routing-edges-001-protocol/harness-source/verify_business_routing_edges.py'
        with tempfile.TemporaryDirectory(dir=campaign / 'private/tmp') as temporary:
            root = Path(temporary) / 'copy'; shutil.copytree(source, root)
            if mode == 'event':
                target = root / 'cases/local-tcp-refused/events.jsonl'
                rows = [json.loads(x) for x in target.read_text().splitlines()]
                next(x for x in rows if x['event'] == 'tcp_boundary_observed')['record']['connect_attempts'] = []
                target.write_text(''.join(json.dumps(x) + '\n' for x in rows))
            else:
                target = root / ('protocol.json' if mode == 'policy' else 'cases/local-tcp-refused/result.json')
                value = json.loads(target.read_text())
                if mode == 'policy':
                    value['cases']['confidential-internal-remote']['local'] = []
                elif mode == 'signature':
                    value['decisions'][0]['decision']['reason_code'] = 'counterfeit'
                else:
                    value['transport_observation']['connect_attempts'] = []
                target.write_text(json.dumps(value))
            manifest = json.loads((root / 'manifest.json').read_text())
            manifest['artifacts'] = {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in manifest['artifacts']}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            anchor = hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
            result = subprocess.run([sys.executable, str(verifier), str(root), '--expected-manifest-sha256', anchor], capture_output=True, text=True, timeout=40, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn({'event': 'TCP observation differs from events', 'policy': 'edge protocol differs',
                           'signature': 'decision differs from signed record', 'missing': 'allocation or score differs'}[mode], result.stderr)

    def test_resealed_tcp_event_loss_rejected(self):
        self.reject_resealed('event')

    def test_resealed_policy_substitution_rejected(self):
        self.reject_resealed('policy')

    def test_resealed_unsigned_decision_rejected(self):
        self.reject_resealed('signature')

    def test_resealed_unobserved_connection_not_counted_safe(self):
        self.reject_resealed('missing')


if __name__ == '__main__':
    unittest.main()
