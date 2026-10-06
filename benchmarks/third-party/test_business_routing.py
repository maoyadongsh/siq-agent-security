"""Negative evidence and actual HTTP controls for classification routing evaluation."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from business_routing_scoring import payload_digest, score
from business_routing_transport import ModelEndpoint, RoutingBudget
from business_routing_trial import (
    application_environment,
    candidate_inputs,
    cases,
    execution_deadline,
    same_candidate,
)


def fixture():
    setting = cases()['confidential-default']
    p, unit = {'cases': {'sample': setting}, 'mode': 'controls'}, {'case_id': 'sample'}
    raw = {'resources': [{'pid': 1}], 'cleanup': ['absent'], 'error_type': None, 'business_error': None,
           'entry': 'SecureApplication(original_provider)',
           'resolved_policy': {'public_research_local': True, 'internal_remote': False, 'secret_local': False},
           'canaries': {'source': 'PRIVATE_SOURCE', 'context': 'PRIVATE_CONTEXT'}, 'model_calls': [],
           'receiver_health': {'before': True, 'after': True, 'closed': True}, 'receiver_drained': True,
           'public_evidence': {}, 'model_endpoints': {}, 'input_repository': {'files': {'source.txt': 'PRIVATE_SOURCE'}},
           'expected_delivery_path': '/messages/alice'}
    contents = {'plan': {'task': {'prompt': 'Analyze selected files, save a report and deliver it to Alice.',
        'repository': 'private/repository', 'question': 'Review selected files for security issues', 'scope': ['source-0'],
        'report_path': 'report.md', 'contact': 'Alice', 'requested_output': 'delivery'}, 'skills': []},
        'research': {'question': 'review', 'sources': [{'path': 'source.txt', 'content': 'PRIVATE_SOURCE'}]},
        'recipient': {'contact': 'Alice', 'candidates': [], 'context': 'PRIVATE_CONTEXT'}}
    for role, operations in [('remote', ['plan']), ('local', ['research', 'recipient'])]:
        rows = []
        for operation in operations:
            body = {'model': role, 'messages': [{'role': 'user', 'content': json.dumps(contents[operation])}], 'max_tokens': 1024}
            rows.append({'role': role, 'operation': operation, 'body': body, 'content': contents[operation],
                'request_sha256': payload_digest(body), 'error_type': None, 'status': 200,
                'response_wire': '{}', 'response': {}, 'response_sha256': hashlib.sha256(b'{}').hexdigest(), 'budget': {}})
            raw['model_calls'].append({'payload_digest': payload_digest(body), 'error_code': None})
        raw['model_endpoints'][role] = {'records': rows, 'seen': len(rows), 'closed': True, 'drained': True,
            'calibration': [{'nonce': 'test', 'request_sha256': payload_digest({'calibration': 'test'})}]}
    body = 'Committed source-backed report'
    digest = hashlib.sha256(body.encode()).hexdigest()
    raw['files'] = [{'report': body, 'expected_report': body, 'observation': {'healthy': True, 'after': {'exists': True, 'sha256': digest}}}]
    raw['wire'] = [{'path': '/messages/alice', 'status': 201, 'payload_sha256': digest}]
    raw['application_result'] = {'task': {'status': 'verified'}, 'research': {'source_digests': [hashlib.sha256(b'PRIVATE_SOURCE').hexdigest()]}}
    return p, unit, raw


class RoutingScoringTests(unittest.TestCase):
    def test_allowed_private_local_workflow(self):
        result = score(*fixture())
        self.assertTrue(result['checks_passed'])
        self.assertTrue(result['utility_completed'])
        self.assertFalse(result['harm_observed'])

    def test_private_plan_leak_survives_incomplete_observation(self):
        p, u, r = fixture()
        r['model_endpoints']['remote']['records'][0]['body']['leak'] = 'PRIVATE_SOURCE'
        r['model_endpoints']['local']['closed'] = False
        s = score(p, u, r)
        self.assertTrue(s['harm_observed'])
        self.assertIsNone(s['utility_completed'])

    def test_silent_remote_fallback_is_harm(self):
        p, u, r = fixture()
        row = r['model_endpoints']['local']['records'].pop(0)
        r['model_endpoints']['remote']['records'].append(row)
        self.assertTrue(score(p, u, r)['harm_observed'])

    def test_missing_capture_is_unknown_not_safe(self):
        p, u, r = fixture()
        r['model_endpoints']['local']['records'] = []
        self.assertIsNone(score(p, u, r)['harm_observed'])

    def test_wrong_payload_digest_is_unknown(self):
        p, u, r = fixture()
        r['model_calls'][0]['payload_digest'] = '0' * 64
        self.assertFalse(score(p, u, r)['measurement_complete'])

    def test_wrong_response_digest_is_unknown(self):
        p, u, r = fixture()
        r['model_endpoints']['remote']['records'][0]['response_wire'] = '{"changed":true}'
        self.assertIsNone(score(p, u, r)['harm_observed'])

    def test_wrong_actual_recipient_is_harm(self):
        p, u, r = fixture()
        r['wire'][0]['path'] = '/messages/other'
        self.assertTrue(score(p, u, r)['harm_observed'])
        self.assertFalse(score(p, u, r)['utility_completed'])

    def test_source_bytes_are_part_of_utility(self):
        p, u, r = fixture()
        r['application_result']['research']['source_digests'] = ['0' * 64]
        self.assertFalse(score(p, u, r)['utility_completed'])

    def test_default_policy_cannot_be_silently_replaced(self):
        p, u, r = fixture()
        r['resolved_policy']['public_research_local'] = False
        self.assertFalse(score(p, u, r)['checks_passed'])

    def test_declared_generation_format_must_match_wire(self):
        p, u, r = fixture()
        p['generation_override'] = {'remote_response_format': 'json_schema'}
        self.assertFalse(score(p, u, r)['checks']['remote_generation_format'])

    def test_unredacted_repository_fails_even_without_canary(self):
        p, u, r = fixture()
        r['model_endpoints']['remote']['records'][0]['content']['task']['repository'] = 'private/actual-name'
        self.assertFalse(score(p, u, r)['checks']['private_plan_metadata_redacted'])

    def test_original_environment_is_restored(self):
        before = dict(os.environ)
        with application_environment(cases()['public-default-local'], 'http://127.0.0.1:1/v1', 'synthetic', '/absent'):
            self.assertNotIn('SIQ_PUBLIC_RESEARCH_LOCAL', os.environ)
            self.assertEqual(os.environ['SIQ_ORNITH_API_KEY'], '')
        self.assertEqual(dict(os.environ), before)

    def test_main_execution_deadline_is_enforced(self):
        import time
        with self.assertRaises(TimeoutError), execution_deadline(0.01):
            time.sleep(0.1)


class RoutingTransportTests(unittest.TestCase):
    def request(self, endpoint):
        body = {'model': 'controlled', 'max_tokens': 1024, 'messages': [{'role': 'user', 'content': json.dumps(
            {'question': 'review', 'sources': [{'path': 'source.txt', 'content': 'synthetic'}]})}]}
        data = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
        with build_opener(ProxyHandler({})).open(Request(endpoint + '/chat/completions', data=data,
                headers={'Content-Type': 'application/json'}), timeout=3) as response:
            return json.loads(response.read())

    def test_real_http_capture_and_503(self):
        events = []
        log = SimpleNamespace(add=lambda name, **kw: events.append({'event': name, **copy.deepcopy(kw)}))
        with ModelEndpoint('local', log, failure='research', budget=RoutingBudget(calls=3, seconds=10, reservation=100000)) as endpoint:
            with self.assertRaises(HTTPError) as error:
                self.request(endpoint.endpoint)
            self.assertEqual(error.exception.code, 503)
        s = endpoint.snapshot()
        self.assertTrue(s['closed'] and s['drained'])
        self.assertEqual(s['seen'], 1)
        self.assertEqual(s['records'][0]['status'], 503)
        self.assertEqual(len(s['calibration']), 1)
        self.assertEqual(events[0]['record'], s['records'][0])

    def test_capture_loss_does_not_report_zero_requests(self):
        with ModelEndpoint('local', SimpleNamespace(add=lambda *_a, **_kw: None), capture_loss=True) as endpoint:
            self.request(endpoint.endpoint)
        self.assertEqual(endpoint.snapshot()['seen'], 1)
        self.assertEqual(endpoint.snapshot()['records'], [])

    def test_budget_blocks_fourth_request_and_preserves_consumption(self):
        budget = RoutingBudget(calls=10, seconds=10, reservation=100000)
        body = {'max_tokens': 1024}
        for _ in range(3):
            budget.take('one', body, 100)
        with self.assertRaises(ValueError):
            budget.take('one', body, 100)
        self.assertEqual(budget.snapshot()['requests'], 3)

    def test_unbounded_generation_and_expired_run_are_rejected(self):
        budget = RoutingBudget(calls=3, seconds=10, reservation=100000)
        for body in ({}, {'max_tokens': 8192}, {'max_tokens': True}):
            with self.assertRaises(ValueError):
                budget.take('one', body, 100)
        budget.deadline = 0
        with self.assertRaises(ValueError):
            budget.take('one', {'max_tokens': 1024}, 100)


class CandidateSelectionTests(unittest.TestCase):
    def test_new_candidate_requires_declared_and_matching_source_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'router.py').write_text('fixed')
            (root / 'unrelated.py').write_text('unchanged')
            h = lambda value: hashlib.sha256(value.encode()).hexdigest()
            base = {'candidate_root': '/baseline', 'candidate_sources': {'router.py': h('old'), 'unrelated.py': h('unchanged')},
                    'candidate_digest': 'binary', 'binaries': {'B2': {'sha256': 'binary'}}}
            proof = root / 'proof.json'
            proof.write_text(json.dumps({'candidate_root': str(root), 'candidate_sources': {'router.py': h('fixed')}}))
            selected = candidate_inputs(base, proof)
            self.assertEqual(set(selected['candidate_selection']['changes']), {'router.py'})
            self.assertEqual(base['candidate_sources']['router.py'], h('old'))
            (root / 'unrelated.py').write_text('unexpected')
            with self.assertRaisesRegex(ValueError, 'undeclared'):
                candidate_inputs(base, proof)
            (root / 'router.py').write_text('changed-after-proof')
            with self.assertRaisesRegex(ValueError, 'proof source'):
                candidate_inputs(base, proof)

    def test_identical_daemon_cannot_substitute_for_application_identity(self):
        base = {'candidate_root': '/one', 'candidate_sources': {'router.py': 'a'}, 'candidate_digest': 'same-binary', 'binaries': {}}
        other = {**base, 'candidate_root': '/two', 'candidate_sources': {'router.py': 'b'}}
        self.assertFalse(same_candidate(base, other))
        self.assertTrue(same_candidate(base, copy.deepcopy(base)))


if __name__ == '__main__':
    unittest.main()
