"""DEV11-F：历史 outbox 空引用盘点（只盘点不修复）。"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db import session_scope
from app.models import OutboxEvent, new_id
from app.outbox_null_inventory import inventory_report, scan_outbox_null_refs


def test_inventory_detects_null_payload_refs_and_does_not_invent_ids(client):
    _ = client  # 触发 app lifespan → init_db
    with session_scope() as session:
        session.add(
            OutboxEvent(
                id=new_id("out"),
                tenant_id="tnt-A",
                event_type="environment.created.v1",
                payload={
                    "event_id": "evt_legacy",
                    "event_type": "environment.created.v1",
                    "tenant_id": "tnt-A",
                    "resource_ref": None,
                    "payload": {"environment_id": None},
                    "schema_version": 1,
                },
                occurred_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        session.add(
            OutboxEvent(
                id=new_id("out"),
                tenant_id="tnt-A",
                event_type="scan.created.v1",
                payload={
                    "event_id": "evt_ok",
                    "event_type": "scan.created.v1",
                    "tenant_id": "tnt-A",
                    "resource_ref": "tsk_ok",
                    "payload": {"task_id": "tsk_ok", "environment_id": "env_ok"},
                    "schema_version": 1,
                },
                occurred_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        session.commit()

    with session_scope() as session:
        findings = scan_outbox_null_refs(session)
        bad = [f for f in findings if f.event_type == "environment.created.v1"]
        assert {f.field for f in bad} >= {"environment_id", "resource_ref"}
        report = inventory_report(session)
        assert report["policy"] == "inventory_only_no_guess_repair"
        assert report["events_with_null_refs"] >= 1
        assert report["unrecoverable_without_evidence"] == report["events_with_null_refs"]
        # 不得出现“已修复/已补全”字段
        assert "repaired" not in report
        assert "guessed_ids" not in report
