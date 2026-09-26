import { get } from './client';

export interface FrameworkSourceView {
  schema_version: 'enterprise-framework-source-view/v1' | 'enterprise-framework-source-view/v2';
  asset_id: string;
  status: 'no_recorded_source' | 'source_unavailable' | 'historical_reported_source';
  runtime_status: 'unverified';
  skill_relationship_status: 'unresolved';
  effective_permissions: null;
  source: null | {
    framework: 'openclaw' | 'hermes'; instance_key: string; environment_id: string; device_id: string;
    device_revoked: boolean; config_sha256: string; evidence_id: string;
    observation_id: string; observed_at: string;
  };
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const identifier = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v);
const digest = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length
  && keys.every(key => Object.hasOwn(v, key));

export function parseFrameworkSource(value: unknown, assetId: string): FrameworkSourceView {
  const fail = () => { throw new Error('框架来源响应无法核验'); };
  if (!object(value) || !exact(value, ['schema_version', 'asset_id', 'status', 'source', 'runtime_status', 'skill_relationship_status', 'effective_permissions'])
    || !['enterprise-framework-source-view/v1', 'enterprise-framework-source-view/v2'].includes(String(value.schema_version)) || value.asset_id !== assetId
    || value.runtime_status !== 'unverified' || value.skill_relationship_status !== 'unresolved'
    || value.effective_permissions !== null) return fail();
  if (value.status === 'historical_reported_source') {
    const source = value.source;
    if (!object(source) || !exact(source, ['framework', 'instance_key', 'environment_id', 'device_id', 'device_revoked', 'config_sha256', 'evidence_id', 'observation_id', 'observed_at'])
      || source.framework !== (value.schema_version === 'enterprise-framework-source-view/v2' ? 'hermes' : 'openclaw')
      || !digest(source.instance_key) || !digest(source.config_sha256)
      || !identifier(source.environment_id) || !identifier(source.device_id) || !identifier(source.observation_id)
      || typeof source.evidence_id !== 'string' || !source.evidence_id || source.evidence_id.length > 256
      || typeof source.device_revoked !== 'boolean' || typeof source.observed_at !== 'string'
      || source.observed_at.length > 40 || !/^\d{4}-\d\d-\d\dT.*Z$/.test(source.observed_at)
      || !Number.isFinite(Date.parse(source.observed_at))) return fail();
  } else if (!['no_recorded_source', 'source_unavailable'].includes(String(value.status)) || value.source !== null) return fail();
  return value as unknown as FrameworkSourceView;
}

export async function getFrameworkSource(assetId: string): Promise<FrameworkSourceView> {
  if (!identifier(assetId) || assetId.length > 64) throw new Error('资产标识无效');
  return parseFrameworkSource(await get<unknown>(`/agents/${encodeURIComponent(assetId)}/framework-source`), assetId);
}
