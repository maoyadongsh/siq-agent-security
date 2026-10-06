"""Measurement boundary checks; product behavior is exercised in the real cohort."""
import copy

import pytest
from native_personal_runtime_check import checks, instance
from verify_native_personal_runtime_check import record_canonical


def test_same_name_cannot_substitute_instance():
    catalog = {'instances': [{'instance_id': 'actual', 'name': 'work'}]}
    assert instance(catalog, 'actual')['name'] == 'work'
    with pytest.raises(ValueError):
        instance(catalog, 'different')
    with pytest.raises(ValueError):
        instance({'instances': catalog['instances'] * 2}, 'actual')


def test_partial_capture_never_passes_selfcheck():
    result = checks({'error_type': 'not_started', 'stages': {}})
    assert len(result) == 21
    assert not result['selfcheck_capture_complete']
    assert not result['product_selfcheck_passed']
    assert not result['actual_product_host_observed']
    assert not result['product_cleanup_complete']


def test_runtime_record_uses_product_float_revision_without_mutation():
    doc = {'revision': 1, 'result': {'ok': True, 'finished_at': None}, 'signature': 'unused'}
    before = copy.deepcopy(doc)
    assert record_canonical(doc) == b'{"result":{"finished_at":null,"ok":true},"revision":1.0}'
    assert doc == before
