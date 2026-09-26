import { get } from './client';
import { isConfigurationSnapshot, type ConfigurationSnapshot } from './roleConfigurationHistory';
import { isSkillObservation, type SkillObservation } from './skillInventory';

interface SourceRoot { kind: 'workspace_skills' | 'project_agent_skills' | 'profile_skills'; locator_sha256: string }
export interface SnapshotComparisonItem {
  installation_id: string; locator_sha256: string;
  relationship_status: 'historical_source_match' | 'outside_declared_sources' | 'unresolved';
  matched_sources: SourceRoot[]; observation: SkillObservation | null;
}
export interface SnapshotComparisonPage {
  schema_version: 'enterprise-role-skill-snapshot-comparison/v1' | 'enterprise-role-skill-snapshot-comparison/v2'; asset_id: string;
  configuration_observation: ConfigurationSnapshot;
  status: 'historical_comparison' | 'snapshot_unavailable';
  comparison_basis: 'latest_skill_observations_against_saved_configuration';
  coverage: 'page_of_device_installations';
  items: SnapshotComparisonItem[]; next_cursor: string | null;
  runtime_status: 'unverified'; effective_permissions: null;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const identifier = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(v);
const observationId = (v: unknown): v is string => typeof v === 'string' && /^rco_[A-Za-z0-9_-]{1,60}$/.test(v);
const digest = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const installationId = (v: unknown): v is string => typeof v === 'string' && /^ski_[A-Za-z0-9_-]{1,60}$/.test(v);
function root(v: unknown): v is SourceRoot {
  return object(v) && exact(v, ['kind', 'locator_sha256'])
    && (v.kind === 'workspace_skills' || v.kind === 'project_agent_skills' || v.kind === 'profile_skills') && digest(v.locator_sha256);
}

export function parseSnapshotComparison(value: unknown, assetId: string, observation: string, cursor?: string): SnapshotComparisonPage {
  const fail = () => { throw new Error('快照技能对照响应无法核验'); };
  if (!object(value) || !exact(value, ['schema_version', 'asset_id', 'configuration_observation', 'status', 'comparison_basis', 'coverage', 'items', 'next_cursor', 'runtime_status', 'effective_permissions'])
    || (typeof value.schema_version !== 'string' || !['enterprise-role-skill-snapshot-comparison/v1', 'enterprise-role-skill-snapshot-comparison/v2'].includes(value.schema_version)) || value.asset_id !== assetId
    || value.comparison_basis !== 'latest_skill_observations_against_saved_configuration'
    || value.coverage !== 'page_of_device_installations' || value.runtime_status !== 'unverified'
    || value.effective_permissions !== null || !Array.isArray(value.items) || value.items.length > 50) return fail();
  const snapshot = value.configuration_observation;
  if (!isConfigurationSnapshot(snapshot) || snapshot.observation_id !== observation) return fail();
  const hermes = value.schema_version === 'enterprise-role-skill-snapshot-comparison/v2';
  if (snapshot.configuration && snapshot.configuration.framework_source.framework !== (hermes ? 'hermes' : 'openclaw')) return fail();
  if (value.status === 'snapshot_unavailable') {
    if (value.items.length !== 0 || value.next_cursor !== null) return fail();
    return value as unknown as SnapshotComparisonPage;
  }
  // 状态与数据一致性：可对照必须基于显式选择快照的已记录配置与已声明来源，
  // 不允许用最新资产属性或其他快照补齐。
  const configuration = snapshot.configuration;
  const declared = configuration?.skill_source_roots;
  if (value.status !== 'historical_comparison' || snapshot.status !== 'recorded_snapshot'
    || !configuration || !declared || declared.status !== (hermes ? 'layout_candidate' : 'declared')
    || !Array.isArray(declared.roots) || declared.roots.length !== (hermes ? 1 : 2) || !declared.roots.every(root)) return fail();
  const roots = declared.roots as SourceRoot[];
  let previous = cursor ?? '';
  for (const item of value.items) {
    if (!object(item) || !exact(item, ['installation_id', 'locator_sha256', 'relationship_status', 'matched_sources', 'observation'])
      || !installationId(item.installation_id) || item.installation_id <= previous || !digest(item.locator_sha256)
      || !Array.isArray(item.matched_sources) || item.matched_sources.length > 2 || !item.matched_sources.every(root)) return fail();
    previous = item.installation_id;
    const matches = item.matched_sources as SourceRoot[];
    if (new Set(matches.map(r => r.kind)).size !== matches.length
      || !matches.every(r => roots.some(d => d.kind === r.kind && d.locator_sha256 === r.locator_sha256))) return fail();
    if (item.relationship_status === 'unresolved') {
      if (matches.length || item.observation !== null) return fail();
    } else {
      if ((typeof item.relationship_status !== 'string' || !['historical_source_match', 'outside_declared_sources'].includes(item.relationship_status))
        || (item.relationship_status === 'historical_source_match') !== (matches.length > 0)
        || !object(item.observation) || !exact(item.observation, ['observation_id', 'manifest_sha256', 'parser_version', 'parse_status', 'name', 'allowed_tools_present', 'declared_tools', 'observed_at', 'batch_digest'])
        || !isSkillObservation(item.observation)) return fail();
    }
  }
  if (value.next_cursor !== null && (!installationId(value.next_cursor) || !value.items.length || value.next_cursor !== previous)) return fail();
  return value as unknown as SnapshotComparisonPage;
}

export async function getSnapshotComparison(assetId: string, observation: string, cursor?: string): Promise<SnapshotComparisonPage> {
  if (!identifier(assetId) || !observationId(observation) || (cursor !== undefined && !installationId(cursor))) throw new Error('快照对照查询标识无效');
  return parseSnapshotComparison(await get<unknown>(
    `/agents/${encodeURIComponent(assetId)}/configuration-observations/${encodeURIComponent(observation)}/skill-installation-sources`,
    { query: { cursor, limit: 50 } }), assetId, observation, cursor);
}
