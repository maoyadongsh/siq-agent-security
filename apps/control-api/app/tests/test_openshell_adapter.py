"""OpenShell Adapter 契约测试（设计文档 §15.3）。

以 FakeBackend 锁定合同语义：能力探测、revision 并发冲突、静态边界 generation、
正负向验证、回滚、unsupported 显式标记。真实后端接入后同一套测试跑在
contract/ 目录的适配器合同测试（开发计划 §5 Phase 3 进入条件）。
"""

from __future__ import annotations

import pytest

from app.adapters.openshell import FakeOpenShellBackend
from app.adapters.openshell.contracts import RevisionConflict, UnsupportedCapability, VerificationFailed


def _network_policy(policy_id="pol-1", **overrides):
    base = {
        "policy_id": policy_id,
        "version": 1,
        "selector": {"agent_ids": ["agt_1"]},
        "network": [
            {
                "endpoint": "api.example.com:443/orders/**",
                "effect": "allow",
                "methods": ["GET"],
                "purpose": "order-read",
            }
        ],
        "enforcement_mode": "block",
        "status": "approved",
    }
    base.update(overrides)
    return base


def test_probe_reports_actual_capabilities():
    backend = FakeOpenShellBackend()
    caps = backend.probe()
    assert caps.backend == "openshell"
    assert caps.dynamic_network_update is False  # 镜像 v0.0.83 现状
    assert caps.interceptor is False


def test_compile_marks_unsupported_explicitly():
    """§14.1：后端不支持的字段显式列出，不得静默丢失。"""
    backend = FakeOpenShellBackend()
    compiled = backend.compile(_network_policy())
    # v0.0.83 无动态网络更新 → 网络落静态制品 + 显式 unsupported
    assert "network.dynamic_update" in compiled.unsupported_by_backend
    assert compiled.needs_generation is True
    assert compiled.artifact["network_policies"][0]["endpoint"].startswith("api.example.com")


def test_compile_rejects_unknown_semantics():
    backend = FakeOpenShellBackend()
    with pytest.raises(UnsupportedCapability):
        backend.compile(_network_policy(evil_field={"x": 1}))


def test_validate_checks_artifact_hash():
    backend = FakeOpenShellBackend()
    compiled = backend.compile(_network_policy())
    report = backend.validate(compiled)
    assert report.valid is True


def test_dynamic_apply_revision_conflict():
    """带外变更防护：期望 revision 不匹配 → RevisionConflict。"""
    backend = FakeOpenShellBackend(dynamic_network_update=True)
    compiled = backend.compile(_network_policy())
    plan = backend.plan_change("sandbox-1", compiled)  # expected_revision=0
    # 模拟带外变更：另一个写者先改了 revision
    backend.create_generation("sandbox-1", compiled)
    with pytest.raises(RevisionConflict):
        backend.apply_dynamic("sandbox-1", plan, expected_revision="0")


def test_dynamic_apply_verify_and_rollback():
    backend = FakeOpenShellBackend(dynamic_network_update=True)
    compiled = backend.compile(_network_policy())
    plan = backend.plan_change("sandbox-2", compiled)
    receipt = backend.apply_dynamic("sandbox-2", plan, expected_revision="0")
    assert receipt.backend_revision == "1"
    assert receipt.evidence["snapshot_hash"]

    # 正负向验证（§15.3：各至少一项）
    report = backend.verify(
        "sandbox-2",
        checks={"expect_allow": ["api.example.com:443/orders/**"], "expect_deny": ["evil.example.com"]},
        receipt=receipt,
    )
    assert report.passed is True, report.failures

    # 回滚恢复上一 revision
    rollback = backend.rollback("sandbox-2", receipt)
    assert rollback.restored_revision == "0"
    assert backend.read_effective_policy("sandbox-2").revision == "0"


def test_static_boundary_requires_generation():
    """§15.2：文件/进程静态边界不能走动态发布。"""
    backend = FakeOpenShellBackend(dynamic_network_update=True)
    compiled = backend.compile(
        _network_policy(filesystem={"read_only": ["/data/wiki"], "read_write": ["/data/analysis"]})
    )
    assert compiled.needs_generation is True
    plan = backend.plan_change("sandbox-3", compiled)
    assert plan.kind == "generation"
    with pytest.raises(VerificationFailed):
        backend.apply_dynamic("sandbox-3", plan, expected_revision="0")
    receipt = backend.create_generation("sandbox-3", compiled)
    assert receipt.backend_revision == "1"


