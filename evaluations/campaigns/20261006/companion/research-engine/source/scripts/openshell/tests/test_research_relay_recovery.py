"""Permission-only fixture routing; financial guard remains enabled."""
from pathlib import Path

from scripts.openshell.prove_research_relay_recovery import RelayRecoveryScenario
from services import agent_chat_runtime_impl as runtime


def test_permission_prompt_has_four_requested_tools_without_financial_routing(tmp_path):
    scenario = object.__new__(RelayRecoveryScenario)
    scenario.company = tmp_path / 'company'
    scenario.prepare_company()
    body = scenario.request_body('SIQ_API_TEST', 'SIQ_TRACE_TEST', '600000-SyntheticApi' + 'a' * 16)
    message = body['message']
    assert body['runtime_target'] == 'openshell'
    assert 'read_file' in message and '三个 write_file 调用' in message
    assert all(value in message for value in ['AUTHORIZED_STAGE_ONE', 'DURING_RELAY_OUTAGE', 'RECOVERED_RELAY_WRITE'])
    assert (scenario.company / 'synthetic.txt').read_text() == 'Synthetic permission fixture. Controlled local read input.\n'
    assert not runtime._needs_financial_evidence_contract(message, None)


def test_financial_request_still_requires_evidence():
    assert runtime._needs_financial_evidence_contract('OpenShell/Hermes 请核验营收、利润和同比增长率。', None)
