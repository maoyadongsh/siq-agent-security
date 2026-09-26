import { beforeEach, expect, it, vi } from 'vitest';
import { getSnapshotComparison, parseSnapshotComparison } from './roleSkillSnapshotComparison';
const get = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ get }));
const snapshot = { observation_id: 'rco_one', observed_at: '2026-09-24T00:00:00Z', received_at: '2026-09-25T00:00:00Z',
  environment_id: 'env-one', device_id: 'edge-one', device_revoked: true, status: 'recorded_snapshot',
  configuration: { task_id: 'task-one', batch_digest: 'a'.repeat(64),
    skill_source_roots: { schema_version: 'enterprise-role-skill-roots/v1', basis: 'agent_workspace', status: 'declared',
      roots: [{ kind: 'workspace_skills', locator_sha256: 'c'.repeat(64) }, { kind: 'project_agent_skills', locator_sha256: 'd'.repeat(64) }] },
    framework_source: { schema_version: 'enterprise-framework-source/v1', framework: 'openclaw', instance_key: 'b'.repeat(64),
      config_sha256: 'e'.repeat(64), evidence_id: 'ev-one' } } };
const fixture = () => ({ schema_version: 'enterprise-role-skill-snapshot-comparison/v1', asset_id: 'agt-one',
  configuration_observation: snapshot, status: 'historical_comparison',
  comparison_basis: 'latest_skill_observations_against_saved_configuration', coverage: 'page_of_device_installations',
  runtime_status: 'unverified', effective_permissions: null,
  items: [{ installation_id: 'ski_one', locator_sha256: 'f'.repeat(64), relationship_status: 'historical_source_match',
    matched_sources: [{ kind: 'workspace_skills', locator_sha256: 'c'.repeat(64) }],
    observation: { observation_id: 'smo-one', manifest_sha256: '1'.repeat(64), parser_version: 'enterprise-skill-manifest/v1',
      parse_status: 'parsed', name: 'demo', allowed_tools_present: false, declared_tools: [],
      observed_at: '2026-09-25T01:00:00Z', batch_digest: '2'.repeat(64) } }],
  next_cursor: 'ski_one' });
