"""The drift probe must restore inode ownership, not only equal file bytes."""
import hashlib
import os
from types import SimpleNamespace

import pytest

from scripts.openshell import prove_research_skill_withdrawal as withdrawal


def test_sec_revocation_prompt_routes_as_permission_task_with_company_context(tmp_path):
    from services import agent_chat_runtime_impl as runtime

    scenario = object.__new__(withdrawal.WithdrawalScenario)
    scenario.company = tmp_path / 'company'
    scenario.task = 'paired-analysis'
    scenario.control = 'revoke-context'
    scenario.prepare_company()
    body = scenario.request_body('SIQ_API_TEST', 'SIQ_TRACE_TEST', '600000-SyntheticApi' + 'a' * 16)
    assert not runtime._needs_financial_evidence_contract(body['message'], body['context'])
    # Naming the runtime must not bypass the guard for an actual financial request.
    assert runtime._needs_financial_evidence_contract(
        body['message'] + ' 请计算营收同比增长率。', body['context'])
    assert 'revenue' not in (scenario.company / 'synthetic.txt').read_text()


@pytest.mark.parametrize('tamper_backup', [False, True])
def test_drift_restoration_preserves_original_installer_identity(tmp_path, monkeypatch, tamper_backup):
    owned = tmp_path / 'installed'
    owned.mkdir()
    source = tmp_path / 'installer-owned-file'
    source.write_bytes(b'approved Skill content\n')
    source.chmod(0o444)
    installed = owned / 'SKILL.md'
    os.link(source, installed)
    original = source.stat()
    scenario = withdrawal.WithdrawalScenario.__new__(withdrawal.WithdrawalScenario)
    scenario.control = 'drift-installation'
    scenario.setup_state = tmp_path / 'evidence'
    scenario.setup_state.mkdir()
    scenario.factory = SimpleNamespace(selected={'installed_path': str(owned),
        'skill_file_sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    scenario.original_installed = None
    scenario.mutation = scenario.mutate({})
    assert installed.read_bytes() != source.read_bytes()
    assert installed.stat().st_ino != original.st_ino
    monkeypatch.setattr(withdrawal.skills.SkillScenario, 'cleanup', lambda self, result: True)
    if tamper_backup:
        backup = scenario.original_installed[3]
        # Replacing this link must not modify the immutable installer source.
        backup.unlink()
        backup.write_bytes(b'not approved')
        with pytest.raises(RuntimeError, match='candidate_skill_drift_backup_changed'):
            scenario.cleanup({})
        assert not os.path.samefile(source, installed)
    else:
        assert scenario.cleanup({}) is True
        assert os.path.samefile(source, installed)
        assert installed.stat().st_mode & 0o777 == 0o444
        assert scenario.original_installed is None
