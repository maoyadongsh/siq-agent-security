"""The fixture grants tool names, never guesses unknown interpreter effects."""
import base64
import json
import subprocess
import sys

import pytest

from scripts.openshell.prove_research_tool_utility import (
    CATALOG_PAGE_CODE, ToolUtilityScenario, UtilityAuthority, WRITER_TOOLS, append_catalog_page,
)
from services import agent_chat_runtime_impl as runtime


def test_additional_grant_applies_only_to_owned_writer():
    authority = object.__new__(UtilityAuthority)
    assert authority.desired_tools('research-permissions-reader') == ['read_file', 'write_file']
    assert authority.desired_tools('research-permissions-writer') == WRITER_TOOLS
    assert 'process' not in WRITER_TOOLS and 'search_files' not in WRITER_TOOLS


def test_runtime_probe_remains_nonfinancial_and_preserves_denial_measurement(tmp_path):
    scenario = object.__new__(ToolUtilityScenario)
    scenario.company = tmp_path / 'owned'
    scenario.prepare_company()
    body = scenario.request_body('SIQ_API_TEST', 'SIQ_TRACE_TEST', '600000-SyntheticApi' + 'a' * 16)
    assert not runtime._needs_financial_evidence_contract(body['message'], None)
    assert '十五个' in body['message'] and '可能因未知效果被拒绝' in body['message']
    assert (scenario.company / 'synthetic.txt').read_bytes() == b'CONTROLLED_READ_ONLY'


def test_catalog_larger_than_cli_limit_exports_without_truncation(tmp_path):
    directory = tmp_path / 'journal'
    directory.mkdir()
    # A single schema can itself span pages, including UTF-8 split boundaries.
    original = (json.dumps({'tools': ['合成工具' * 18000]}, ensure_ascii=False) + '\n').encode()
    (directory / 'tool-catalog.jsonl').write_bytes(original)
    (directory / 'catalog-complete.json').write_text(json.dumps({'request_count': 1}))
    code = CATALOG_PAGE_CODE.replace('/tmp/siq-research-skill-sync', str(directory))
    collected = b''
    for _ in range(20):
        output = subprocess.check_output([sys.executable, '-c', code, str(len(collected))])
        assert len(output) < 65536
        exported = json.loads(output)
        collected, size = append_catalog_page(collected, exported)
        if len(collected) == size:
            break
    assert len(original) > 65536 and collected == original
    assert exported['complete'] == {'request_count': 1}


@pytest.mark.parametrize('page', [
    {'offset': 1, 'size': 1, 'page': ''},
    {'offset': 0, 'size': 2097153, 'page': ''},
    {'offset': 0, 'size': 2, 'page': base64.b64encode(b'x').decode()},
    {'offset': 0, 'size': 1, 'page': '!invalid!'},
    {'offset': False, 'size': 0, 'page': ''},
])
def test_catalog_page_rejects_gaps_truncation_and_invalid_bounds(page):
    with pytest.raises(ValueError):
        append_catalog_page(b'', page)