beforeEach(() => get.mockReset());
it('compares Hermes saved layout only through the paired v2 envelope', () => {
  const value = structuredClone(fixture());
  value.schema_version = 'enterprise-role-skill-snapshot-comparison/v2';
  const config = value.configuration_observation.configuration;
  config.framework_source.schema_version = 'enterprise-framework-source/v2';
  config.framework_source.framework = 'hermes';
  config.skill_source_roots = { schema_version: 'enterprise-role-skill-roots/v2', basis: 'hermes_profile_layout',
    status: 'layout_candidate', roots: [{ kind: 'profile_skills', locator_sha256: 'c'.repeat(64) }] };
  value.items[0].matched_sources[0].kind = 'profile_skills';
  expect(parseSnapshotComparison(value, 'agt-one', 'rco_one')).toEqual(value);
  expect(() => parseSnapshotComparison({ ...value, schema_version: fixture().schema_version }, 'agt-one', 'rco_one')).toThrow();
  config.skill_source_roots = structuredClone(snapshot.configuration.skill_source_roots);
  expect(() => parseSnapshotComparison(value, 'agt-one', 'rco_one')).toThrow();
});
it('requests the selected snapshot via GET with encoded path and cursor, no identity overrides', async () => {
  get.mockResolvedValue(fixture());
  expect(await getSnapshotComparison('agt-one', 'rco_one', 'ski_before')).toEqual(fixture());
  expect(get).toHaveBeenCalledExactlyOnceWith(
    '/agents/agt-one/configuration-observations/rco_one/skill-installation-sources',
    { query: { cursor: 'ski_before', limit: 50 } });
  expect(() => parseSnapshotComparison(fixture(), 'agt-one', 'rco_one', 'ski_one')).toThrow();
});
it.each([{ asset_id: 'foreign' }, { schema_version: 'enterprise-role-skill-sources-view/v1' },
  { comparison_basis: 'latest_configuration' }, { coverage: 'all_assets' }, { runtime_status: 'verified' },
  { effective_permissions: [] }, { next_cursor: 'ski_else' }, { extra: true },
  { configuration_observation: { ...snapshot, observation_id: 'rco_other' } }])('rejects scope and authority drift %#', patch => {
  expect(() => parseSnapshotComparison({ ...fixture(), ...patch }, 'agt-one', 'rco_one')).toThrow();
});
it('rejects status/data contradictions: unavailable with data, comparison without declared roots', () => {
  expect(() => parseSnapshotComparison({ ...fixture(), status: 'snapshot_unavailable', items: fixture().items, next_cursor: 'ski_one' }, 'agt-one', 'rco_one')).toThrow();
  expect(() => parseSnapshotComparison({ ...fixture(), status: 'historical_comparison',
    configuration_observation: { ...snapshot, configuration: { ...snapshot.configuration!, skill_source_roots: null } } }, 'agt-one', 'rco_one')).toThrow();
  expect(() => parseSnapshotComparison({ ...fixture(), status: 'historical_comparison',
    configuration_observation: { ...snapshot, status: 'snapshot_unavailable', configuration: null } }, 'agt-one', 'rco_one')).toThrow();
});
it.each([{ relationship_status: 'unresolved' }, { relationship_status: 'outside_declared_sources' },
  { matched_sources: [{ kind: 'workspace_skills', locator_sha256: '9'.repeat(64) }] },
  { observation: {} }, { locator_sha256: 'private-path' },
  { matched_sources: [{ kind: 'workspace_skills', locator_sha256: 'c'.repeat(64) }, { kind: 'workspace_skills', locator_sha256: 'c'.repeat(64) }] }])('rejects inconsistent observation %#', patch => {
  const value = fixture();
  expect(() => parseSnapshotComparison({ ...value, items: [{ ...value.items[0], ...patch }] }, 'agt-one', 'rco_one')).toThrow();
});
it('accepts outside_declared_sources with verified observation and unresolved without matches', () => {
  const value = fixture();
  const outside = { ...value.items[0], relationship_status: 'outside_declared_sources', matched_sources: [] };
  expect(parseSnapshotComparison({ ...value, items: [outside], next_cursor: null }, 'agt-one', 'rco_one').items[0].relationship_status).toBe('outside_declared_sources');
  const unresolved = { ...value.items[0], relationship_status: 'unresolved', matched_sources: [], observation: null };
  expect(parseSnapshotComparison({ ...value, items: [unresolved], next_cursor: null }, 'agt-one', 'rco_one').items[0].relationship_status).toBe('unresolved');
});
it('rejects a relationship array that stringifies to an accepted status', () => {
  const value = fixture();
  expect(() => parseSnapshotComparison({ ...value, items: [{ ...value.items[0],
    relationship_status: ['historical_source_match'] }] }, 'agt-one', 'rco_one')).toThrow();
});
it('keeps snapshot_unavailable distinct from an empty comparison page', () => {
  const unavailable = { ...fixture(), status: 'snapshot_unavailable', items: [], next_cursor: null };
  expect(parseSnapshotComparison(unavailable, 'agt-one', 'rco_one').status).toBe('snapshot_unavailable');
  expect(parseSnapshotComparison({ ...fixture(), items: [], next_cursor: null }, 'agt-one', 'rco_one').status).toBe('historical_comparison');
});
it('rejects duplicate positions and cursor regressions', () => {
  const value = fixture();
  expect(() => parseSnapshotComparison({ ...value, items: [value.items[0], value.items[0]] }, 'agt-one', 'rco_one')).toThrow();
  expect(() => parseSnapshotComparison({ ...value, items: [{ ...value.items[0], installation_id: 'ski_zero' }] }, 'agt-one', 'rco_one', 'ski_one')).toThrow();
});
it.each([['../foreign', 'rco_one', undefined], ['agt-one', 'bad', undefined], ['agt-one', 'rco_one', 'bad'],
  ['', 'rco_one', undefined]])('rejects bad query before network %#', async (id, observation, cursor) => {
  await expect(getSnapshotComparison(id!, observation!, cursor)).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
});
