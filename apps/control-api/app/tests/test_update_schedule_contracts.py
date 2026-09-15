"""Independent structural validation of local scheduler wire and disk contracts."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[4]


@pytest.mark.parametrize('kind', [
    'local-skill-update-source-save', 'local-skill-update-source-disable',
    'local-skill-update-schedule-view',
    'local-skill-update-schedule', 'local-skill-update-schedule-run',
    'local-skill-update-schedule-run-result',
])
def test_update_schedule_contract(kind):
    schema = json.loads((ROOT / 'packages/contracts' / f'{kind}.v1.schema.json').read_text())
    example = json.loads((ROOT / 'apps/agentshield/testdata/contracts' / f'{kind}.json').read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(example)
    for key in schema['required']:
        assert list(validator.iter_errors({k: v for k, v in example.items() if k != key}))
        assert list(validator.iter_errors({**example, key: None}))
    assert list(validator.iter_errors({**example, 'unknown': 'reject'}))
    assert list(validator.iter_errors({**example, 'schema_version': 'future/v99'}))
