"""行为 fixture 通道（P0）：校验器逐条拒绝 + 三个后端都不得自行升级。

本文件钉住的**唯一**命题：`enforcement_verified` 只能由"边界内真实行为观测"
经校验器接受后产生。因此测试分两层：

1. **校验器层**（纯逻辑，无 IO）：构造一份合法差分证据，然后**逐条**翻转
   一个字段，断言落回对应的固定判别码。没有"看起来像就放行"的余地；
2. **后端层**：Fake / HTTP 收到一份**完美证据**仍必须退回 readback_verified
   且 `probe_evidence is None`；CLI 只有在证据绑定与本次读回逐项一致时才升级，
   绑定不符时**照常**产出 readback_verified 并留下判别码。

P0 结论档只能是"隔离验证通过"：这里的一切观测都是合成/本地假强制点，
**不构成任何生产行为验证**，也不接线到任何门禁。
"""

from __future__ import annotations

import dataclasses

import httpx
import pytest
from app.adapters.openshell import enforcement_probe as ep
from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.client import OpenShellHttpClient
from app.adapters.openshell.contracts import DeploymentReceipt
from app.adapters.openshell.fake_backend import FakeOpenShellBackend
from app.adapters.openshell.operation_registry import PolicyOperationRegistry

ENDPOINT = "api.example.com:443"
OTHER_ENDPOINT = "collector.example.com:8443"
ALLOW_PATH = "/sandbox/probe-a"
DENY_PATH = "/sandbox/probe-b"
DIGEST = "a" * 64
SCRIPT_SHA = "c" * 64
CONTENT_SHA = "b" * 64


def _obs(outcome: str, *, endpoint: str = ENDPOINT, path: str = ALLOW_PATH,
         sha: str = CONTENT_SHA, origin: str = ep.ORIGIN_SANDBOX_EXEC,
         elapsed_ms: int = 5) -> ep.ProbeObservation:
    return ep.ProbeObservation(
        origin=origin, endpoint=endpoint, outcome=outcome,
        binary_path=path, binary_sha256=sha, elapsed_ms=elapsed_ms,
    )


def _arm(outcome: str, *, endpoint: str = ENDPOINT, path: str = ALLOW_PATH,
         count: int = ep.MIN_ATTEMPTS_PER_ARM, **kwargs) -> list[ep.ProbeObservation]:
    return [_obs(outcome, endpoint=endpoint, path=path, **kwargs) for _ in range(count)]


def _control(endpoint: str = ENDPOINT, outcome: str = ep.OUTCOME_CONNECTED) -> ep.ProbeObservation:
    return _obs(outcome, endpoint=endpoint, path="", sha="", origin=ep.ORIGIN_CONTROL_PLANE_HOST)


def _evidence(**overrides) -> ep.EnforcementProbeEvidence:
    """一份**合法**的主方案证据（同 endpoint / 双 binary path / 同内容）。

    每个测试只翻转它要钉住的那一个字段，因此任一失败都能唯一归因。
    """
    base = dict(
        schema=ep.PROBE_SCHEMA,
        target="siq-as-canary",
        endpoint_fingerprint="fp-canary",
        policy_revision="2",
        applied_policy_digest=DIGEST,
        enforcement_mode="unknown",
        differential=ep.DIFFERENTIAL_SAME_ENDPOINT,
        allow_rule_pairs=[(ENDPOINT, ALLOW_PATH)],
        allow_arm=_arm(ep.OUTCOME_CONNECTED, path=ALLOW_PATH),
        deny_arm=_arm(ep.OUTCOME_REFUSED, path=DENY_PATH),
        reachability_controls=[_control()],
        probe_script_sha256s=[SCRIPT_SHA],
        observed_at="2026-09-26T00:00:00Z",
    )
    base.update(overrides)
    return ep.EnforcementProbeEvidence(**base)


def _expectation(**overrides) -> ep.EnforcementProbeExpectation:
    base = dict(
        endpoint_fingerprint="fp-canary", policy_revision="2", applied_policy_digest=DIGEST,
    )
    base.update(overrides)
    return ep.EnforcementProbeExpectation(**base)


def _check(evidence, expectation=None) -> tuple[bool, str]:
    return ep.validate_enforcement_probe_evidence(
        evidence, _expectation() if expectation is None else expectation
    )


