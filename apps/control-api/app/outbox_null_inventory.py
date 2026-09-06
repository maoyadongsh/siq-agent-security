"""历史 Outbox 空对象引用盘点（DEV11-F / R05）。

只盘点、不猜测补 ID、不覆盖既有审计/事件。
修复须另走带依据的追加留痕流程（本模块不自动修复）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutboxEvent
from app.outbox import REQUIRED_REF_KEYS


@dataclass(frozen=True)
class NullRefFinding:
    outbox_id: str
    tenant_id: str
    event_type: str
    field: str
    location: str  # payload|envelope.resource_ref|envelope.environment_id


def _is_empty_ref(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def scan_outbox_null_refs(session: Session) -> list[NullRefFinding]:
    findings: list[NullRefFinding] = []
    rows = session.scalars(select(OutboxEvent).order_by(OutboxEvent.id)).all()
    for event in rows:
        envelope = event.payload if isinstance(event.payload, dict) else {}
        payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
        if _is_empty_ref(envelope.get("resource_ref")) and "resource_ref" in envelope:
            findings.append(
                NullRefFinding(
                    outbox_id=event.id,
                    tenant_id=event.tenant_id,
                    event_type=event.event_type,
                    field="resource_ref",
                    location="envelope.resource_ref",
                )
            )
        env_id = envelope.get("environment_id")
        if "environment_id" in envelope and _is_empty_ref(env_id):
            findings.append(
                NullRefFinding(
                    outbox_id=event.id,
                    tenant_id=event.tenant_id,
                    event_type=event.event_type,
                    field="environment_id",
                    location="envelope.environment_id",
                )
            )
        for key, value in payload.items():
            if key not in REQUIRED_REF_KEYS:
                continue
            if _is_empty_ref(value):
                findings.append(
                    NullRefFinding(
                        outbox_id=event.id,
                        tenant_id=event.tenant_id,
                        event_type=event.event_type,
                        field=key,
                        location="payload",
                    )
                )
    return findings


def inventory_report(session: Session) -> dict:
    """返回可机器消费的盘点报告；unrecoverable = 无依据不得自动补 ID 的条数。"""
    findings = scan_outbox_null_refs(session)
    event_ids = {f.outbox_id for f in findings}
    total = len(session.scalars(select(OutboxEvent.id)).all())
    by_type: dict[str, int] = {}
    for f in findings:
        by_type[f.event_type] = by_type.get(f.event_type, 0) + 1
    return {
        "scanned_events": total,
        "events_with_null_refs": len(event_ids),
        "null_ref_findings": len(findings),
        # 无外部依据时一律计为不可自动恢复；禁止猜测补 ID
        "unrecoverable_without_evidence": len(event_ids),
        "by_event_type": by_type,
        "findings": [asdict(f) for f in findings],
        "policy": "inventory_only_no_guess_repair",
    }
