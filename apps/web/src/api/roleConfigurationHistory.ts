import { get } from './client';

export interface ConfigurationSnapshot {
  observation_id: string; observed_at: string; received_at: string;
  environment_id: string; device_id: string; device_revoked: boolean;
  status: 'recorded_snapshot' | 'snapshot_unavailable';
  configuration: null | {
    framework_source: { schema_version: 'enterprise-framework-source/v1' | 'enterprise-framework-source/v2'; framework: 'openclaw' | 'hermes';
      instance_key: string; config_sha256: string; evidence_id: string };
    skill_source_roots: null | { schema_version: 'enterprise-role-skill-roots/v1';
      basis: 'none' | 'agent_workspace' | 'default_workspace'; status: 'declared' | 'unresolved';
      roots: { kind: 'workspace_skills' | 'project_agent_skills'; locator_sha256: string }[] }
      | { schema_version: 'enterprise-role-skill-roots/v2'; basis: 'hermes_profile_layout'; status: 'layout_candidate';
        roots: { kind: 'profile_skills'; locator_sha256: string }[] };
    task_id: string; batch_digest: string;
  };
}
export interface ConfigurationHistoryPage {
  schema_version: 'enterprise-role-configuration-history/v1' | 'enterprise-role-configuration-history/v2'; asset_id: string;
  coverage: 'recorded_configuration_observations'; items: ConfigurationSnapshot[];
  next_cursor: string | null; runtime_status: 'unverified'; effective_permissions: null;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const identifier = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(v);
const observationId = (v: unknown): v is string => typeof v === 'string' && /^rco_[A-Za-z0-9_-]{1,60}$/.test(v);
const digest = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const timestamp = (v: unknown): v is string => typeof v === 'string' && v.length <= 32
  && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(v) && Number.isFinite(Date.parse(v))
  && new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
// Keep microseconds: Date.parse truncates to milliseconds and can reverse adjacent observations.
const timeKey = (v: string) => v.slice(0, 19) + (v.slice(19, -1).replace(/^\./, '')).padEnd(6, '0');

function validRoots(v: unknown, hermes: boolean): boolean {
  if (v === null) return true;
  if (hermes) return object(v) && exact(v, ['schema_version', 'basis', 'status', 'roots'])
    && v.schema_version === 'enterprise-role-skill-roots/v2' && v.basis === 'hermes_profile_layout'
    && v.status === 'layout_candidate' && Array.isArray(v.roots) && v.roots.length === 1
    && object(v.roots[0]) && exact(v.roots[0], ['kind', 'locator_sha256'])
    && v.roots[0].kind === 'profile_skills' && digest(v.roots[0].locator_sha256);
  if (!object(v) || !exact(v, ['schema_version', 'basis', 'status', 'roots'])
    || v.schema_version !== 'enterprise-role-skill-roots/v1'
    || !['none', 'agent_workspace', 'default_workspace'].includes(String(v.basis)) || !Array.isArray(v.roots)) return false;
  if (v.status === 'unresolved') return v.roots.length === 0;
  if (v.status !== 'declared' || v.basis === 'none' || v.roots.length !== 2) return false;
  return v.roots.every((r, i) => object(r) && exact(r, ['kind', 'locator_sha256'])
    && r.kind === ['workspace_skills', 'project_agent_skills'][i] && digest(r.locator_sha256))
    && v.roots[0].locator_sha256 !== v.roots[1].locator_sha256;
}

export function isConfigurationSnapshot(v: unknown): v is ConfigurationSnapshot {
  if (!object(v) || !exact(v, ['observation_id', 'observed_at', 'received_at', 'environment_id', 'device_id', 'device_revoked', 'status', 'configuration'])
    || !observationId(v.observation_id) || !timestamp(v.observed_at) || !timestamp(v.received_at)
    || !identifier(v.environment_id) || !identifier(v.device_id) || typeof v.device_revoked !== 'boolean') return false;
  if (v.status === 'snapshot_unavailable') return v.configuration === null;
  const c = v.configuration;
  if (v.status !== 'recorded_snapshot' || !object(c) || !exact(c, ['framework_source', 'skill_source_roots', 'task_id', 'batch_digest'])
    || !identifier(c.task_id) || !digest(c.batch_digest)) return false;
  const s = c.framework_source;
  return object(s) && exact(s, ['schema_version', 'framework', 'instance_key', 'config_sha256', 'evidence_id'])
    && ((s.schema_version === 'enterprise-framework-source/v1' && s.framework === 'openclaw')
      || (s.schema_version === 'enterprise-framework-source/v2' && s.framework === 'hermes'))
    && validRoots(c.skill_source_roots, s.framework === 'hermes')
    && digest(s.instance_key) && digest(s.config_sha256) && typeof s.evidence_id === 'string'
    && s.evidence_id.length <= 2048;
}

export function parseConfigurationHistory(value: unknown, assetId: string, cursor?: string): ConfigurationHistoryPage {
  const fail = () => { throw new Error('配置历史响应无法核验'); };
  if (!object(value) || !exact(value, ['schema_version', 'asset_id', 'coverage', 'items', 'next_cursor', 'runtime_status', 'effective_permissions'])
    || !['enterprise-role-configuration-history/v1', 'enterprise-role-configuration-history/v2'].includes(String(value.schema_version)) || value.asset_id !== assetId
    || value.coverage !== 'recorded_configuration_observations' || value.runtime_status !== 'unverified'
    || value.effective_permissions !== null || !Array.isArray(value.items) || value.items.length > 50
    || !value.items.every(isConfigurationSnapshot)) return fail();
  const framework = value.schema_version === 'enterprise-role-configuration-history/v2' ? 'hermes' : 'openclaw';
  if (value.items.some(row => row.configuration && row.configuration.framework_source.framework !== framework)) return fail();
  const ids = value.items.map(v => v.observation_id);
  if (new Set(ids).size !== ids.length || (cursor !== undefined && ids.includes(cursor))) return fail();
  for (let i = 1; i < value.items.length; i += 1) {
    const previous = value.items[i - 1], current = value.items[i];
    const before = timeKey(previous.received_at), after = timeKey(current.received_at);
    if (after > before || (after === before && current.observation_id >= previous.observation_id)) return fail();
  }
  if (value.next_cursor !== null && (!observationId(value.next_cursor) || !ids.length || value.next_cursor !== ids.at(-1))) return fail();
  return value as unknown as ConfigurationHistoryPage;
}

export async function getConfigurationHistory(assetId: string, cursor?: string): Promise<ConfigurationHistoryPage> {
  if (!identifier(assetId) || (cursor !== undefined && !observationId(cursor))) throw new Error('配置历史查询标识无效');
  return parseConfigurationHistory(await get<unknown>(`/agents/${encodeURIComponent(assetId)}/configuration-observations`,
    { query: { limit: 50, cursor } }), assetId, cursor);
}