# ---------------------------------------------------------------- 正向

def test_valid_same_endpoint_differential_is_accepted():
    """主方案：同 endpoint、两个 binary 路径、同一份内容、三臂齐 ⇒ 接受。"""
    accepted, reason = _check(_evidence())
    assert accepted is True
    assert reason == ep.REASON_OK


def test_valid_distinct_endpoints_differential_is_accepted():
    """退路：两个 endpoint + 各自的可达性对照 ⇒ 接受（弱一档但结构完整）。"""
    evidence = _evidence(
        differential=ep.DIFFERENTIAL_DISTINCT_ENDPOINTS,
        allow_rule_pairs=[(ENDPOINT, ALLOW_PATH)],
        allow_arm=_arm(ep.OUTCOME_CONNECTED, endpoint=ENDPOINT, path=ALLOW_PATH),
        deny_arm=_arm(ep.OUTCOME_TIMEOUT, endpoint=OTHER_ENDPOINT, path=DENY_PATH),
        reachability_controls=[_control(ENDPOINT), _control(OTHER_ENDPOINT)],
    )
    assert _check(evidence) == (True, ep.REASON_OK)


@pytest.mark.parametrize("mode", ["unknown", "block", "enforce", ""])
def test_readback_mode_unknown_or_block_does_not_block_upgrade(mode):
    """`unknown` **不是**否决理由。

    CLI 路径的 `read_effective_policy` 恒填 unknown（`cli_backend.py` P1-11：
    `policy get --full` 里没有模式字段）。若把 unknown 当否决理由，这道门在
    真实路径上**永远打不开**——那正是本仓库反复拒绝的纸面门禁。
    """
    assert _check(_evidence(enforcement_mode=mode))[0] is True


@pytest.mark.parametrize("mode", ["warn", "audit_only"])
def test_readback_mode_warn_or_audit_only_is_rejected(mode):
    """读回**明确**说"不拦截"时，与行为观测矛盾 ⇒ 从严拒绝。"""
    assert _check(_evidence(enforcement_mode=mode)) == (False, ep.R_MODE)


# ---------------------------------------------------------------- 结构与原点

@pytest.mark.parametrize("evidence,expected", [
    (None, _expectation()),
    (_evidence(), None),
])
def test_missing_evidence_or_expectation_is_rejected(evidence, expected):
    assert ep.validate_enforcement_probe_evidence(evidence, expected) == (False, ep.R_SCHEMA)


def test_unsupported_schema_is_rejected():
    assert _check(_evidence(schema="siq.openshell.enforcement-probe/v2")) == (False, ep.R_SCHEMA)


def test_missing_observed_at_is_rejected():
    assert _check(_evidence(observed_at="")) == (False, ep.R_OBSERVED_AT)


@pytest.mark.parametrize("origin", sorted(ep.REJECTED_PROBE_ORIGINS))
def test_boundary_origin_allowlist_is_rejection_based(origin):
    """非法原点逐个点名拒绝：夹具自述、模拟、读回、网关自报都不算观测。"""
    assert _check(_evidence(allow_arm=_arm(ep.OUTCOME_CONNECTED, origin=origin))) == (False, ep.R_ORIGIN)


def test_deny_arm_origin_outside_allowlist_is_rejected():
    out_of_boundary = _arm(ep.OUTCOME_REFUSED, path=DENY_PATH, origin=ep.ORIGIN_CONTROL_PLANE_HOST)
    assert _check(_evidence(deny_arm=out_of_boundary)) == (False, ep.R_ORIGIN)


def test_reachability_control_must_be_out_of_boundary():
    """对照臂必须来自边界外；否则"对照"与"观测"同源，等于没有对照。"""
    in_boundary = [_obs(ep.OUTCOME_CONNECTED, path="", sha="")]
    assert _check(_evidence(reachability_controls=in_boundary)) == (False, ep.R_ORIGIN)


# ---------------------------------------------------------------- 绑定失效

def test_fingerprint_mismatch_is_rejected():
    assert _check(_evidence(endpoint_fingerprint="fp-other")) == (False, ep.R_FINGERPRINT)


def test_empty_fingerprint_is_rejected():
    assert _check(_evidence(endpoint_fingerprint="")) == (False, ep.R_FINGERPRINT)


