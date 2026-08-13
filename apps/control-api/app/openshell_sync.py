"""OpenShell 有效权限同步（Permission Resolver 的 OpenShell 域，设计文档 §12.4）。

- 从真实网关（经 OpenShellCliBackend）拉取沙箱与有效策略；
- 转化为 PermissionFact：state=effective、authority=openshell、
  authority_revision=策略 revision——这是产品中第一条真实 effective 权限来源；
- 替换语义：同一 authority+subject 的旧事实先清除，再写入新快照（避免漂移残影）；
- 任何网关错误 fail-closed 并如实返回，绝不产出空权限冒充安全状态。
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import PolicySnapshot
from app.models import PermissionFact, utcnow
from app.outbox import audit, emit_event

AUTHORITY = "openshell"


def _fact_for(
    subject_id: str,
    snapshot: PolicySnapshot,
    domain: str,
    action: str,
    resource_type: str,
    value: str,
    conditions: dict | None = None,
) -> PermissionFact:
    return PermissionFact(
        subject_type="openshell_sandbox",
        subject_id=subject_id,
        domain=domain,
        action=action,
        resource_type=resource_type,
        resource_value=value,
        effect="allow",
        conditions=conditions or {},
        state="effective",  # 权威来源（§12.2）：由网关实际策略解析
        authority=AUTHORITY,
        authority_revision=snapshot.revision,
        evidence_ids=[],
        valid_from=utcnow(),
    )


def sync_openshell(session: Session, tenant_id: str, environment_id: str | None = None) -> dict:
    """拉取真实 OpenShell 有效策略并写入 PermissionFacts。"""
    backend = OpenShellCliBackend()

    targets = backend.list_targets().targets
    facts: list[PermissionFact] = []
    for target in targets:
        snapshot = backend.read_effective_policy(target["id"])
        subject = f"sandbox:{target['id']}"

        fs = snapshot.filesystem
        for path in fs.get("read_only") or []:
            facts.append(_fact_for(subject, snapshot, "filesystem", "fs.read", "path", str(path)))
        for path in fs.get("read_write") or []:
            facts.append(_fact_for(subject, snapshot, "filesystem", "fs.write", "path", str(path)))

        for rule in snapshot.network:
            facts.append(
                _fact_for(
                    subject,
                    snapshot,
                    "network",
                    "http.request",
                    "endpoint",
                    str(rule.get("endpoint", "")),
                    conditions={
                        "binary_paths": rule.get("binary_paths") or [],
                        "rule_name": rule.get("rule_name", ""),
                    },
                )
            )

        proc = snapshot.process
        if proc.get("run_as_user") or proc.get("run_as_group"):
            facts.append(
                _fact_for(
                    subject,
                    snapshot,
                    "process",
                    "process.run_as",
                    "identity",
                    f"{proc.get('run_as_user', '?')}:{proc.get('run_as_group', '?')}",
                )
            )

    # 替换语义：清掉该租户内旧 openshell 事实，写入新快照
    session.execute(
        delete(PermissionFact).where(
            PermissionFact.tenant_id == tenant_id, PermissionFact.authority == AUTHORITY
        )
    )
    for fact in facts:
        fact.tenant_id = tenant_id
        session.add(fact)

    audit(
        session,
        tenant_id,
        "system",
        "openshell-sync",
        "permission.sync",
        "permission_fact",
        summary={"targets": len(targets), "facts": len(facts)},
    )
    if facts:
        emit_event(
            session,
            tenant_id,
            "agent.permission.snapshot.updated.v1",
            {"authority": AUTHORITY, "facts": len(facts), "targets": len(targets)},
        )
    session.commit()
    return {"targets": len(targets), "facts": len(facts)}
