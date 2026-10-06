import copy
import io
import json
from types import SimpleNamespace

import pytest

from scripts.openshell import prove_research_skill_drift_authority as proof


def test_pair_requires_rejection_and_same_restored_identity():
    before = {'HTTP_status': 200, 'body': {'identity_id': 'original'}, 'finished_unix': 1}
    changed = {'HTTP_status': 401, 'body': {'error': 'runtime_identity_required'},
               'started_unix': 4, 'finished_unix': 5}
    restored = {'HTTP_status': 200, 'body': before['body'], 'started_unix': 6}
    mutation = {'before_sha256': 'a', 'after_sha256': 'b',
                'mutation_started_unix': 2, 'mutation_finished_unix': 3}
    assert all(proof.paired_checks(before, changed, restored, mutation).values())
    for status in (200, 403, 500, 503):
        bad = dict(changed, HTTP_status=status)
        assert not all(proof.paired_checks(before, bad, restored, mutation).values())
    other = copy.deepcopy(restored)
    other['body']['identity_id'] = 'replacement'
    assert not all(proof.paired_checks(before, changed, other, mutation).values())


@pytest.mark.parametrize('body', [{'error': 'runtime_identity_required', 'secret': 'sensitive'},
                                 {'error': 'internal_error'}])
def test_unrecognized_auth_response_never_exported(body):
    response = io.BytesIO(json.dumps(body).encode())
    response.status = 401
    authority = SimpleNamespace(endpoint='http://127.0.0.1:47811',
                                http=SimpleNamespace(open=lambda *a, **k: response))
    with pytest.raises(RuntimeError, match='candidate_drift_self_unexpected_response'):
        proof.inspect_self(authority, 'private-credential')
