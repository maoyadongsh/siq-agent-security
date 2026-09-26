import { beforeEach, expect, it, vi } from 'vitest';
import { getRoleSkillSources, parseRoleSkillSources } from './roleSkillSources';
const get = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ get }));
const fixture = () => ({ schema_version: 'enterprise-role-skill-sources-view/v1', asset_id: 'agt-one',
  status: 'historical_comparison', coverage: 'page_of_device_installations', runtime_status: 'unverified', effective_permissions: null,
  framework_source: { schema_version: 'enterprise-framework-source-view/v1', asset_id: 'agt-one',
    status: 'historical_reported_source', runtime_status: 'unverified', skill_relationship_status: 'unresolved', effective_permissions: null,
    source: { framework: 'openclaw', instance_key: 'a'.repeat(64), config_sha256: 'b'.repeat(64), environment_id: 'env-one',
      device_id: 'edge-one', device_revoked: false, evidence_id: 'ev-one', observation_id: 'obs-one', observed_at: '2026-09-25T00:00:00Z' } },
  declared_roots: { schema_version: 'enterprise-role-skill-roots/v1', basis: 'agent_workspace', status: 'declared', roots: [
    { kind: 'workspace_skills', locator_sha256: 'c'.repeat(64) }, { kind: 'project_agent_skills', locator_sha256: 'd'.repeat(64) }] },
  items: [{ installation_id: 'ski_one', locator_sha256: 'e'.repeat(64), relationship_status: 'unresolved', matched_sources: [], observation: null }], next_cursor: 'ski_one' });
beforeEach(() => get.mockReset());
it('accepts Hermes layout v2 only with matching view/root versions and candidate semantics', () => {
  const v1 = fixture();
  const value = { ...v1, schema_version: 'enterprise-role-skill-sources-view/v2',
    framework_source: { ...v1.framework_source, schema_version: 'enterprise-framework-source-view/v2',
      source: { ...v1.framework_source.source, framework: 'hermes' } },
    declared_roots: { schema_version: 'enterprise-role-skill-roots/v2', basis: 'hermes_profile_layout',
      status: 'layout_candidate', roots: [{ kind: 'profile_skills', locator_sha256: 'c'.repeat(64) }] } };
  expect(parseRoleSkillSources(value, 'agt-one')).toEqual(value);
  expect(() => parseRoleSkillSources({ ...value, schema_version: v1.schema_version }, 'agt-one')).toThrow();
  expect(() => parseRoleSkillSources({ ...value, framework_source: v1.framework_source }, 'agt-one')).toThrow();
  expect(() => parseRoleSkillSources({ ...value, declared_roots: v1.declared_roots }, 'agt-one')).toThrow();
  expect(() => parseRoleSkillSources({ ...value, declared_roots: { ...value.declared_roots, status: 'declared' } }, 'agt-one')).toThrow();
});
it('requests scoped sources via GET and validates cursor', async () => {
  get.mockResolvedValue(fixture());
  expect(await getRoleSkillSources('agt-one', 'ski_before')).toEqual(fixture());
  expect(get).toHaveBeenCalledExactlyOnceWith('/agents/agt-one/skill-installation-sources', { query: { cursor: 'ski_before', limit: 50 } });
  expect(() => parseRoleSkillSources(fixture(), 'agt-one', 'ski_one')).toThrow();
});
it.each([{ asset_id: 'foreign' }, { runtime_status: 'verified' }, { effective_permissions: [] },
  { coverage: 'all_assets' }, { next_cursor: 'ski_else' }, { status: 'protected' }, { extra: true }, { declared_roots: null }])('rejects scope and authority drift %#', patch => {
  expect(() => parseRoleSkillSources({ ...fixture(), ...patch }, 'agt-one')).toThrow();
});
it.each([{ relationship_status: 'historical_source_match' }, { relationship_status: 'outside_declared_sources' },
  { matched_sources: [{ kind: 'workspace_skills', locator_sha256: 'f'.repeat(64) }] },
  { observation: {} }, { locator_sha256: 'private-path' }])('rejects inconsistent observation %#', patch => {
  const value = fixture();
  expect(() => parseRoleSkillSources({ ...value, items: [{ ...value.items[0], ...patch }] }, 'agt-one')).toThrow();
});
it('preserves unavailable as distinct from an empty comparison', () => {
  const unavailable = { ...fixture(), status: 'source_unavailable', declared_roots: null, items: [], next_cursor: null };
  expect(parseRoleSkillSources(unavailable, 'agt-one').status).toBe('source_unavailable');
  expect(parseRoleSkillSources({ ...fixture(), items: [], next_cursor: null }, 'agt-one').status).toBe('historical_comparison');
});
it('rejects coercible root basis instead of accepting a malformed declaration', () => {
  const value = fixture();
  expect(() => parseRoleSkillSources({ ...value,
    declared_roots: { ...value.declared_roots, basis: ['agent_workspace'] } }, 'agt-one')).toThrow();
});
it('rejects duplicate positions and root aliases', () => {
  const value = fixture();
  expect(() => parseRoleSkillSources({ ...value, items: [value.items[0], value.items[0]] }, 'agt-one')).toThrow();
  value.declared_roots.roots[1] = value.declared_roots.roots[0];
  expect(() => parseRoleSkillSources(value, 'agt-one')).toThrow();
});
it.each([['../foreign', undefined], ['agt-one', 'bad'], ['', undefined]])('rejects bad query before network %#', async (id, cursor) => {
  await expect(getRoleSkillSources(id!, cursor)).rejects.toThrow(); expect(get).not.toHaveBeenCalled();
});
