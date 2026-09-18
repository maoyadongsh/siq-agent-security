"""Regression tests for evidence parsing and private runtime material layout."""
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ACCEPTANCE = load('openshell-o05v6-d05-acceptance')
SERVICE = load('openshell-o05v6-d08-service-gateway')
JOURNEY = load('openshell-o05v6-taskexec-journey')
R07 = load('r07-linux-user-journey-smoke')


def status():
    return {'schema_version': 'openshell-task-execution-status/v1',
            'stop': {'remote_stop': 'unsupported', 'remote_stop_confirmed': False,
                     'local_cli_termination': 'requested'}}


class ReviewGuards(unittest.TestCase):
    def test_r07_failure_report_never_serializes_exception_payload(self):
        secret = "Bearer private-token pairing-code raw-response /private/user/file"
        harness = types.SimpleNamespace(
            journey_results=[{"id": "r07_check", "status": "fail", "actual": secret}],
            current_wait={"journey_step": "step5_receipts_deny_row",
                          "wait_target": {"category": "role:row", "state": "visible"}})
        report = R07.failure_diagnostics(RuntimeError(secret), harness)
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("error", report)
        self.assertEqual(report["failed_check_ids"], ["r07_check"])
        self.assertEqual(report["last_wait"], harness.current_wait)
        self.assertEqual(report["error_type"], "RuntimeError")

    def test_r07_failure_before_harness_initialization_is_reportable(self):
        report = R07.failure_diagnostics(ValueError("private configuration"), None)
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"], [])
        self.assertEqual(report["failed_check_ids"], [])
        self.assertIsNone(report["last_wait"])

    def test_k02_rejects_unreachable_probe_before_using_doctor(self):
        journey = object.__new__(JOURNEY.Journey)
        calls = []

        def fake_http(step_id, *_args):
            calls.append(step_id)
            return {'ok': False}

        journey.http = fake_http
        with self.assertRaises(JOURNEY.StepFailure):
            journey.leg_k02()
        self.assertEqual(calls, ['K02a'])

    def test_public_evidence_removes_secrets_and_private_roots_recursively(self):
        doc = {'meta': {'path': '/private/root/evidence/run.json',
                        'token': 'prefix-secret-value-suffix'},
               'steps': [{'detail': 'secret-value at /private/root'}]}
        safe = ACCEPTANCE.public_evidence(
            doc, {'secret-value': 'test-secret'}, [('/private/root', '<root>')])
        self.assertEqual(safe['meta']['path'], '<root>/evidence/run.json')
        self.assertEqual(safe['meta']['token'], 'prefix-<redacted:test-secret>-suffix')
        self.assertEqual(safe['steps'][0]['detail'], '<redacted:test-secret> at <root>')
        self.assertIn('secret-value', doc['meta']['token'])

    def test_receiver_requires_exact_fresh_calibrated_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            recv = ACCEPTANCE.CanaryReceiver('A', Path(tmp) / 'arrivals.jsonl')
            recv.records = [
                {'path': '/host', 'peer': '127.0.0.1'},
                {'path': '/control', 'peer': '172.23.0.5'},
                {'path': '/task', 'peer': '172.23.0.50'},
            ]
            recv.sandbox_peer = '172.23.0.5'
            self.assertEqual(recv.peers_for_path('/control'), ['172.23.0.5'])
            self.assertEqual(recv.count_peer_since('172.23.0.5', 2), 0)
            self.assertEqual(recv.foreign_peers(), ['127.0.0.1', '172.23.0.50'])
            recv.records.append({'path': '/task', 'peer': '172.23.0.5'})
            self.assertEqual(recv.count_peer_since('172.23.0.5', 2), 1)

    def test_both_host_receivers_must_answer_and_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            receivers = tuple(ACCEPTANCE.CanaryReceiver(tag, Path(tmp) / f'{tag}.jsonl')
                              for tag in ('A', 'B'))
            receivers[0].records.append({'path': '/host', 'peer': '127.0.0.1'})
            self.assertFalse(ACCEPTANCE.host_selfcheck_passed([True, False], receivers, '/host'))
            self.assertFalse(ACCEPTANCE.host_selfcheck_passed([True, True], receivers, '/host'))
            receivers[1].records.append({'path': '/host', 'peer': '127.0.0.1'})
            self.assertTrue(ACCEPTANCE.host_selfcheck_passed([True, True], receivers, '/host'))

    def test_sandbox_peer_calibration_requires_same_non_host_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            journey = object.__new__(ACCEPTANCE.AcceptanceJourney)
            journey.run_id = 'fixture'
            journey.ep_a, journey.ep_b = 'host.invalid:1234', 'host.invalid:5678'
            journey.host_selfcheck_path = '/host'
            journey.meta = {'d05': {}}
            journey.recv_a = ACCEPTANCE.CanaryReceiver('A', Path(tmp) / 'A.jsonl')
            journey.recv_b = ACCEPTANCE.CanaryReceiver('B', Path(tmp) / 'B.jsonl')
            for recv in (journey.recv_a, journey.recv_b):
                recv.records.append({'path': '/host', 'peer': '127.0.0.1'})
            recorded = []
            journey.record = recorded.append

            def direct(_step_id, _title, argv, **_kwargs):
                tag = 'A' if '1234' in argv[-1] else 'B'
                recv = journey.recv_a if tag == 'A' else journey.recv_b
                path = argv[-1].split('/', 3)[-1]
                recv.records.append({'path': '/' + path, 'peer': '10.8.0.7'})
                return types.SimpleNamespace(stdout=json.dumps({'tag': tag}))

            journey.sandbox_exec = direct
            journey.calibrate_sandbox_peer()
            self.assertEqual(journey.sandbox_peer, '10.8.0.7')
            self.assertEqual(journey.meta['d05']['sandbox_peer'], '10.8.0.7')
            self.assertEqual(recorded[-1]['status'], 'pass')

            journey.recv_b.records.clear()
            journey.recv_b.records.append({'path': '/host', 'peer': '127.0.0.1'})
            def wrong_peer(_step_id, _title, argv, **_kwargs):
                tag = 'A' if '1234' in argv[-1] else 'B'
                recv = journey.recv_a if tag == 'A' else journey.recv_b
                path = '/' + argv[-1].split('/', 3)[-1]
                recv.records.append({'path': path, 'peer': '10.8.0.7' if tag == 'A' else '10.8.0.8'})
                return types.SimpleNamespace(stdout=json.dumps({'tag': tag}))
            journey.sandbox_exec = wrong_peer
            with self.assertRaises(ACCEPTANCE.StepFailure):
                journey.calibrate_sandbox_peer()

            def host_peer(_step_id, _title, argv, **_kwargs):
                tag = 'A' if '1234' in argv[-1] else 'B'
                recv = journey.recv_a if tag == 'A' else journey.recv_b
                path = '/' + argv[-1].split('/', 3)[-1]
                recv.records.append({'path': path, 'peer': '127.0.0.1'})
                return types.SimpleNamespace(stdout=json.dumps({'tag': tag}))
            journey.sandbox_exec = host_peer
            with self.assertRaises(ACCEPTANCE.StepFailure):
                journey.calibrate_sandbox_peer()

    def test_stop_reads_nested_success_and_conflict(self):
        direct = dict(status(), _http_status=200)
        conflict = {'_http_status': 409, 'error': 'stop_not_observable', 'status': status()}
        for response in [direct, conflict]:
            with self.subTest(response=response):
                got = ACCEPTANCE.parse_local_stop_response(response)
                self.assertEqual(got['remote_stop'], 'unsupported')
                self.assertIs(got['remote_stop_confirmed'], False)

    def test_missing_or_malformed_is_failure_not_backend_blocked(self):
        cases = [{'_http_status': 200}, dict(status(), _http_status=502),
                 {'_http_status': 409, 'error': 'unrelated', 'status': status()},
                 {'_http_status': 200, 'remote_stop': 'unsupported', 'remote_stop_confirmed': False}]
        for key, value in [('remote_stop', None), ('remote_stop_confirmed', None),
                           ('remote_stop_confirmed', 0), ('remote_stop_confirmed', True),
                           ('local_cli_termination', 'invented')]:
            doc = dict(status(), _http_status=200)
            doc['stop'][key] = value
            cases.append(doc)
        for response in cases:
            with self.subTest(response=response), self.assertRaises(ValueError):
                ACCEPTANCE.parse_local_stop_response(response)

    def test_cleanup_refuses_failed_readback_and_unowned_or_drifted_policy(self):
        body = json.dumps({"network_policies": {"unrelated": {}}})
        for rc, digest, state in [
            (1, "owned", {"applied2_version": 9, "applied2_hash": "owned"}),
            (0, "owned", {}),
            (0, "changed", {"applied2_version": 9, "applied2_hash": "owned"}),
            (0, "owned", {"applied2_version": 8, "applied2_hash": "owned"}),
        ]:
            with self.subTest(rc=rc, state=state), tempfile.TemporaryDirectory() as tmp:
                response = (rc, f"Version: 9\nHash: {digest}\n---\n{body}", "")
                with patch.dict('sys.modules', yaml=types.SimpleNamespace(safe_load=json.loads)), \
                        patch.object(SERVICE, 'cli_policy_full', return_value=response), \
                        patch.object(SERVICE.subprocess, 'run') as write:
                    with self.assertRaises(SERVICE.Check):
                        SERVICE.outside_service_cleanup(Path(tmp), state)
                    write.assert_not_called()

    def test_cleanup_restores_exact_captured_policy(self):
        pristine = '{"filesystem": {"read_only": true}}'
        owned = '{"network_policies": {"batch": {}}}'
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict('sys.modules', yaml=types.SimpleNamespace(safe_load=json.loads)), \
                patch.object(SERVICE, 'PRISTINE_HASH', 'baseline'), \
                patch.object(SERVICE, 'cli_policy_full', side_effect=[
                    (0, 'Version: 9\nHash: owned\n---\n' + owned, ''),
                    (0, 'Version: 10\nHash: baseline\n---\n' + pristine, '')]), \
                patch.object(SERVICE.subprocess, 'run', return_value=types.SimpleNamespace(
                    returncode=0, stdout='', stderr='')) as write:
            result = SERVICE.outside_service_cleanup(Path(tmp), {
                'applied2_version': 9, 'applied2_hash': 'owned', 'pristine_body': pristine})
            self.assertTrue(result['ok'])
            self.assertEqual((Path(tmp) / 'cleanup-restore-policy.yaml').read_text(), pristine)
            write.assert_called_once()

    def test_private_materials_exclusive_and_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private, db, seed = SERVICE.prepare_private_materials(root)
            self.assertEqual(private.name, 'd08-private')
            self.assertEqual(private.stat().st_mode & 0o777, 0o700)
            self.assertEqual(db.stat().st_mode & 0o777, 0o600)
            self.assertEqual(seed.parent, private)
            db.write_bytes(b'preserve-existing-run')
            with self.assertRaises(FileExistsError):
                SERVICE.prepare_private_materials(root)
            self.assertEqual(db.read_bytes(), b'preserve-existing-run')
            self.assertFalse((root / 'd08.db').exists())

    def test_only_filter_prefix_semantics(self):
        matches = ACCEPTANCE.only_filter_matches
        self.assertTrue(matches('leg_e04', None))
        self.assertTrue(matches('leg_e04', ''))
        self.assertTrue(matches('leg_e04', '  , , '))
        self.assertTrue(matches('leg_e04', 'e04'))
        self.assertTrue(matches('leg_e04_authority', 'e04'))
        self.assertTrue(matches('leg_e06_loading', 'E06'))
        self.assertTrue(matches('leg_k70', 'e06,k70'))
        self.assertFalse(matches('leg_e06_loading', 'e04'))
        self.assertFalse(matches('leg_k70', 'e0'))
        self.assertFalse(matches('leg_e01', 'e02,e06'))

    def test_ostart_evidence_id_mirrors_go_derivation(self):
        # openshell_task_exec.go: "ostart-" + hex(sha256("ostart|" + id)[:8]).
        self.assertEqual(
            ACCEPTANCE.ostart_evidence_id('rcp-0123456789ab-test-exec'),
            'ostart-e9f7cd755992a7e8')
        rid = ACCEPTANCE.ostart_evidence_id('rcp-deadbeef-exec')
        self.assertTrue(rid.startswith('ostart-'))
        self.assertEqual(len(rid), len('ostart-') + 16)
        int(rid[len('ostart-'):], 16)

    def test_ost_evidence_id_mirrors_go_derivation(self):
        # openshell_task_exec.go: "ost-" + hex(sha256("ost|" + id)[:8]) — the
        # outcome document the crash leg asserts is absent at kill time.
        self.assertEqual(
            ACCEPTANCE.ost_evidence_id('rcp-0123456789ab-test-exec'),
            'ost-495ef3ea90a10131')
        rid = ACCEPTANCE.ost_evidence_id('rcp-deadbeef-exec')
        self.assertTrue(rid.startswith('ost-') and not rid.startswith('ostart-'))
        self.assertEqual(len(rid), len('ost-') + 16)
        int(rid[len('ost-'):], 16)

    def test_filtered_storage_leg_cannot_pass_with_missing_core_checks(self):
        required = ('E11c', 'E11f', 'E11i', 'E11j')
        for steps in ([], [{'id': 'E11k', 'status': 'pass'}],
                      [{'id': 'E11c', 'status': 'pass'}]):
            with self.subTest(steps=steps):
                checks = ACCEPTANCE.required_step_checks(steps, required)
                self.assertEqual(set(checks), set(required))
                self.assertIn('not_run', checks.values())
                self.assertFalse(all(v == 'pass' for v in checks.values()))

    def test_required_checks_reject_failures_duplicates_and_missing_status(self):
        required = ('E11c', 'E11f', 'E11i', 'E11j')
        complete = [{'id': key, 'status': 'pass'} for key in required]
        self.assertTrue(all(v == 'pass' for v in
                            ACCEPTANCE.required_step_checks(complete, required).values()))
        for bad in ('fail', 'partial', 'blocked', 'not_run', None):
            steps = [dict(step) for step in complete]
            steps[2]['status'] = bad
            self.assertFalse(all(v == 'pass' for v in
                                 ACCEPTANCE.required_step_checks(steps, required).values()))
        for duplicate in ({'id': 'E11i', 'status': 'pass'},
                          {'id': 'E11i', 'status': 'fail'}):
            checks = ACCEPTANCE.required_step_checks(complete + [duplicate], required)
            self.assertEqual(checks['E11i'], 'ambiguous')

    def test_policy_wait_does_not_count_arbitrary_cli_error_as_timeout(self):
        for code in (0, 1, 2, 124, None):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                journey = object.__new__(ACCEPTANCE.AcceptanceJourney)
                journey.e06_changed_policy = Path(tmp) / 'policy.json'
                journey.e06_changed_policy.write_text('{}')
                journey.expected_revision, journey.expected_digest = '1', 'digest'
                journey.base_hash, journey.e06_changed_hash = 'original', 'changed'
                journey.cli_bin, journey.gateway_endpoint = 'openshell', 'test-endpoint'
                journey.target, journey.run_id = 'owned-target', 'test-run'
                journey.policy_read = Mock(side_effect=[{'revision': '1', 'hash': 'original'},
                                                        {'revision': '2', 'hash': 'changed'}])
                journey.approve_task = lambda *_a, **_kw: ({}, {}, {})
                journey.cli_unasserted = Mock(return_value=(
                    types.SimpleNamespace(returncode=code) if code is not None else None))
                journey.submit_expect_refusal = lambda *_a, **_kw: {'_http_status': 409}
                records = []
                journey.record = records.append
                result = journey._e06_cli_wait_timeout()
                self.assertEqual(result, 'pass' if code == 124 else 'partial')
                self.assertIs(records[-1]['cli_wait_timed_out'], code == 124)

    def test_timeout_verdict_checks_uncertainty_and_never_invents_remote_attribution(self):
        response = {'_http_status': 502, 'ok': False, 'execution_uncertain': True,
                    'outcome': {'state': 'timed_out', 'bound_fired': 'timeout',
                                'execution_uncertain': True, 'task_executed': 'unknown',
                                'spawned': True}}
        verdict = ACCEPTANCE.timeout_observation_status
        self.assertEqual(verdict(response), 'pass')
        for field, value in [('ok', True), ('execution_uncertain', False), ('_http_status', 200)]:
            self.assertEqual(verdict(dict(response, **{field: value})), 'fail')
        for field, value in [('execution_uncertain', False), ('task_executed', 'yes'),
                             ('bound_fired', None), ('state', 'succeeded')]:
            bad = dict(response, outcome=dict(response['outcome'], **{field: value}))
            self.assertEqual(verdict(bad), 'fail')
        ambiguous = dict(response, outcome={'state': 'failed', 'spawned': True,
                                            'task_executed': 'unknown', 'exit_code': 124,
                                            'exit_code_attribution': 'remote_or_cli',
                                            'execution_uncertain': False})
        self.assertEqual(verdict(ambiguous), 'partial')
        self.assertEqual(verdict({}), 'fail')

    def test_old_cli_refusal_cannot_close_unsupported_wait_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            journey = object.__new__(ACCEPTANCE.AcceptanceJourney)
            journey.root, journey.pristine_json = Path(tmp), Path(tmp) / 'pristine.json'
            journey.grant_id, journey.grant_digest = 'original', 'original-digest'
            journey.ep_a = 'example.invalid:1234'
            journey.steps = [{'id': 'E06g', 'status': 'pass'}]
            journey.e_items = []
            journey.record = journey.steps.append
            journey.http = Mock(return_value={'admission': {'admission_id': 'second'}})
            journey.deploy_grant = Mock(return_value={'grant_id': 'second', 'grant_digest': 'digest'})
            journey._e06_submit_during_load = Mock(return_value='pass')
            journey._e06_cli_wait_timeout = Mock(return_value='pass')
            journey._e06_old_cli = Mock(return_value='pass')
            journey._e06_restore_pristine = Mock()
            journey.leg_e06_loading()
            self.assertEqual(journey.e_items[0]['status'], 'partial')
            self.assertEqual(journey.e_items[0]['sub_results']['unsupported_wait_option'], 'not_run')

    def test_e_item_upsert_replaces_same_item_row(self):
        journey = object.__new__(ACCEPTANCE.AcceptanceJourney)
        journey.e_items = []
        journey.e_item('E06', 'partial', detail='baseline')
        journey.e_item('E01', 'pass', detail='untouched')
        journey.e_item_upsert('E06', 'pass', detail='closure legs ran')
        rows = [e for e in journey.e_items if e['item'] == 'E06']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'pass')
        self.assertEqual(rows[0]['detail'], 'closure legs ran')
        self.assertEqual(journey.e_items[1]['status'], 'pass')
        journey.e_item_upsert('E09', 'partial', detail='new row appended')
        self.assertEqual([e['item'] for e in journey.e_items], ['E06', 'E01', 'E09'])


if __name__ == '__main__':
    unittest.main()
