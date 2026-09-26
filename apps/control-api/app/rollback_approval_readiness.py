"""内部只读就绪度核对：**独立回滚审批**当前能不能成立、缺哪几条、哪些无法由记录判定。

本模块只回答一个问题：把既有代码与既有记录按下面 7 条要求逐条对照，**哪几条有证据、哪几条没有**。
它**不是**审批实现、**不是** HTTP 接口、**不是** 回滚执行器：不写库、不产生审计/outbox/任务、
不发起外部探测、不扫描宿主，`runtime_effect` 恒为 `"none"`。

**为什么要有这一层**：当前回滚链只做**同一侧的活体授权链重查**（`app/routers/policies.py` 的
`authorize_rollback`：绑定仍权威、目标权威未变、端点指纹与回执一致）。那是**执行前复验**，
证明"提交的意图仍与当前状态一致"；**独立审批**证明的是另一件事——"**另一个身份**为**这一次具体操作**
承担了责任"。两者都必要，但**不可互相替代**，本条只把这个缺口如实记下来，不假装它已被复验覆盖。

**三条不变量（写死在判定里，测试逐条钉住）**：

1. **声明不是证据**：任何"合同里写了/字段已声明"的项一律记 `declared_only`，**不计入**成立。
2. **不可观测就是不可观测**：本层看不到人的身份（谁批的、批的人是否等于申请人），所以这类项
   即使被自述为 `present`，也**降级**为 `not_determinable` —— **自述不得越过不可观测性**。
3. **本层不产生任何运行时效果**：即便 7 条全部有证据，结论也只能是
   `rollback_approval_requirements_met_but_not_wired`，**永远不会**是"审批已生效"；
   `enforcement_verified` 与 `effective` 都**不由本层产生**（保留值的唯一合法生产者见执行记录 R09.2）。

**一处必须说清的可达性**：由不变量 2 直接推出——第 3 条要求
（`approver_differs_from_requester`）在本层**不可观测**，任何取值都降级为 `not_determinable`，
因此 `met = 全部 present` **恒为假**，`rollback_approval_requirements_met_but_not_wired`
这一档**经由本层不可达**。保留该档不是为了宣称可达，而是为了把上限写死：
**"全部成立"也只是"未接线"**。真正的"全部成立"必须由本层之外的、能给出独立审批者身份与
一次性操作绑定的生产者来举证——那不是本模块的职责，本模块也不假装拥有它。
"""

from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "enterprise-rollback-approval-readiness/v1"

# 就绪状态词表（固定四值）。没有"部分成立"，也没有"趋势向好"这种说法。
PRESENT = "present"
ABSENT = "absent"
DECLARED_ONLY = "declared_only"
NOT_DETERMINABLE = "not_determinable"
STATUSES = (PRESENT, ABSENT, DECLARED_ONLY, NOT_DETERMINABLE)

# 结论词表：**没有**"审批已生效"这一档，也不设"总体安全/不安全"。
NOT_READY = "rollback_approval_not_ready"
REQUIREMENTS_MET_BUT_NOT_WIRED = "rollback_approval_requirements_met_but_not_wired"
CONCLUSIONS = (NOT_READY, REQUIREMENTS_MET_BUT_NOT_WIRED)

# 本层对运行时的影响恒为 none：它不接线、不开关、不改变 authorize_rollback 的现有语义。
RUNTIME_EFFECT = "none"

# 固定原因码（不得临时拼字符串）。
REASON_CODES = frozenset({
    "no_independent_approver_identity",
    "live_chain_recheck_is_owner_side",
    "requester_equals_operator_unobservable",
    "no_approval_record_bound_to_operation",
    "no_approval_validity_window",
    "no_revocation_path",
    "approval_audit_not_in_same_transaction",
    "request_body_override_only_declared",
    "declaration_is_not_evidence",
    "human_identity_cannot_be_observed_by_this_layer",
    "fact_value_unrecognized",
    "fact_missing",
})

