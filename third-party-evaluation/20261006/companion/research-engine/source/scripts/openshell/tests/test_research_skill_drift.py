import json

from scripts.openshell import prove_research_skill_drift as drift


def test_actual_cli_defaults_construct_original_scenario_without_authority_calls(tmp_path):
    args = drift.arguments([
        '--recovery-file', str(tmp_path / 'recovery-reference'),
        '--relay-binary', str(tmp_path / 'relay'), '--relay-sha256', 'a' * 64,
        '--helper-image-ref', 'helper', '--helper-image-id', 'sha256:' + 'b' * 64,
        '--evidence-suffix', 'v9999', '--output', str(tmp_path / 'result.json')])
    scenario = drift.DriftScenario(args)
    assert scenario.task == 'paired-analysis' and scenario.control == 'drift-installation'
    assert scenario.setup_state.is_dir() and not scenario.factory.admin


def test_diagnostics_export_fixed_category_lines_only():
    rows = [
        {'MESSAGE': 'supervisor_failure stage=runtime_identity category=authority_service', '__REALTIME_TIMESTAMP': '123'},
        {'MESSAGE': 'private token or model content'},
        {'MESSAGE': 'supervisor_failure stage=guard_tick category=run_guard private password'},
    ]
    assert drift.categorical_journal('\n'.join(json.dumps(r) for r in rows)) == [
        {'timestamp_microseconds': '123', 'stage': 'runtime_identity', 'category': 'authority_service'}]


def test_journal_failure_never_skips_original_cleanup(monkeypatch):
    scenario = drift.DriftScenario.__new__(drift.DriftScenario)
    scenario.sync_records = [{'business_run_id': 'qwen-request-' + '1' * 16}]
    result, calls = {}, []
    def unavailable(*args):
        raise OSError('private path')
    monkeypatch.setattr(drift.startup, 'location', unavailable)
    monkeypatch.setattr(drift.withdrawal.WithdrawalScenario, 'cleanup',
                        lambda self, report: calls.append(report) or True)
    assert scenario.cleanup(result) is True
    assert calls == [result] and result == {'diagnostic_collection_failure_type': 'OSError'}
