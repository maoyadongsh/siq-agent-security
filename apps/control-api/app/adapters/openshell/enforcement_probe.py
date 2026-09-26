"""行为 fixture 通道：证据结构与校验器（P0，纯逻辑，不产生事实）。

本模块回答的是**一个**问题：一份"边界内行为观测"证据，是否足以支撑把验证级别
提到 `enforcement_verified`。它**自己不是**生产者——真正的观测由
`probe_channel.py` 在边界内取回，判定由这里做，且判定是**拒绝式**的：
任何一条必需条件不满足，就给出固定判别码并拒绝升级，绝不给"看起来像"留口子。

三条设计不变量（方案 §2，逐条落到代码）：

1. **观测必须在边界内发起**（`ALLOWED_PROBE_ORIGINS` 只含 `sandbox_exec`）。
2. **判定不在夹具里**：边界内的探针脚本只报告事实（`ProbeObservation`），
   本模块不接受"脚本自述结论"这一形态——`self_report` 一律拒绝。
3. **不确定就不升级**：臂不齐、臂内矛盾、绑定不匹配、执行模式**明确**为
   warn/audit_only，全部落到固定判别码，绝不产生 `enforcement_verified`。
   （读回 `unknown` 不构成否决理由——见校验器内 §执行模式 的说明。）

差分结构（方案 §3）：允许臂必须真的连上，拒绝臂必须是**被拦**形态，
且有一个**边界外**的可达性对照证明该 endpoint 此刻是活的——三段缺一即 `inconclusive`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------ 固定词表

PROBE_SCHEMA = "siq.openshell.enforcement-probe/v1"

#: 边界内观测原点白名单。**拒绝式**：不在此集合内的一切原点都不可用于升级。
ORIGIN_SANDBOX_EXEC = "sandbox_exec"
ALLOWED_PROBE_ORIGINS = frozenset({ORIGIN_SANDBOX_EXEC})

#: 边界外可达性对照的原点（只用于对照，**永不**单独构成证据）。
ORIGIN_CONTROL_PLANE_HOST = "control_plane_host"

#: 明确点名的非法原点：写出来是为了让"它被拒绝"成为一条可测的事实。
REJECTED_PROBE_ORIGINS = frozenset({
    "fixture",
    "simulated",
    "self_report",
    "script_self_report",
    "config_readback",
    "gateway_self_report",
})

OUTCOME_CONNECTED = "connected"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_REFUSED = "connection_refused"
OUTCOME_RESET = "connection_reset"
OUTCOME_DNS = "dns_failure"
#: 词表外的失败（例如探针自身报错）。**既不算连上、也不算被拦** ⇒ 该臂作废。
OUTCOME_ERROR = "probe_error"
PROBE_OUTCOMES = frozenset({
    OUTCOME_CONNECTED, OUTCOME_TIMEOUT, OUTCOME_REFUSED, OUTCOME_RESET, OUTCOME_DNS, OUTCOME_ERROR,
})
#: "被拦住"的可接受形态（"没连上"而不是"连上了"）。
BLOCK_LIKE_OUTCOMES = frozenset({OUTCOME_TIMEOUT, OUTCOME_REFUSED, OUTCOME_RESET, OUTCOME_DNS})

#: 差分档。主方案强、退路弱一档；档位必须显式写进证据，不许事后解释。
DIFFERENTIAL_SAME_ENDPOINT = "same_endpoint_binary_path"
DIFFERENTIAL_DISTINCT_ENDPOINTS = "distinct_endpoints_reachability_controlled"
DIFFERENTIAL_KINDS = frozenset({DIFFERENTIAL_SAME_ENDPOINT, DIFFERENTIAL_DISTINCT_ENDPOINTS})

MIN_ATTEMPTS_PER_ARM = 3
_HEX64 = re.compile(r"[0-9a-f]{64}")

# ------------------------------------------------------------ 判别码

REASON_OK = "probe_evidence_accepted"
R_SCHEMA = "probe_evidence_schema_unsupported"
R_ORIGIN = "probe_origin_not_accepted"
R_FINGERPRINT = "probe_binding_fingerprint_mismatch"
R_TARGET = "probe_binding_target_mismatch"
R_REVISION = "probe_binding_revision_mismatch"
R_DIGEST = "probe_binding_digest_mismatch"
R_MODE = "probe_enforcement_mode_not_block"
R_ALLOW_INCOMPLETE = "probe_allow_arm_incomplete"
R_ALLOW_NOT_CONNECTED = "probe_allow_arm_not_connected"
R_DENY_INCOMPLETE = "probe_deny_arm_incomplete"
R_DENY_NOT_BLOCKED = "probe_deny_arm_not_blocked"
R_DENY_INCONSISTENT = "probe_deny_arm_inconsistent"
R_DENY_TIMEOUT_NO_CONTROL = "probe_deny_timeout_without_reachability_control"
R_CONTROL_MISSING = "probe_reachability_control_missing"
R_CONTROL_NOT_CONNECTED = "probe_reachability_control_not_connected"
R_DIFF_KIND = "probe_differential_kind_unsupported"
R_DIFF_SAME_ENDPOINT = "probe_differential_not_same_endpoint"
R_DIFF_BINARY_DISTINCT = "probe_differential_binary_path_not_distinct"
R_DIFF_BINARY_CONTENT = "probe_differential_binary_content_differs"
R_DIFF_ENDPOINTS = "probe_differential_endpoints_not_distinct"
R_ALLOW_PAIR = "probe_allow_pair_not_in_allow_set"
R_DENY_PAIR = "probe_deny_pair_in_allow_set"
R_DIGEST_MALFORMED = "probe_digest_malformed"
R_OBSERVED_AT = "probe_observed_at_missing"
R_ATTEMPTS = "probe_attempts_insufficient"


# ------------------------------------------------------------ 数据结构


@dataclass(frozen=True)
class ProbeObservation:
    """**单次**观测事实。只描述"发生了什么"，不含"是否符合预期"的判定。"""

    origin: str  # sandbox_exec | control_plane_host
    endpoint: str  # host:port
    outcome: str  # PROBE_OUTCOMES
    binary_path: str = ""  # 边界内绝对路径（对照臂为空）
    binary_sha256: str = ""  # 该路径下文件的摘要
    elapsed_ms: int = 0


@dataclass(frozen=True)
class EnforcementProbeEvidence:
    """一次行为探针运行的完整事实（不含判定）。

    绑定对象 = (target, endpoint_fingerprint, policy_revision, applied_policy_digest)：
    这四项任一变化，证据即失效（与 D-4「不设 TTL、以绑定对象为准」一致）。
    """

    schema: str
    target: str
    endpoint_fingerprint: str
    policy_revision: str
    applied_policy_digest: str
    enforcement_mode: str  # 读回的执行模式；warn/audit_only 一律拒绝，unknown 如实保留
    differential: str
    allow_rule_pairs: list[tuple[str, str]] = field(default_factory=list)  # (endpoint, binary_path)
    allow_arm: list[ProbeObservation] = field(default_factory=list)
    deny_arm: list[ProbeObservation] = field(default_factory=list)
    reachability_controls: list[ProbeObservation] = field(default_factory=list)
    probe_script_sha256s: list[str] = field(default_factory=list)
    observed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """审计可复核的表示。只含摘要与形态，**不含**策略正文或凭据。"""
        return {
            "schema": self.schema,
            "target": self.target,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "policy_revision": self.policy_revision,
            "applied_policy_digest": self.applied_policy_digest,
            "enforcement_mode": self.enforcement_mode,
            "differential": self.differential,
            "allow_rule_pairs": [list(pair) for pair in self.allow_rule_pairs],
            "allow_arm": [_obs(o) for o in self.allow_arm],
            "deny_arm": [_obs(o) for o in self.deny_arm],
            "reachability_controls": [_obs(o) for o in self.reachability_controls],
            "probe_script_sha256s": list(self.probe_script_sha256s),
            "observed_at": self.observed_at,
        }


def _obs(observation: ProbeObservation) -> dict[str, Any]:
    return {
        "origin": observation.origin,
        "endpoint": observation.endpoint,
        "outcome": observation.outcome,
        "binary_path": observation.binary_path,
        "binary_sha256": observation.binary_sha256,
        "elapsed_ms": observation.elapsed_ms,
    }


@dataclass(frozen=True)
class EnforcementProbeExpectation:
    """调用方对本次运行的期望绑定（来自同一次读回快照，不是自述）。"""

    endpoint_fingerprint: str
    policy_revision: str
    applied_policy_digest: str
    target: str


def validate_enforcement_probe_evidence(
    evidence: EnforcementProbeEvidence | None,
    expected: EnforcementProbeExpectation | None,
) -> tuple[bool, str]:
    """判定这份证据能否支撑 `enforcement_verified`。**只返回 (bool, 固定判别码)**。

    判别顺序是确定的：先结构、再绑定、再执行模式、再各臂、最后差分一致性。
    第一个不满足的条件决定判别码——便于测试逐条钉住，也便于人读。
    """
    if evidence is None or expected is None:
        return False, R_SCHEMA
    if evidence.schema != PROBE_SCHEMA:
        return False, R_SCHEMA
    if not evidence.observed_at:
        return False, R_OBSERVED_AT
    if not isinstance(evidence.target, str) or not evidence.target or evidence.target != expected.target:
        return False, R_TARGET

    # --- 绑定：目标已核对；其余三项全等，且不允许空值蒙混 ---
    if not evidence.endpoint_fingerprint or evidence.endpoint_fingerprint != expected.endpoint_fingerprint:
        return False, R_FINGERPRINT
    if not evidence.policy_revision or evidence.policy_revision != expected.policy_revision:
        return False, R_REVISION
    if (
        not evidence.applied_policy_digest
        or evidence.applied_policy_digest != expected.applied_policy_digest
    ):
        return False, R_DIGEST
    if not _hex64(evidence.applied_policy_digest):
        return False, R_DIGEST_MALFORMED
    for digest in evidence.probe_script_sha256s:
        if not _hex64(digest):
            return False, R_DIGEST_MALFORMED
    if not evidence.probe_script_sha256s:
        return False, R_DIGEST_MALFORMED

    # --- 执行模式：**矛盾时从严** ---
    #
    # 不能要求"读回必须是 block"：CLI 路径的 `read_effective_policy` 刻意恒填
    # `unknown`（`cli_backend.py:542-544`，P1-11：`policy get --full` 输出里根本没有
    # 模式字段）。若把 `unknown` 当否决理由，这道门**在真实路径上永远打不开**——
    # 那正是本仓库反复拒绝的"纸面门禁"。而"边界内拒绝臂真的被拦住"本身就是
    # **比读回更强的直接事实**。
    # 因此规则是：读回**明确**是非拦截模式（warn / audit_only）时一律拒绝
    # （此时行为观测与配置自述矛盾，从严）；`unknown` 不作为否决理由，但会在
    # 证据里如实保留为 unknown，读证据的人能看见这一点。
    if evidence.enforcement_mode in {"warn", "audit_only"}:
        return False, R_MODE

    # --- 原点白名单：拒绝式 ---
    for observation in evidence.allow_arm + evidence.deny_arm:
        if observation.origin not in ALLOWED_PROBE_ORIGINS:
            return False, R_ORIGIN
    for observation in evidence.reachability_controls:
        if observation.origin != ORIGIN_CONTROL_PLANE_HOST:
            return False, R_ORIGIN

    # --- 各臂形态 ---
    if len(evidence.allow_arm) < MIN_ATTEMPTS_PER_ARM:
        return False, R_ALLOW_INCOMPLETE
    if any(o.outcome not in PROBE_OUTCOMES for o in evidence.allow_arm + evidence.deny_arm):
        return False, R_DENY_INCONSISTENT
    if any(o.outcome != OUTCOME_CONNECTED for o in evidence.allow_arm):
        return False, R_ALLOW_NOT_CONNECTED
    if any(not _hex64(o.binary_sha256) for o in evidence.allow_arm):
        return False, R_DIGEST_MALFORMED

    if len(evidence.deny_arm) < MIN_ATTEMPTS_PER_ARM:
        return False, R_DENY_INCOMPLETE
    if any(o.outcome not in BLOCK_LIKE_OUTCOMES for o in evidence.deny_arm):
        return False, R_DENY_NOT_BLOCKED
    if len({o.outcome for o in evidence.deny_arm}) != 1:
        return False, R_DENY_INCONSISTENT
    if any(not _hex64(o.binary_sha256) for o in evidence.deny_arm):
        return False, R_DIGEST_MALFORMED

    # --- 可达性对照：拒绝臂涉及的每个 endpoint 都必须被独立证明"此刻是活的" ---
    if not evidence.reachability_controls:
        return False, R_CONTROL_MISSING
    if any(o.outcome != OUTCOME_CONNECTED for o in evidence.reachability_controls):
        return False, R_CONTROL_NOT_CONNECTED
    controlled = {o.endpoint for o in evidence.reachability_controls if o.outcome == OUTCOME_CONNECTED}
    deny_endpoints = {o.endpoint for o in evidence.deny_arm}
    if not deny_endpoints.issubset(controlled):
        # 特别地：`timeout` 形态的拒绝臂不允许在没有对照的情况下成立（可能是路由黑洞）。
        if any(o.outcome == OUTCOME_TIMEOUT for o in evidence.deny_arm):
            return False, R_DENY_TIMEOUT_NO_CONTROL
        return False, R_CONTROL_MISSING

    # --- 差分一致性 ---
    allow_endpoints = {o.endpoint for o in evidence.allow_arm}
    deny_endpoint = evidence.deny_arm[0].endpoint
    if len(allow_endpoints) != 1 or len(deny_endpoints) != 1:
        return False, R_DENY_INCONSISTENT
    allow_endpoint = next(iter(allow_endpoints))
    if evidence.differential not in DIFFERENTIAL_KINDS:
        return False, R_DIFF_KIND
    if evidence.differential == DIFFERENTIAL_SAME_ENDPOINT:
        if allow_endpoint != deny_endpoint:
            return False, R_DIFF_SAME_ENDPOINT
        allow_paths = {o.binary_path for o in evidence.allow_arm}
        deny_paths = {o.binary_path for o in evidence.deny_arm}
        if len(allow_paths) != 1 or len(deny_paths) != 1 or allow_paths == deny_paths:
            return False, R_DIFF_BINARY_DISTINCT
        # 同一份内容、两个绝对路径：否则"差别"可能只是两份不同的探针。
        if {o.binary_sha256 for o in evidence.allow_arm} != {o.binary_sha256 for o in evidence.deny_arm}:
            return False, R_DIFF_BINARY_CONTENT
    else:
        if allow_endpoint == deny_endpoint:
            return False, R_DIFF_ENDPOINTS

    # --- 与写面规则集自洽：(允许臂, 拒绝臂) 必须一在集内、一在集外 ---
    allow_pairs = {
        (o.endpoint, o.binary_path) for o in evidence.allow_arm
    }
    deny_pairs = {(o.endpoint, o.binary_path) for o in evidence.deny_arm}
    written = set(evidence.allow_rule_pairs)
    if not allow_pairs or not allow_pairs.issubset(written):
        return False, R_ALLOW_PAIR
    if deny_pairs & written:
        return False, R_DENY_PAIR

    return True, REASON_OK


def _hex64(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))
