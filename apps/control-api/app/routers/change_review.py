"""Bounded, identity-bound review snapshots; legacy decision routes remain compatible."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ChangeRequest, DesiredPolicy
from app.routers.policies import (
    _MODE_RANK,
    _approve_change_request,
    _desired_from_policy,
    _reject_change_request,
    _validate_policy_static,
)
from app.rulepack import load_rulepack
from app.schemas import ChangeRequestOut
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["policies"])
_SENSITIVE_KEY = re.compile(
    r"^(?:password|passwd|(?:access[_-]?|refresh[_-]?|id[_-]?)?token|credentials?|authorization|"
    r"api[_-]?key|private[_-]?key|signing[_-]?key|client[_-]?secret|secret(?:[_-]?(?:value|key))?)$",
    re.I,
)
_DOMAINS = {
    "selector": "适用对象（技术标识）",
    "filesystem": "文件访问",
    "network": "网络访问",
    "process": "进程约束",
    "model_routing": "模型路由",
    "tools": "工具清单",
    "tool_policies": "工具权限",
    "data_scope_refs": "数据范围引用",
    "secrets": "凭据引用",
    "resources": "资源限制",
    "audit": "审计要求",
    "exceptions": "例外规则",
}


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Section(Wire):
    key: str = Field(max_length=64)
    label: str = Field(max_length=128)
    content: str = Field(max_length=6000)
    redacted: bool
    truncated: bool


ApproveBlocker = Literal[
    "missing_permission",
    "not_proposed",
    "own_proposal",
    "incomplete_content",
    "policy_invalid",
    "downgrade_requires_high_risk",
]
RejectBlocker = Literal["missing_permission", "not_proposed"]


class ChangeReview(Wire):
    schema_version: Literal["change-review/v1"] = "change-review/v1"
    change_id: str = Field(max_length=256)
    status: str = Field(max_length=64)
    policy_name: str = Field(max_length=6000)
    policy_version: int = Field(ge=1)
    enforcement_mode: Literal["audit_only", "warn", "block"]
    approval_policy: Literal["standard", "high_risk", "break_glass"]
    proposer_id: str = Field(max_length=256)
    approver_id: str | None = Field(max_length=256)
    review_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    sections: list[Section] = Field(max_length=16)
    can_approve: bool
    can_reject: bool
    approve_blockers: list[ApproveBlocker] = Field(max_length=6)
    reject_blockers: list[RejectBlocker] = Field(max_length=2)


class ReviewDecision(Wire):
    schema_version: Literal["change-review-decision/v1"]
    decision: Literal["approve", "reject"]
    review_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _section(key: str, label: str, value: object, rules: tuple) -> Section:
    redacted = False
    truncated = False
    nodes = 0

    def clean(item: object, depth: int = 0) -> object:
        nonlocal redacted, truncated, nodes
        nodes += 1
        if nodes > 1000 or depth > 16:
            truncated = True
            return "[内容超出审查上限]"
        if isinstance(item, dict):
            result = {}
            for index, (k, v) in enumerate(item.items()):
                if index >= 1000 or nodes > 1000:
                    truncated = True
                    break
                safe_key = str(clean(str(k), depth + 1))
                if _SENSITIVE_KEY.search(str(k)):
                    redacted = True
                    result[safe_key] = "[已隐藏敏感字段]"
                else:
                    result[safe_key] = clean(v, depth + 1)
            return result
        if isinstance(item, list):
            result = []
            for v in item:
                if nodes > 1000:
                    truncated = True
                    break
                result.append(clean(v, depth + 1))
            return result
        if isinstance(item, str):
            # Do not return a long prefix that might split an unrecognised secret.
            if len(item) > 6000:
                truncated = True
                return "[文本超出审查上限]"
            safe = item
            for rule in rules:
                safe = rule.pattern.sub(rule.replacement, safe)
            redacted |= safe != item
            return safe
        return item

    safe = clean(value)
    content = (
        json.dumps(safe, ensure_ascii=False, indent=2) if value is not None else "未配置（具体默认行为由执行后端决定）"
    )
    if len(content) > 6000:
        content = "内容超出审查上限，请拆分策略后重新提交。"
        truncated = True
    return Section(key=key, label=label, content=content, redacted=redacted, truncated=truncated)


def _locate(session: Session, identity: Identity, cr_id: str, *, lock: bool = False):
    query = select(ChangeRequest).where(ChangeRequest.id == cr_id, ChangeRequest.tenant_id == identity.tenant_id)
    cr = session.scalar(query.with_for_update() if lock else query)
    if cr is None:
        raise HTTPException(404, "not_found")
    ensure_permission(identity, "policy:read")
    query = select(DesiredPolicy).where(DesiredPolicy.id == cr.policy_id, DesiredPolicy.tenant_id == identity.tenant_id)
    policy = session.scalar(query.with_for_update() if lock else query)
    if policy is None:
        raise HTTPException(404, "not_found")
    return cr, policy


def _snapshot(session: Session, identity: Identity, cr: ChangeRequest, policy: DesiredPolicy) -> ChangeReview:
    previous = session.scalar(
        select(DesiredPolicy)
        .where(
            DesiredPolicy.tenant_id == identity.tenant_id,
            DesiredPolicy.name == policy.name,
            DesiredPolicy.version < policy.version,
        )
        .order_by(DesiredPolicy.version.desc(), DesiredPolicy.id)
    )
    previous_basis = (
        {"id": previous.id, "mode": previous.enforcement_mode, "status": previous.status} if previous else None
    )
    desired = _desired_from_policy(policy)
    _, _, rules = load_rulepack()
    title = _section("name", "策略名称", policy.name, rules)
    sections = [_section(key, label, desired[key], rules) for key, label in _DOMAINS.items()]
    sections += [
        _section("impact", "申请人填写的用途与影响（尚未经系统核验）", cr.impact, rules),
        _section("validation", "校验提示", policy.unsupported_by_backend, rules),
        _section("previous", "前一版本模式（不代表当前运行时状态）", previous_basis, rules),
    ]
    reject: list[RejectBlocker] = []
    if not identity.has_permission("change:approve"):
        reject.append("missing_permission")
    if cr.status != "proposed":
        reject.append("not_proposed")
    approve: list[ApproveBlocker] = list(reject)
    if cr.proposer_user_id == identity.actor_id:
        approve.append("own_proposal")
    if any(s.redacted or s.truncated for s in [title, *sections]):
        approve.append("incomplete_content")
    if policy.status != "validated" or _validate_policy_static(policy):
        approve.append("policy_invalid")
    if (
        previous
        and previous.status not in ("rejected", "failed")
        and _MODE_RANK[policy.enforcement_mode] < _MODE_RANK.get(previous.enforcement_mode, -1)
        and cr.approval_policy != "high_risk"
    ):
        approve.append("downgrade_requires_high_risk")
    digest = hashlib.sha256(
        json.dumps(
            {
                "version": "change-review/v1",
                "tenant": identity.tenant_id,
                "actor": identity.actor_id,
                "actor_type": identity.identity_type,
                "change": cr.id,
                "status": cr.status,
                "proposer": cr.proposer_user_id,
                "approver": cr.approver_user_id,
                "approval_policy": cr.approval_policy,
                "impact": cr.impact,
                "diff": cr.diff,
                "policy": desired,
                "name": policy.name,
                "validation": policy.unsupported_by_backend,
                "previous": previous_basis,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return ChangeReview(
        change_id=cr.id,
        status=cr.status,
        policy_name=json.loads(title.content) if not title.truncated else "名称过长",
        policy_version=policy.version,
        enforcement_mode=policy.enforcement_mode,
        approval_policy=cr.approval_policy,
        proposer_id=cr.proposer_user_id,
        approver_id=cr.approver_user_id,
        review_digest=digest,
        sections=sections,
        can_approve=not approve,
        can_reject=not reject,
        approve_blockers=approve,
        reject_blockers=reject,
    )


@router.get("/api/v1/change-requests/{cr_id}/review", response_model=ChangeReview)
def get_review(
    cr_id: str, response: Response, session: Session = Depends(get_session), identity: Identity = Depends(get_identity)
):
    cr, policy = _locate(session, identity, cr_id)
    response.headers["Cache-Control"] = "no-store"
    return _snapshot(session, identity, cr, policy)


@router.post("/api/v1/change-requests/{cr_id}/review-decision", response_model=ChangeRequestOut)
def review_decision(
    cr_id: str,
    body: ReviewDecision,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    cr, policy = _locate(session, identity, cr_id, lock=True)
    ensure_permission(identity, "change:approve")
    current = _snapshot(session, identity, cr, policy)
    if not hmac.compare_digest(body.review_digest, current.review_digest):
        raise HTTPException(409, "review_changed")
    blockers = current.approve_blockers if body.decision == "approve" else current.reject_blockers
    if blockers:
        raise HTTPException(409, f"review_blocked:{blockers[0]}")
    apply = _approve_change_request if body.decision == "approve" else _reject_change_request
    return apply(cr, session, identity, review_digest=current.review_digest)