def test_revision_mismatch_is_rejected():
    assert _check(_evidence(policy_revision="3")) == (False, ep.R_REVISION)


def test_digest_mismatch_is_rejected():
    assert _check(_evidence(applied_policy_digest="d" * 64)) == (False, ep.R_DIGEST)


def test_non_hex_digest_is_rejected():
    """读回自己给出的 digest 都不是 sha256 ⇒ 绑定比较本身无意义 ⇒ 拒绝。"""
    malformed = "z" * 64
    assert _check(_evidence(applied_policy_digest=malformed), _expectation(applied_policy_digest=malformed)) == (
        False, ep.R_DIGEST_MALFORMED,
    )


def test_missing_probe_script_digest_is_rejected():
    """没有探针脚本摘要 ⇒ 无法证明"跑的是哪份夹具" ⇒ 拒绝。"""
    assert _check(_evidence(probe_script_sha256s=[])) == (False, ep.R_DIGEST_MALFORMED)
    assert _check(_evidence(probe_script_sha256s=["not-a-sha"])) == (False, ep.R_DIGEST_MALFORMED)


def test_arm_binary_digest_must_be_a_sha256():
    assert _check(_evidence(allow_arm=_arm(ep.OUTCOME_CONNECTED, sha=""))) == (False, ep.R_DIGEST_MALFORMED)
    assert _check(_evidence(deny_arm=_arm(ep.OUTCOME_REFUSED, path=DENY_PATH, sha="xyz"))) == (
        False, ep.R_DIGEST_MALFORMED,
    )


# ---------------------------------------------------------------- 各臂形态

def test_allow_arm_needs_at_least_three_attempts():
    assert _check(_evidence(allow_arm=_arm(ep.OUTCOME_CONNECTED, count=2))) == (False, ep.R_ALLOW_INCOMPLETE)


def test_allow_arm_must_be_connected():
    assert _check(_evidence(allow_arm=_arm(ep.OUTCOME_TIMEOUT))) == (False, ep.R_ALLOW_NOT_CONNECTED)


def test_deny_arm_needs_at_least_three_attempts():
    short = _arm(ep.OUTCOME_REFUSED, path=DENY_PATH, count=2)
    assert _check(_evidence(deny_arm=short)) == (False, ep.R_DENY_INCOMPLETE)


def test_deny_arm_connected_is_rejected():
    """拒绝臂真的连上了 ⇒ 策略没在这条路上生效 ⇒ 不得升级。"""
    assert _check(_evidence(deny_arm=_arm(ep.OUTCOME_CONNECTED, path=DENY_PATH))) == (False, ep.R_DENY_NOT_BLOCKED)


@pytest.mark.parametrize("outcome", [ep.OUTCOME_REFUSED, ep.OUTCOME_RESET, ep.OUTCOME_DNS, ep.OUTCOME_TIMEOUT])
def test_every_block_like_outcome_counts_as_blocked(outcome):
    """被拦的形态是词表化的：拒绝/重置/DNS 失败/超时都算（超时另需对照，见下）。"""
    assert _check(_evidence(deny_arm=_arm(outcome, path=DENY_PATH)))[0] is True


def test_inconsistent_deny_arm_is_rejected():
    """三次形态必须一致；混合形态说明现象不可复现 ⇒ inconclusive。"""
    mixed = _arm(ep.OUTCOME_REFUSED, path=DENY_PATH, count=2) + _arm(ep.OUTCOME_RESET, path=DENY_PATH, count=1)
    assert _check(_evidence(deny_arm=mixed)) == (False, ep.R_DENY_INCONSISTENT)


def test_out_of_vocabulary_outcome_is_rejected():
    """词表外的形态（例如夹具自述"blocked"）既不算被拦、也不算连上 ⇒ 作废。"""
    assert _check(_evidence(deny_arm=_arm("blocked", path=DENY_PATH))) == (False, ep.R_DENY_INCONSISTENT)


def test_probe_self_error_is_neither_connected_nor_blocked():
    """探针自身出错（`probe_error`）绝不能被当成"被拦住了"来充数。"""
    assert _check(_evidence(allow_arm=_arm(ep.OUTCOME_ERROR))) == (False, ep.R_ALLOW_NOT_CONNECTED)
    assert _check(_evidence(deny_arm=_arm(ep.OUTCOME_ERROR, path=DENY_PATH))) == (False, ep.R_DENY_NOT_BLOCKED)


