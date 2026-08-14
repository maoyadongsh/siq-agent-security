"""OpenShell 有效权限同步（Permission Resolver 的 OpenShell 域，设计文档 §12.4）。

- 从真实网关（经 OpenShellCliBackend）拉取沙箱与有效策略；
- 转化为 PermissionFact：state=effective、authority=openshell、
  authority_revision=策略 revision——这是产品中第一条真实 effective 权限来源；
- 替换语义：同一 authority+subject 的旧事实先清除，再写入新快照（避免漂移残影）；
- 任何网关错误 fail-closed 并如实返回，绝不产出空权限冒充安全状态。
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import PolicySnapshot
from app.models import Deployment, PermissionFact, utcnow
from app.outbox import audit, emit_event

AUTHORITY = "openshell"


def _fact_for(
    environment_id: str,
    subject_id: str,
    snapshot: PolicySnapshot,
    domain: str,
    action: str,
    resource_type: str,
    value: str,
    conditions: dict | None = None,
) -> PermissionFact:
    return PermissionFact(
        environment_id=environment_id,
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


def sync_openshell(session: Session, tenant_id: str, environment_id: str) -> dict:
    """拉取真实 OpenShell 有效策略并写入 PermissionFacts。"""
    backend = OpenShellCliBackend()

    backend_targets = backend.list_targets().targets
    bound_targets = set(
        session.scalars(
            select(Deployment.target).where(
                Deployment.tenant_id == tenant_id,
                Deployment.environment_id == environment_id,
                Deployment.status == "effective",
            )
        )
    )
    targets = [target for target in backend_targets if target.get("id") in bound_targets]
    facts: list[PermissionFact] = []
    for target in targets:
        snapshot = backend.read_effective_policy(target["id"])
        subject = f"sandbox:{target['id']}"

        fs = snapshot.filesystem
        for path in fs.get("read_only") or []:
            facts.append(_fact_for(environment_id, subject, snapshot, "filesystem", "fs.read", "path", str(path)))
        for path in fs.get("read_write") or []:
            facts.append(_fact_for(environment_id, subject, snapshot, "filesystem", "fs.write", "path", str(path)))

        for rule in snapshot.network:
            facts.append(
                _fact_for(
                    environment_id,
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
                    environment_id,
                    subject,
                    snapshot,
                    "process",
                    "process.run_as",
                    "identity",
                    f"{proc.get('run_as_user', '?')}:{proc.get('run_as_group', '?')}",
                )
            )

    # 替换语义：只替换该环境的 OpenShell 事实，不影响同租户其他环境。
    session.execute(
        delete(PermissionFact).where(
            PermissionFact.tenant_id == tenant_id,
            PermissionFact.environment_id == environment_id,
            PermissionFact.authority == AUTHORITY,
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
        resource_id=environment_id,
        summary={
            "environment_id": environment_id,
            "backend_targets": len(backend_targets),
            "bound_targets": len(targets),
            "facts": len(facts),
        },
    )
    if facts:
        emit_event(
            session,
            tenant_id,
            "agent.permission.snapshot.updated.v1",
            {
                "authority": AUTHORITY,
                "environment_id": environment_id,
                "facts": len(facts),
                "targets": len(targets),
            },
            environment_id=environment_id,
        )
    session.commit()
    return {
        "backend_targets": len(backend_targets),
        "targets": len(targets),
        "ignored_unbound_targets": len(backend_targets) - len(targets),
        "facts": len(facts),
    }