def test_read_effective_policy_is_backend_state_not_desired():
    backend = FakeOpenShellBackend()
    snapshot = backend.read_effective_policy("nonexistent-target")
    assert snapshot.revision == "0"  # 不虚构 desired 状态
    # P1-11：目标不存在时无法确定执行模式，如实 unknown（不虚构 block）
    assert snapshot.enforcement_mode == "unknown"


def test_verify_requires_both_allow_and_deny():
    backend = FakeOpenShellBackend(dynamic_network_update=True)
    compiled = backend.compile(_network_policy())
    receipt = backend.apply_dynamic("sandbox-4", backend.plan_change("sandbox-4", compiled), "0")
    report = backend.verify("sandbox-4", checks={"expect_allow": ["api.example.com:443/orders/**"]}, receipt=receipt)
    assert report.passed is False
    assert report.level == "failed"  # P1-2：失败时 level 如实 failed
    assert any("正负向" in f for f in report.failures)


# ------------------------------------------------------------ P1-1/P1-2/P1-11 合同测试


def test_probe_reports_versioned_capability_document():
    """P1-1：能力文档按能力域逐项报告 status/semantics/basis（Fake 按模拟语义如实标注）。"""
    caps = FakeOpenShellBackend().probe()
    assert caps.capabilities, "能力文档必须非空"
    for name, item in caps.capabilities.items():
        assert item.status in ("supported", "unsupported", "unknown"), name
        assert item.semantics in ("enforce", "observe", "advisory", "none"), name
        assert item.basis, f"{name} 必须标注判定依据"
    # Fake 默认镜像 v0.0.83：网络 L3/L4 无动态更新、工具治理未知
    assert caps.capability("network_l34").status == "unsupported"
    assert caps.capability("tools_mcp").status == "unknown"
    # 未报告的能力项查询 → unknown（fail-closed，绝不当 supported）
    assert caps.capability("nonexistent_capability").status == "unknown"


def test_compile_derives_unsupported_reasons_from_capability_document():
    """P1-1：unsupported 原因从能力文档派生；unknown 能力 fail-closed 并注明 unknown。"""
    backend = FakeOpenShellBackend()  # tools_mcp=unknown、resources=unknown
    compiled = backend.compile(
        _network_policy(tools=[{"name": "shell"}], resources={"cpu": "1"}, audit={"log_requests": True})
    )
    tools_reasons = [r for r in compiled.unsupported_by_backend if r.startswith("tools:")]
    assert tools_reasons and "unknown" in tools_reasons[0] and "fail-closed" in tools_reasons[0]
    resources_reasons = [r for r in compiled.unsupported_by_backend if r.startswith("resources:")]
    assert resources_reasons and "unknown" in resources_reasons[0]
    audit_reasons = [r for r in compiled.unsupported_by_backend if r.startswith("audit:")]
    assert audit_reasons and "audit_events" in audit_reasons[0]


def test_compile_enforcement_mode_checked_against_capability_document():
    """P1-11：执行模式按能力文档判定；Fake 全模式 supported → 不进 unsupported 列表。"""
    backend = FakeOpenShellBackend(dynamic_network_update=True)
    for mode in ("audit_only", "warn", "block"):
        compiled = backend.compile(_network_policy(enforcement_mode=mode))
        assert not any(r.startswith("enforcement_mode.") for r in compiled.unsupported_by_backend), mode


def test_verify_report_level_is_readback_not_enforcement():
    """P1-2：Fake 只有状态读回，无行为 fixture → readback_verified，绝不 enforcement_verified。"""
    backend = FakeOpenShellBackend(dynamic_network_update=True)
    compiled = backend.compile(_network_policy())
    receipt = backend.apply_dynamic("sandbox-5", backend.plan_change("sandbox-5", compiled), "0")
    report = backend.verify(
        "sandbox-5",
        checks={"expect_allow": ["api.example.com:443/orders/**"], "expect_deny": ["evil.example.com"]},
        receipt=receipt,
    )
    assert report.passed is True
    assert report.level == "readback_verified"
    # checks 携带 request/expected/actual/revision 供审计复核
    check = report.allow_checks[0]
    assert check["expected"] == "allow" and check["actual"] == "allow"
    assert check["request"] == "config_readback" and check["revision"] == receipt.backend_revision


def test_stream_events_source_is_labeled():
    """P1-2：事件批次如实标注来源，不伪装行为事件流。"""
    backend = FakeOpenShellBackend(dynamic_network_update=True)
    batch = backend.stream_events()
    assert batch.source == "fake_backend_log"
