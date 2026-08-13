"""候选分类服务（设计文档 §11）。

原则（§11.2 模型禁止任务）：
- 分类永远不直接纳管（不改变 asset.status 为 confirmed/managed）；
- 低置信或冲突 → asset.status=needs_review，进入人工确认；
- 输出严格 Schema（§11.3），只含证据引用，不含原始内容；
- classification_run 落库：classifier/model/prompt/schema 版本 + temperature/seed（可追溯重跑）；
- 模型可关闭（SIQ_AS_CLASSIFIER=model-off，默认 baseline）：退化为确定性规则 + 人工确认。
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.models import AgentAsset, ClassificationRun, utcnow

# §11.3 输出 Schema 字段（与设计文档示例一致）
OUTPUT_KEYS = ("is_agent_candidate", "role", "system_candidates", "capability_hints", "unresolved_questions")

CONFIDENCE_THRESHOLD = 0.85  # 低于阈值进入 needs_review（人工确认）

# 确定性基线：角色词表（名称→角色提示）
# 顺序敏感：特化词必须排在通用词（advisor）之前
_ROLE_HINTS = [
    ("legal", "legal-advisor"),
    ("audit", "financial-review-assistant"),
    ("auditor", "financial-review-assistant"),
    ("finance", "financial-review-assistant"),
    ("finreport", "report-assistant"),
    ("risk", "risk-controller"),
    ("sector", "sector-expert"),
    ("strategist", "strategist"),
    ("research", "research-assistant"),
    ("advisor", "advisor"),
]


def _baseline_classify(asset: AgentAsset) -> dict:
    """确定性规则分类：不调用模型。返回 §11.3 Schema 结构。"""
    name = asset.name.lower()
    role_hints = [role for key, role in _ROLE_HINTS if key in name]
    role = role_hints[0] if role_hints else None

    is_agent = bool(role) or any(
        kw in name for kw in ("agent", "assistant", "advisor", "auditor", "controller", "expert")
    )

    unresolved = []
    if role is None:
        unresolved.append("未能从名称归纳业务角色")
    if not asset.owner_user_id:
        unresolved.append("未发现可验证的负责人信息")

    confidence = 0.9 if (is_agent and role) else (0.6 if is_agent else 0.3)
    return {
        "is_agent_candidate": is_agent,
        "role": (
            {"value": role, "confidence": confidence, "evidence_ids": list(asset.evidence_ids or [])}
            if role
            else None
        ),
        "system_candidates": [],
        "capability_hints": [],
        "unresolved_questions": unresolved,
    }


def classifier_mode() -> str:
    return os.getenv("SIQ_AS_CLASSIFIER", "baseline")


def classify_asset(session: Session, tenant_id: str, asset: AgentAsset) -> ClassificationRun:
    """执行分类并落库 classification_run；低置信置 needs_review（绝不自动纳管）。"""
    mode = classifier_mode()
    if mode == "model-off":
        # 显式关闭模型：只记录人工待确认结论，不产生任何自动化结论
        output = {
            "is_agent_candidate": None,
            "role": None,
            "system_candidates": [],
            "capability_hints": [],
            "unresolved_questions": ["模型分类已关闭（SIQ_AS_CLASSIFIER=model-off），等待人工确认"],
        }
    elif mode == "baseline":
        output = _baseline_classify(asset)
    else:
        # provider 模式 Phase 1 后接入；当前拒绝启动而非静默降级
        raise ValueError(f"未支持的分类器模式: {mode}")

    run = ClassificationRun(
        tenant_id=tenant_id,
        asset_id=asset.id,
        classifier=mode,
        model_ref=None,
        prompt_version="siq.classify.prompt.v1",
        schema_version=1,
        temperature=0.0 if mode == "baseline" else None,
        seed=42 if mode == "baseline" else None,
        input_evidence_ids=list(asset.evidence_ids or []),
        output=output,
        created_at=utcnow(),
    )
    session.add(run)

    # 低置信/有未决问题 → needs_review；分类不改变 candidate→confirmed 之外的任何状态
    if asset.status == "candidate":
        confidence = (output.get("role") or {}).get("confidence")
        if output.get("is_agent_candidate") is False or (confidence is not None and confidence < CONFIDENCE_THRESHOLD):
            asset.status = "needs_review"
    return run