# 7 条要求。`evidence_source_today` 写的是**今天**能从哪读到（有就写，没有就明写没有），
# 不是"应该在哪读到"。`status_today` 是 2026-09-26 的实测结论，随实现变化需重测。
REQUIREMENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "independent_approver_identity",
        "name": "存在**独立**审批者身份（不是执行者、不是请求者）",
        "why": "回滚是破坏性动作；责任必须落到第二个可识别身份上，而不是同一个操作者的复核。",
        "evidence_source_today": "无。回滚链上只有调用者身份与 `authorize_rollback` 的活体重查。",
        "status_today": ABSENT,
        "reason_today": "no_independent_approver_identity",
    },
    {
        "id": "live_chain_recheck_is_not_approval",
        "name": "不把执行前复验**冒充**独立审批",
        "why": "复验与审批是两件事：复验证明意图未漂移，审批证明有人为这次操作担责。",
        "evidence_source_today": "`app/routers/policies.py` 的 `authorize_rollback` 只做绑定/目标/指纹复验。",
        "status_today": ABSENT,
        "reason_today": "live_chain_recheck_is_owner_side",
    },
    {
        "id": "approver_differs_from_requester",
        "name": "审批者 ≠ 申请者 ≠ 操作者（职责分离）",
        "why": "自批自执行会让「审批」退化为一次确认点击。",
        "evidence_source_today": "无法判定：本层看不到人的身份，只能看到令牌/角色。",
        "status_today": NOT_DETERMINABLE,
        "reason_today": "requester_equals_operator_unobservable",
    },
    {
        "id": "approval_bound_to_operation",
        "name": "审批记录与**这一次**操作绑定（operation_id + target + current/restore 摘要）",
        "why": "否则一次审批可以被复用去授权另一次回滚。",
        "evidence_source_today": "无。`deployment.verification.rollback` 只记回滚结果，不记审批来源。",
        "status_today": ABSENT,
        "reason_today": "no_approval_record_bound_to_operation",
    },
    {
        "id": "approval_validity_window",
        "name": "审批有效期（相对执行时刻的窗口）",
        "why": "陈旧审批不得在环境已变化后被当作仍然有效。",
        "evidence_source_today": "无。",
        "status_today": ABSENT,
        "reason_today": "no_approval_validity_window",
    },
    {
        "id": "no_request_body_override",
        "name": "审批证据**不可**由请求正文覆盖",
        "why": "调用方不能自带一份「审批」来绕过审批。",
        "evidence_source_today": "只有声明：`contracts.py` 的 `RollbackAuthorization` 注明"
                                  "「仅由私有操作记录和实时读回构造，不接受请求正文覆盖」。",
        "status_today": DECLARED_ONLY,
        "reason_today": "request_body_override_only_declared",
    },
    {
        "id": "revocation_takes_effect",
        "name": "审批被撤销后，回滚必须被拒",
        "why": "没有撤销路径的审批在现实中不可撤回，等于永久授权。",
        "evidence_source_today": "无。",
        "status_today": ABSENT,
        "reason_today": "no_revocation_path",
    },
)

REQUIREMENT_IDS = tuple(item["id"] for item in REQUIREMENTS)

# 本层看不到、也不许被自述越过的项：人工身份类事实一律降级为 not_determinable。
_UNOBSERVABLE_IDS = frozenset({"approver_differs_from_requester"})

_DECLARATION_VALUES = frozenset({"declared_only", "declared", "documented"})
_PRESENT_VALUES = frozenset({"present", "verified"})
_ABSENT_VALUES = frozenset({"absent", "missing"})


def _classify(requirement_id: str, value: object) -> tuple[str, str]:
    """把一个事实取值判成四值之一，并给出原因码。**任何未识别取值都不得记成立**。

    取值判定**按类型严格**：只有布尔 `True` 或列名字符串才可能记 `present`。
    这里**不能**用集合成员判定（`1 in {True}` 为真、`0.0 in {False}` 为真），
    否则 JSON 里的数字 `1`/`0.0` 会被悄悄当作"成立"——那正是本模块要拒绝的事。
    """
    if value is None:
        return ABSENT, "fact_missing"
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _DECLARATION_VALUES:
            # 不变量 1：声明不是证据。
            return DECLARED_ONLY, "declaration_is_not_evidence"
        if normalized in _PRESENT_VALUES:
            if requirement_id in _UNOBSERVABLE_IDS:
                # 不变量 2：自述 present 不得越过不可观测性。
                return NOT_DETERMINABLE, "human_identity_cannot_be_observed_by_this_layer"
            return PRESENT, ""
        if normalized in _ABSENT_VALUES:
            return ABSENT, "fact_missing"
        return NOT_DETERMINABLE, "fact_value_unrecognized"
    if value is True:
        if requirement_id in _UNOBSERVABLE_IDS:
            return NOT_DETERMINABLE, "human_identity_cannot_be_observed_by_this_layer"
        return PRESENT, ""
    if value is False:
        return ABSENT, "fact_missing"
    return NOT_DETERMINABLE, "fact_value_unrecognized"


def evaluate(facts: Mapping[str, object]) -> dict[str, Any]:
    """按 `facts` 逐条判定。纯函数：不改入参、不读库、不写库、不产生任何运行时效果。

    `facts` 的键是 `REQUIREMENT_IDS` 的子集；缺键等同于 `None`（记 `absent`，**不**记成立）。
    """
    rows: list[dict[str, Any]] = []
    for item in REQUIREMENTS:
        requirement_id = item["id"]
        value = facts[requirement_id] if requirement_id in facts else None
        status, reason = _classify(requirement_id, value)
        if status == PRESENT and not reason:
            reason = ""
        rows.append({
            "id": requirement_id,
            "name": item["name"],
            "status": status,
            "reason": reason,
            "why": item["why"],
            "evidence_source_today": item["evidence_source_today"],
        })
    counts = {status: sum(1 for row in rows if row["status"] == status) for status in STATUSES}
    # 因不变量 2，`approver_differs_from_requester` 永不可能是 present，故本表达式
    # 在**经由本层**时恒为假（`requirements_met_but_not_wired` 不可达，见模块 docstring）。
    # 保留判定本身是为了让"上限"可执行地表达：一旦有本层之外的合法生产者，
    # 结论也必须停在"未接线"，绝不会变成"已生效"。
    met = all(row["status"] == PRESENT for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "requirements": rows,
        "counts": counts,
        "conclusion": REQUIREMENTS_MET_BUT_NOT_WIRED if met else NOT_READY,
        # 不变量 3：即便全条有证据，本层也不产生任何运行时效果。
        "runtime_effect": RUNTIME_EFFECT,
        "independent_approval_supported": False,
        "enforcement_verified_produced": False,
    }


def requirements_table() -> list[dict[str, Any]]:
    """今日事实表（只读快照）：哪几条要求、今天是什么状态、从哪读出来的。"""
    return [dict(item) for item in REQUIREMENTS]