# ---------------------------------------------------------------- 可达性对照

def test_missing_reachability_control_is_rejected():
    assert _check(_evidence(reachability_controls=[])) == (False, ep.R_CONTROL_MISSING)


def test_unreachable_control_is_rejected():
    """对照自己都连不上 ⇒ 无法排除"整条路是死的" ⇒ 拒绝。"""
    assert _check(_evidence(reachability_controls=[_control(outcome=ep.OUTCOME_REFUSED)])) == (
        False, ep.R_CONTROL_NOT_CONNECTED,
    )


def test_timeout_deny_arm_without_its_own_control_is_rejected():
    """`timeout` 也可能是路由黑洞：没有该 endpoint 的对照就不成立。"""
    evidence = _evidence(
        deny_arm=_arm(ep.OUTCOME_TIMEOUT, endpoint=OTHER_ENDPOINT, path=DENY_PATH),
        reachability_controls=[_control(ENDPOINT)],
    )
    assert _check(evidence) == (False, ep.R_DENY_TIMEOUT_NO_CONTROL)


def test_deny_endpoint_outside_controls_is_rejected():
    evidence = _evidence(
        deny_arm=_arm(ep.OUTCOME_REFUSED, endpoint=OTHER_ENDPOINT, path=DENY_PATH),
        reachability_controls=[_control(ENDPOINT)],
    )
    assert _check(evidence) == (False, ep.R_CONTROL_MISSING)


# ---------------------------------------------------------------- 差分一致性

def test_unsupported_differential_kind_is_rejected():
    assert _check(_evidence(differential="whatever")) == (False, ep.R_DIFF_KIND)


def test_same_endpoint_differential_requires_identical_endpoint():
    evidence = _evidence(
        deny_arm=_arm(ep.OUTCOME_REFUSED, endpoint=OTHER_ENDPOINT, path=DENY_PATH),
        reachability_controls=[_control(ENDPOINT), _control(OTHER_ENDPOINT)],
    )
    assert _check(evidence) == (False, ep.R_DIFF_SAME_ENDPOINT)


def test_same_endpoint_differential_requires_distinct_binary_paths():
    """两条臂用同一个绝对路径 ⇒ 唯一变量不是策略 ⇒ 拒绝。"""
    assert _check(_evidence(deny_arm=_arm(ep.OUTCOME_REFUSED, path=ALLOW_PATH))) == (
        False, ep.R_DIFF_BINARY_DISTINCT,
    )


def test_same_endpoint_differential_requires_identical_binary_content():
    """两个路径必须是**同一份内容**：否则"差别"可能只是两份不同的探针。"""
    assert _check(_evidence(deny_arm=_arm(ep.OUTCOME_REFUSED, path=DENY_PATH, sha="e" * 64))) == (
        False, ep.R_DIFF_BINARY_CONTENT,
    )


def test_multiple_endpoints_in_allow_arm_are_rejected():
    mixed = _arm(ep.OUTCOME_CONNECTED, count=2) + _arm(ep.OUTCOME_CONNECTED, endpoint=OTHER_ENDPOINT, count=1)
    assert _check(_evidence(allow_arm=mixed)) == (False, ep.R_DENY_INCONSISTENT)


def test_distinct_endpoints_differential_rejects_equal_endpoints():
    evidence = _evidence(
        differential=ep.DIFFERENTIAL_DISTINCT_ENDPOINTS,
        deny_arm=_arm(ep.OUTCOME_REFUSED, path=DENY_PATH),
    )
    assert _check(evidence) == (False, ep.R_DIFF_ENDPOINTS)


# ---------------------------------------------------------------- 与写面自洽

def test_allow_arm_pair_must_be_in_written_allow_set():
    """允许臂的 (endpoint, path) 必须在**这次写进去的**规则里，否则无法归因。"""
    assert _check(_evidence(allow_rule_pairs=[])) == (False, ep.R_ALLOW_PAIR)
    assert _check(_evidence(allow_rule_pairs=[(OTHER_ENDPOINT, ALLOW_PATH)])) == (False, ep.R_ALLOW_PAIR)


