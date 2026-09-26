import { get } from './client';
import { parseFrameworkSource, type FrameworkSourceView } from './frameworkSource';
import { isSkillObservation, type SkillObservation } from './skillInventory';

interface SourceRoot { kind: 'workspace_skills' | 'project_agent_skills' | 'profile_skills'; locator_sha256: string }
export interface RoleSkillSourcePage {
  schema_version: 'enterprise-role-skill-sources-view/v1' | 'enterprise-role-skill-sources-view/v2'; asset_id: string;
  status: 'source_unavailable' | 'historical_comparison'; framework_source: FrameworkSourceView;
  declared_roots: null | { schema_version: 'enterprise-role-skill-roots/v1';
    basis: 'agent_workspace' | 'default_workspace'; status: 'declared'; roots: SourceRoot[] }
    | { schema_version: 'enterprise-role-skill-roots/v2'; basis: 'hermes_profile_layout'; status: 'layout_candidate'; roots: SourceRoot[] };
  coverage: 'page_of_device_installations'; next_cursor: string | null;
  runtime_status: 'unverified'; effective_permissions: null;
  items: { installation_id: string; locator_sha256: string;
    relationship_status: 'historical_source_match' | 'outside_declared_sources' | 'unresolved';
    matched_sources: SourceRoot[]; observation: SkillObservation | null }[];
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const digest = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const installationId = (v: unknown): v is string => typeof v === 'string' && /^ski_[A-Za-z0-9_-]{1,60}$/.test(v);
function root(v: unknown): v is SourceRoot {
  return object(v) && exact(v, ['kind', 'locator_sha256'])
    && (v.kind === 'workspace_skills' || v.kind === 'project_agent_skills' || v.kind === 'profile_skills') && digest(v.locator_sha256);
}

export function parseRoleSkillSources(value: unknown, assetId: string, cursor?: string): RoleSkillSourcePage {
  const fail = () => { throw new Error('技能来源响应无法核验'); };
  if (!object(value) || !exact(value, ['schema_version', 'asset_id', 'status', 'framework_source', 'declared_roots', 'coverage', 'items', 'next_cursor', 'runtime_status', 'effective_permissions'])
    || (typeof value.schema_version !== 'string' || !['enterprise-role-skill-sources-view/v1', 'enterprise-role-skill-sources-view/v2'].includes(value.schema_version)) || value.asset_id !== assetId
    || value.coverage !== 'page_of_device_installations' || value.runtime_status !== 'unverified'
    || value.effective_permissions !== null || !Array.isArray(value.items) || value.items.length > 50) return fail();
  const source = parseFrameworkSource(value.framework_source, assetId);
  const hermes = value.schema_version === 'enterprise-role-skill-sources-view/v2';
  if (source.schema_version !== `enterprise-framework-source-view/${hermes ? 'v2' : 'v1'}`) return fail();
  if (value.status === 'source_unavailable') {
    if (value.declared_roots !== null || value.items.length !== 0 || value.next_cursor !== null) return fail();
    return value as unknown as RoleSkillSourcePage;
  }
  const declared = value.declared_roots;
  if (value.status !== 'historical_comparison' || source.status !== 'historical_reported_source'
    || !object(declared) || !exact(declared, ['schema_version', 'basis', 'status', 'roots'])
    || !Array.isArray(declared.roots) || !declared.roots.every(root)) return fail();
  if (hermes) {
    if (declared.schema_version !== 'enterprise-role-skill-roots/v2' || declared.status !== 'layout_candidate'
      || declared.basis !== 'hermes_profile_layout' || declared.roots.length !== 1
      || declared.roots[0].kind !== 'profile_skills') return fail();
  } else if (declared.schema_version !== 'enterprise-role-skill-roots/v1' || declared.status !== 'declared'
    || (typeof declared.basis !== 'string' || !['agent_workspace', 'default_workspace'].includes(declared.basis)) || declared.roots.length !== 2
    || declared.roots[0].kind !== 'workspace_skills' || declared.roots[1].kind !== 'project_agent_skills'
    || declared.roots[0].locator_sha256 === declared.roots[1].locator_sha256) return fail();
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
  return value as unknown as RoleSkillSourcePage;
}

export async function getRoleSkillSources(assetId: string, cursor?: string): Promise<RoleSkillSourcePage> {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(assetId) || (cursor !== undefined && !installationId(cursor))) throw new Error('来源查询标识无效');
  return parseRoleSkillSources(await get<unknown>(`/agents/${encodeURIComponent(assetId)}/skill-installation-sources`,
    { query: { cursor, limit: 50 } }), assetId, cursor);
}
