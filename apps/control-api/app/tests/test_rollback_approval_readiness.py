"""R04 独立回滚审批**只读就绪度核对**的最小验证。

本模块不是 HTTP 接口、不接数据库，故直接对纯函数 `evaluate()` 取值；
测试逐条钉住模块 docstring 里的三条不变量：**声明不是证据**、**自述不得越过不可观测性**、
**本层不产生任何运行时效果**。另有两条边界守卫：对模块源码的**只读性**做静态断言，
以及"不得出现 `effective` / `enforcement_verified` 事实"。
"""
from __future__ import annotations

import ast
from pathlib import Path

from app.rollback_approval_readiness import (
    ABSENT,
    CONCLUSIONS,
    DECLARED_ONLY,
    NOT_DETERMINABLE,
    NOT_READY,
    PRESENT,
    REASON_CODES,
    REQUIREMENT_IDS,
    REQUIREMENTS,
    REQUIREMENTS_MET_BUT_NOT_WIRED,
    RUNTIME_EFFECT,
    SCHEMA_VERSION,
    STATUSES,
    evaluate,
    requirements_table,
)

MODULE_PATH = Path(__file__).resolve().parents[1] / "rollback_approval_readiness.py"

# 本层看不到人的身份：这一条即便被自述为成立，也必须降级。
UNOBSERVABLE_ID = "approver_differs_from_requester"


def _all_present_facts() -> dict:
    return {requirement_id: True for requirement_id in REQUIREMENT_IDS}


def test_default_facts_are_not_ready_and_never_claim_present():
    """缺键等同 None：一条都不许记成立，结论停在 not_ready。"""
    result = evaluate({})
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["conclusion"] == NOT_READY
    assert result["counts"] == {"present": 0, "absent": len(REQUIREMENT_IDS), "declared_only": 0,
                                "not_determinable": 0}
    assert [row["id"] for row in result["requirements"]] == list(REQUIREMENT_IDS)
    assert all(row["status"] == ABSENT for row in result["requirements"])


def test_declaration_is_never_evidence():
    """不变量 1：声明/文档/字段存在，一律记 declared_only，**不计入**成立。"""
    for value in ("declared_only", "declared", "documented", "  Declared  "):
        result = evaluate({requirement_id: value for requirement_id in REQUIREMENT_IDS})
        assert result["counts"]["present"] == 0, value
        assert result["counts"]["declared_only"] == len(REQUIREMENT_IDS), value
        assert all(row["reason"] == "declaration_is_not_evidence" for row in result["requirements"]), value
        assert result["conclusion"] == NOT_READY, value


def test_unrecognized_value_is_never_treated_as_present():
    """未识别取值不得被当成成立，也不得被静默丢掉：记 not_determinable + 固定原因码。"""
    for value in ("verified_by_someone", 1, 0.0, [], {"ok": True}):
        result = evaluate({requirement_id: value for requirement_id in REQUIREMENT_IDS})
        assert result["counts"]["present"] == 0, value
        assert result["counts"]["not_determinable"] == len(REQUIREMENT_IDS), value
        assert all(row["reason"] == "fact_value_unrecognized" for row in result["requirements"]), value


def test_declared_facts_do_not_reach_met_even_with_nothing_else_missing():
    """关键反例：把每一项都写成"已声明"，结论必须仍是 not_ready（不得变成 met）。"""
    result = evaluate({requirement_id: "declared_only" for requirement_id in REQUIREMENT_IDS})
    assert result["counts"]["present"] == 0
    assert result["conclusion"] == NOT_READY
    assert result["conclusion"] != REQUIREMENTS_MET_BUT_NOT_WIRED


def test_self_reported_present_cannot_cross_unobservability():
    """不变量 2：身份类事实本层看不到，自述 present 必须降级为 not_determinable。"""
    result = evaluate(_all_present_facts())
    downgraded = [row for row in result["requirements"] if row["id"] == UNOBSERVABLE_ID]
    assert len(downgraded) == 1
    assert downgraded[0]["status"] == NOT_DETERMINABLE
    assert downgraded[0]["reason"] == "human_identity_cannot_be_observed_by_this_layer"
    # 其余各项确实被判成立——降级是**针对这一条**的，不是整体失效。
    assert result["counts"]["present"] == len(REQUIREMENT_IDS) - 1
    assert result["conclusion"] == NOT_READY