def test_deny_arm_pair_must_not_be_in_written_allow_set():
    """拒绝臂的 (endpoint, path) 若也在允许集里，就不是"被策略拦住"。"""
    evidence = _evidence(allow_rule_pairs=[(ENDPOINT, ALLOW_PATH), (ENDPOINT, DENY_PATH)])
    assert _check(evidence) == (False, ep.R_DENY_PAIR)


# ---------------------------------------------------------------- 后端层：不得自行升级

_DESIRED_NETWORK_POLICY = {
    "policy_id": "pol-probe",
    "version": 1,
    "selector": {"agent_ids": ["agt_1"]},
    "network": [
        {"endpoint": ENDPOINT, "effect": "allow", "binary_paths": [ALLOW_PATH]},
    ],
    "enforcement_mode": "block",
    "status": "approved",
}


def test_fake_backend_ignores_probe_evidence_and_stays_readback():
    """Fake 无边界内通道：收到一份**完美证据**也必须只给 readback_verified。"""
    backend = FakeOpenShellBackend(dynamic_network_update=True)
    compiled = backend.compile(_DESIRED_NETWORK_POLICY)
    plan = backend.plan_change("s1", compiled)
    receipt = backend.apply_dynamic("s1", plan, expected_revision="0")
    report = backend.verify(
        "s1",
        checks={"expect_allow": [ENDPOINT], "expect_deny": [OTHER_ENDPOINT]},
        receipt=receipt,
        probe_evidence=_evidence(),
    )
    assert report.passed is True, report.failures
    assert report.level == "readback_verified"
    assert report.probe_evidence is None
    assert backend.probe().capability("enforcement_probe").status == "unsupported"


def test_http_client_ignores_probe_evidence_and_stays_readback():
    """HTTP 后端同理：能力文档未报告该通道 ⇒ 非 supported，且绝不据此上调级别。"""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/health"):
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/capabilities"):
            return httpx.Response(200, json={"capabilities": {}})
        return httpx.Response(200, json={
            "revision": "2",
            "policy": {"version": 1, "network_policies": {
                "managed": {"name": "managed",
                            "endpoints": [{"host": "api.example.com", "port": 443}],
                            "binaries": [{"path": ALLOW_PATH}]},
            }},
        })

    client = OpenShellHttpClient("https://gw.test", transport=httpx.MockTransport(handler))
    snapshot = client.read_effective_policy("s1")
    report = client.verify(
        "s1",
        checks={"expect_allow": [ENDPOINT], "expect_deny": [OTHER_ENDPOINT]},
        receipt=DeploymentReceipt(
            backend_revision=snapshot.revision, applied_policy_digest=snapshot.policy_digest, evidence={},
        ),
        probe_evidence=_evidence(),
    )
    assert report.probe_evidence is None
    assert report.level != "enforcement_verified"
    assert client.probe().capability("enforcement_probe").status != "supported"


# ---- CLI 后端：升级只能由校验器决定，且绑定必须与本次读回逐项一致 ----

GATEWAY_INFO = "Gateway Info\n  Gateway: siq-openshell-dev\n  Gateway endpoint: https://127.0.0.1:17671\n"
STATUS_OK = "Server Status\n  Gateway: siq-openshell-dev\n  Gateway version: 0.0.104\n"

POLICY_WITH_NET = """Version:      2
Active:       2
---
version: 1
filesystem_policy:
  include_workdir: true
  read_only:
  - /usr
  read_write:
  - /sandbox
landlock:
  compatibility: best_effort
process:
  run_as_user: sandbox
  run_as_group: sandbox
network_policies:
  siq_rule_0:
    name: siq-rule-0
    endpoints:
    - host: api.example.com
      port: 443
    binaries:
    - path: /sandbox/probe-a
"""


def _cli_backend(fingerprint: str = "fp-canary") -> OpenShellCliBackend:
    def runner(args: list[str]) -> tuple[int, str, str]:
        if tuple(args) == ("policy", "get", "s1", "--full"):
            return 0, POLICY_WITH_NET, ""
        return 1, "", f"unexpected args: {tuple(args)}"

    backend = OpenShellCliBackend(
        runner=runner, env_script="/nonexistent/env.sh", operation_registry=PolicyOperationRegistry(),
    )
    # 生产路径上该值由 status 握手写入；此处直接给定，避免测试依赖环境变量。
    backend._detected_fingerprint = fingerprint
    return backend


