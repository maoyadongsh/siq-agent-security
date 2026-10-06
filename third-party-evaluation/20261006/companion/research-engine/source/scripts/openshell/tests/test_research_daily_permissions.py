import pytest

from scripts.openshell.prove_research_daily_permissions import owned_receipts


def test_shared_authority_export_excludes_other_agents_and_paginates():
    calls = []
    pages = [
        {'verified': True, 'receipts': [{'seq': 1, 'agent_id': 'other', 'receipt_id': 'private'},
                                      {'seq': 2, 'agent_id': 'own', 'receipt_id': 'a'}]},
        {'verified': True, 'receipts': [{'seq': 3, 'agent_id': 'own', 'receipt_id': 'b'}]},
        {'verified': True, 'receipts': []},
    ]

    def call(path):
        calls.append(path)
        return pages.pop(0)

    result = owned_receipts(call, 'own')
    assert [r['receipt_id'] for r in result['receipts']] == ['a', 'b']
    assert calls == ['/v1/receipts?since_seq=-1', '/v1/receipts?since_seq=2', '/v1/receipts?since_seq=3']


def test_unverified_or_nonadvancing_receipt_page_is_rejected():
    with pytest.raises(RuntimeError, match='chain_unverified'):
        owned_receipts(lambda _: {'verified': False, 'receipts': []}, 'own')
    with pytest.raises(RuntimeError, match='cursor_invalid'):
        owned_receipts(lambda _: {'verified': True, 'receipts': [{'seq': 1, 'agent_id': 'own'}]}, 'own')
