"""Installer cleanup must resume the original signed removal transaction."""
from scripts.openshell.research_permission_skills import removal_request


def test_initial_removal_uses_current_authority():
    view = {'record': {'operation': {'signature': 'operation'}},
            'state_revision': 3, 'binding_signature': 'binding', 'claim': None}
    request = removal_request(view)
    assert request['expected_grant_revision'] == 3
    assert request['expected_binding_signature'] == 'binding'


def test_retry_after_revocation_keeps_original_claim_revision():
    view = {'record': {'operation': {'signature': 'operation'}},
            'state_revision': 4, 'binding_signature': 'binding',
            'claim': {'grant_revision': 3, 'binding_signature': 'binding'}}
    request = removal_request(view)
    assert request['expected_grant_revision'] == 3
    assert request['operation_signature'] == 'operation'