def test_met_but_not_wired_is_unreachable_through_this_layer():
    """可达性如实钉住：因不变量 2，`requirements_met_but_not_wired` 经由本层不可达。

    这条断言不是"期望的失败"，而是**设计事实**：第 3 条要求在本层不可观测，
    所以 `全部 present` 恒为假。保留该档只为表达上限——「全部成立也只是未接线」。
    """
    assert REQUIREMENTS_MET_BUT_NOT_WIRED in CONCLUSIONS
    assert evaluate(_all_present_facts())["conclusion"] == NOT_READY
    assert evaluate({}).get("conclusion") != REQUIREMENTS_MET_BUT_NOT_WIRED


def test_runtime_effect_is_none_and_no_enforcement_or_effective_fact_is_produced():
    """不变量 3：本层不产生运行时效果，也不得生产 `effective`/`enforcement_verified`。"""
    for facts in ({}, _all_present_facts(), {requirement_id: "declared_only" for requirement_id in REQUIREMENT_IDS}):
        result = evaluate(facts)
        assert result["runtime_effect"] == RUNTIME_EFFECT == "none"
        assert result["independent_approval_supported"] is False
        assert result["enforcement_verified_produced"] is False
        assert result["conclusion"] not in {"effective", "enforced", "enforcement_verified"}
        assert all(row["status"] not in {"effective", "enforcement_verified"} for row in result["requirements"])


def test_reasons_are_drawn_from_the_fixed_vocabulary_only():
    """原因码只能取自固定词表；成立项没有原因码（不得挂一个好看的解释）。"""
    for facts in ({}, _all_present_facts(), {requirement_id: "nonsense" for requirement_id in REQUIREMENT_IDS},
                  {requirement_id: "declared" for requirement_id in REQUIREMENT_IDS}):
        result = evaluate(facts)
        for row in result["requirements"]:
            assert row["status"] in STATUSES, row
            if row["status"] == PRESENT:
                assert row["reason"] == "", row
            else:
                assert row["reason"] in REASON_CODES, row
                assert row["reason"] != "", row


def test_evaluate_is_pure_and_deterministic():
    """纯函数：不改入参、两次调用结果相同、返回值与模块常量不共享可变状态。"""
    facts = {requirement_id: True for requirement_id in REQUIREMENT_IDS}
    snapshot = dict(facts)
    first = evaluate(facts)
    second = evaluate(facts)
    assert facts == snapshot  # 入参未被改动，也未被补键
    assert first == second

    # 改动返回值不得反噬模块常量（否则下一次判定会被污染）。
    first["requirements"][0]["status"] = "tampered"
    first["counts"]["present"] = 999
    assert evaluate(facts) == second
    assert all(item["status_today"] in STATUSES for item in REQUIREMENTS)


def test_requirements_table_is_a_snapshot_of_todays_facts():
    """今日事实表：7 条、id 与顺序稳定、今日状态与原因码都在固定词表内。"""
    table = requirements_table()
    assert len(table) == len(REQUIREMENT_IDS) == 7
    assert [item["id"] for item in table] == list(REQUIREMENT_IDS)
    for item in table:
        assert item["status_today"] in STATUSES
        assert item["reason_today"] in REASON_CODES
        assert item["why"] and item["evidence_source_today"]

    # 今日快照里唯一"有东西"的那条只能是声明：声明不是证据（不变量 1）。
    declared = [item for item in table if item["status_today"] == DECLARED_ONLY]
    assert [item["id"] for item in declared] == ["no_request_body_override"]
    assert declared[0]["reason_today"] == "request_body_override_only_declared"
    assert [item["id"] for item in table if item["status_today"] == PRESENT] == []

    # 返回的是副本：改它不影响下一次读取。
    table[0]["status_today"] = "present"
    assert requirements_table()[0]["status_today"] != "present"


def _code_without_comments_and_strings(source: str) -> str:
    """去掉注释与字符串字面量后的源码。

    必须去掉它们，否则断言会与 docstring 里**说明**这些词的行文相撞——
    本文件要证明的是"代码里没有副作用入口"，而不是"文档里不许提这些词"。
    """
    import io
    import tokenize

    pieces: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.FSTRING_START,
                          tokenize.FSTRING_MIDDLE, tokenize.FSTRING_END):
            continue
        pieces.append(token.string)
    return " ".join(pieces)


def test_module_source_stays_read_only():
    """源码级边界守卫：只允许标准库的纯类型导入，且代码里不得出现任何副作用入口。"""
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported == {"collections.abc", "typing"}, imported

    code = _code_without_comments_and_strings(source)
    for forbidden in ("session_scope", "Session", "httpx", "requests", "subprocess", "open",
                      "commit", "OutboxEvent", "AuditEvent", "enforcement_verified",
                      "effective", "rollback(", "apply"):
        assert forbidden not in code, f"只读边界被突破：代码里出现 {forbidden!r}"
