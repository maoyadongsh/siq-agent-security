"""Trusted device predicate shared by consumers of discovered asset evidence."""

from sqlalchemy import select, true

from app.models import AgentAsset, EdgeAgent, Evidence


def asset_evidence_device_filter(asset: AgentAsset):
    if asset.discovery_scope == "legacy":
        return true()
    return Evidence.collector_id.in_(
        select(EdgeAgent.device_identity).where(EdgeAgent.id == asset.discovery_scope)
    ) & Evidence.environment_id.in_(select(EdgeAgent.environment_id).where(EdgeAgent.id == asset.discovery_scope))
