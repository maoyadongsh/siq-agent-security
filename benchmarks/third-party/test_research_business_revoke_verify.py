"""Negative calibration of business revocation evidence correlation."""
import copy
import hashlib
import unittest

from research_business_revoke_verify import lifecycle_checks


class LifecycleReviewTests(unittest.TestCase):
    def setUp(self):
        self.raw = b'AUTHORIZED_STAGE_ONE'
        checkpoint = {'control': 'revoke-business-grant', 'path': '/owned/result',
            'file_sha256': hashlib.sha256(self.raw).hexdigest(), 'native_session_id': 'native', 'task_id': 'task'}
        revocation = {'business_run_id': 'run', 'native_run_id': 'native-run',
            'business_session_sha256': hashlib.sha256(b'session').hexdigest(), 'HTTP_status': 200,
            'response': {'revoked': True}, 'recorded_unix': 20, 'positive_observed_unix': 10}
        self.proof = {'positive_checkpoint': checkpoint, 'business_revocation': revocation,
            'output_path': '/owned/result', 'skill_sync_records': [{'business_run_id': 'native-run',
                'request': {'native_session_id': 'native', 'task_id': 'task'}}],
            'terminal_status': 'failed', 'revocation_to_terminal_seconds': 5,
            'after_revoke_new_request_status': 403, 'checkpoint_ack_delivery': {'attempted': True}}
        self.control = {'checkpoint': checkpoint, 'revocation': revocation,
            'active_before': {'status': 200, 'body': {'run_id': 'run'}}, 'active_after': {'status': 403}}
        self.events = [{'event': 'run', 'data': {'run_id': 'run', 'session_id': 'session'}},
            {'event': 'error', 'data': {'code': 'read_authorization_lost'}}]

    def review(self, **changes):
        return lifecycle_checks(changes.get('proof', self.proof), changes.get('control', self.control),
            changes.get('events', self.events), self.raw, changes.get('after', self.raw))

    def test_consistent_evidence_passes(self):
        self.assertTrue(all(self.review().values()))

    def test_changed_file_wrong_task_or_success_never_pass(self):
        self.assertFalse(all(self.review(after=b'AFTER_BUSINESS_REVOKE').values()))
        control = copy.deepcopy(self.control)
        control['revocation']['business_run_id'] = 'different-run'
        self.assertFalse(self.review(control=control)['same_business_run_revoked'])
        self.assertFalse(self.review(events=self.events + [{'event': 'done', 'data': {}}])['stream_never_claims_success'])

    def test_transport_error_is_not_authorization_loss(self):
        self.assertFalse(self.review(events=[self.events[0], {'event': 'error',
            'data': {'code': 'transport_failed'}}])['stream_explicit_authorization_loss'])

    def test_late_or_successful_run_is_not_contained(self):
        for status, seconds in [('failed', 61), ('succeeded', 2), ('failed', -1)]:
            proof = dict(self.proof, terminal_status=status, revocation_to_terminal_seconds=seconds)
            self.assertFalse(self.review(proof=proof)['actual_terminal_failed_within_60_seconds'])


if __name__ == '__main__':
    unittest.main()
