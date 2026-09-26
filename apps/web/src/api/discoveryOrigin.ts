import { get } from './client';

export interface DiscoveryOrigin {
  schema_version: 'enterprise-discovery-origin/v1';
  asset_id: string;
  status: 'device_bound' | 'legacy_unresolved' | 'source_unavailable';
  environment: { id: string; name: string } | null;
  device: { id: string; identity: string; revoked: boolean } | null;
  reported_framework: string;
  assigned_role: string | null;
  observations: { observation_id: string; evidence_id: string; content_hash: string; observed_at: string }[];
  observations_truncated: boolean;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 4096;

export function isDiscoveryOrigin(v: unknown, assetId: string): v is DiscoveryOrigin {
  if (!object(v) || v.schema_version !== 'enterprise-discovery-origin/v1' || v.asset_id !== assetId
    || !text(v.reported_framework) || !(v.assigned_role === null || typeof v.assigned_role === 'string')
    || typeof v.observations_truncated !== 'boolean' || !Array.isArray(v.observations) || v.observations.length > 200) return false;
  if (v.status === 'device_bound') {
    if (!object(v.environment) || !text(v.environment.id) || !text(v.environment.name)
      || !object(v.device) || !text(v.device.id) || !text(v.device.identity) || typeof v.device.revoked !== 'boolean') return false;
  } else if (!['legacy_unresolved', 'source_unavailable'].includes(String(v.status))
    || v.environment !== null || v.device !== null || v.observations.length !== 0 || v.observations_truncated) return false;
  return v.observations.every(o => object(o) && text(o.observation_id) && text(o.evidence_id)
    && typeof o.content_hash === 'string' && /^[a-f0-9]{64}$/.test(o.content_hash)
    && text(o.observed_at) && Number.isFinite(Date.parse(o.observed_at)))
    && new Set(v.observations.map(o => o.observation_id)).size === v.observations.length;
}

export async function getDiscoveryOrigin(assetId: string): Promise<DiscoveryOrigin> {
  const value = await get<unknown>(`/agents/${encodeURIComponent(assetId)}/discovery-origin`);
  if (!isDiscoveryOrigin(value, assetId)) throw new Error('资产来源响应无法核验');
  return value;
}