def _cli_report(backend, evidence):
    snapshot = backend.read_effective_policy("s1")
    return backend.verify(
        "s1",
        checks={"expect_allow": [ENDPOINT], "expect_deny": [OTHER_ENDPOINT]},
        receipt=DeploymentReceipt(
            backend_revision=snapshot.revision, applied_policy_digest=snapshot.policy_digest, evidence={},
        ),
        probe_evidence=evidence,
    )


def _cli_evidence(**overrides) -> ep.EnforcementProbeEvidence:
    """按**本次读回**的实际 revision/digest 绑定证据，只翻转调用方指定的字段。"""
    base = dict(
        endpoint_fingerprint="fp-canary",
        policy_revision="2",
        applied_policy_digest=_readback_digest(),
    )
    base.update(overrides)
    return _evidence(**base)


def _readback_digest() -> str:
    return _cli_backend().read_effective_policy("s1").policy_digest


def test_cli_backend_without_probe_evidence_stays_readback():
    """不传证据：即便三臂齐全也不存在，级别只能是 readback_verified。"""
    report = _cli_report(_cli_backend(), None)
    assert report.level == "readback_verified"
    assert report.probe_evidence is None
    assert report.probe_reject_reason == ""


def test_cli_backend_upgrades_only_with_accepted_evidence():
    report = _cli_report(_cli_backend(), _cli_evidence())
    assert report.level == "enforcement_verified"
    assert report.probe_evidence is not None
    assert report.probe_reject_reason == ""


def test_cli_backend_keeps_readback_and_records_reject_reason():
    """绑定与本次读回不一致 ⇒ 照常 readback_verified + 固定判别码，绝不静默。"""
    report = _cli_report(_cli_backend(), _cli_evidence(policy_revision="9"))
    assert report.level == "readback_verified"
    assert report.probe_evidence is None
    assert report.probe_reject_reason == ep.R_REVISION


def test_cli_backend_rejects_when_readback_says_not_blocking(monkeypatch):
    """读回明确说 warn ⇒ 即使证据完全合格也不升级（矛盾时从严）。"""
    backend = _cli_backend()
    original = backend.read_effective_policy

    def patched(target: str):
        return dataclasses.replace(original(target), enforcement_mode="warn")

    monkeypatch.setattr(backend, "read_effective_policy", patched)
    report = _cli_report(backend, _cli_evidence())
    assert report.level == "readback_verified"
    assert report.probe_evidence is None


def test_cli_backend_rejects_forged_evidence_from_control_plane():
    """边界外原点的"观测"混进允许臂 ⇒ 拒绝，且判别码是原点而非其它。"""
    forged = _cli_evidence(allow_arm=_arm(ep.OUTCOME_CONNECTED, origin=ep.ORIGIN_CONTROL_PLANE_HOST))
    report = _cli_report(_cli_backend(), forged)
    assert report.level == "readback_verified"
    assert report.probe_reject_reason == ep.R_ORIGIN


def test_cli_capability_document_states_channel_exists_but_unmeasured():
    """能力文档如实标注：通道已实现，但 binary 归因前提未在真实目标上实测。"""
    def runner(args: list[str]) -> tuple[int, str, str]:
        key = tuple(args)
        if key == ("gateway", "info"):
            return 0, GATEWAY_INFO, ""
        if key == ("status",):
            return 0, STATUS_OK, ""
        return 1, "", f"unexpected args: {key}"

    backend = OpenShellCliBackend(
        runner=runner, env_script="/nonexistent/env.sh", operation_registry=PolicyOperationRegistry(),
    )
    item = backend.probe().capability("enforcement_probe")
    assert item.status == "unknown"
    assert "未" in item.basis


def test_evidence_to_dict_carries_no_policy_body_or_secret():
    """审计表示只含摘要与形态：不含策略正文、不含凭据。"""
    payload = _evidence().to_dict()
    assert set(payload) == {
        "schema", "target", "endpoint_fingerprint", "policy_revision", "applied_policy_digest",
        "enforcement_mode", "differential", "allow_rule_pairs", "allow_arm", "deny_arm",
        "reachability_controls", "probe_script_sha256s", "observed_at",
    }
    flat = repr(payload)
    assert "password" not in flat and "token" not in flat and "secret" not in flat
