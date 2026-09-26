import { expect, it, vi } from 'vitest';
import { getConfigurationHistory, parseConfigurationHistory, type ConfigurationHistoryPage, type ConfigurationSnapshot } from './roleConfigurationHistory';

const get = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ get }));
const snapshot = (): ConfigurationSnapshot => ({
  observation_id: 'rco_z', observed_at: '2026-09-25T00:00:00Z', received_at: '2026-09-25T00:00:00.123456Z',
  environment_id: 'env-one', device_id: 'edge-one', device_revoked: true, status: 'recorded_snapshot',
  configuration: { task_id: 'task-one', batch_digest: 'a'.repeat(64), framework_source: {
    schema_version: 'enterprise-framework-source/v1', framework: 'openclaw', instance_key: 'b'.repeat(64),
    config_sha256: 'c'.repeat(64), evidence_id: 'ev:<script>bad()</script>',
  }, skill_source_roots: { schema_version: 'enterprise-role-skill-roots/v1', basis: 'agent_workspace', status: 'declared',
    roots: [{ kind: 'workspace_skills', locator_sha256: 'd'.repeat(64) }, { kind: 'project_agent_skills', locator_sha256: 'e'.repeat(64) }] } },
});
const page = (): ConfigurationHistoryPage => ({ schema_version: 'enterprise-role-configuration-history/v1', asset_id: 'agt_one',
  coverage: 'recorded_configuration_observations', items: [snapshot()], next_cursor: null, runtime_status: 'unverified', effective_permissions: null });

it('supports Hermes history only with paired v2 source and layout roots', () => {
  const value = page();
  value.schema_version = 'enterprise-role-configuration-history/v2';
  const config = value.items[0].configuration!;
  config.framework_source.schema_version = 'enterprise-framework-source/v2';
  config.framework_source.framework = 'hermes';
  config.skill_source_roots = { schema_version: 'enterprise-role-skill-roots/v2', basis: 'hermes_profile_layout',
    status: 'layout_candidate', roots: [{ kind: 'profile_skills', locator_sha256: 'd'.repeat(64) }] };
  expect(parseConfigurationHistory(value, 'agt_one')).toEqual(value);
  expect(() => parseConfigurationHistory({ ...value, schema_version: page().schema_version }, 'agt_one')).toThrow();
  config.skill_source_roots = snapshot().configuration!.skill_source_roots;
  expect(() => parseConfigurationHistory(value, 'agt_one')).toThrow();
});

it('uses GET, exact asset path and bounded cursor query, without identity overrides', async () => {
  get.mockReset(); get.mockResolvedValue(page());
  expect((await getConfigurationHistory('agt_one', 'rco_earlier_anchor')).items).toHaveLength(1);
  expect(get).toHaveBeenCalledExactlyOnceWith('/agents/agt_one/configuration-observations', { query: { limit: 50, cursor: 'rco_earlier_anchor' } });
});
it.each([['../bad', undefined], ['agt_one', 'bad'], ['agt_one', 'rco_' + 'a'.repeat(61)]])('rejects invalid request identifiers %s %s', async (asset, cursor) => {
  get.mockReset(); await expect(getConfigurationHistory(asset!, cursor)).rejects.toThrow('标识无效'); expect(get).not.toHaveBeenCalled();
});
it('preserves HTTP rejection instead of converting it to an empty page', async () => {
  get.mockReset(); const rejection = new Error('synthetic403'); get.mockRejectedValue(rejection);
  await expect(getConfigurationHistory('agt_one')).rejects.toBe(rejection);
});
it.each([
  { asset_id: 'agt_foreign' }, { effective_permissions: [] }, { runtime_status: 'protected' },
  { extra: 'secret' }, { schema_version: 'future' }, { coverage: 'all' }, { next_cursor: 'rco_other' },
])('rejects invalid envelope %#', patch => {
  expect(() => parseConfigurationHistory({ ...page(), ...patch }, 'agt_one')).toThrow('无法核验');
});
it.each([
  { status: 'effective' }, { device_revoked: 'false' }, { configuration: null }, { tenant_id: 'secret' },
  { received_at: '2026-02-30T00:00:00Z' }, { observed_at: '2026-09-25' }, { observation_id: 'obs_other' },
])('rejects invalid snapshot %#', patch => {
  expect(() => parseConfigurationHistory({ ...page(), items: [{ ...snapshot(), ...patch }] }, 'agt_one')).toThrow();
});
it('does not show payload on unavailable snapshots', () => {
  expect(() => parseConfigurationHistory({ ...page(), items: [{ ...snapshot(), status: 'snapshot_unavailable' }] }, 'agt_one')).toThrow();
  expect(parseConfigurationHistory({ ...page(), items: [{ ...snapshot(), status: 'snapshot_unavailable', configuration: null }] }, 'agt_one').items[0].configuration).toBeNull();
});
it.each([null, { schema_version: 'enterprise-role-skill-roots/v1', basis: 'none', status: 'unresolved', roots: [] }])('retains missing/unresolved roots without inventing declarations %#', roots => {
  const value = page(); value.items[0].configuration!.skill_source_roots = roots as NonNullable<ConfigurationSnapshot['configuration']>['skill_source_roots'];
  expect(parseConfigurationHistory(value, 'agt_one').items[0].configuration!.skill_source_roots).toEqual(roots);
});
it.each(['duplicate', 'reversed', 'extra', 'none', 'unresolved'])('rejects inconsistent declared roots %s', fault => {
  const value = page(); const roots = value.items[0].configuration!.skill_source_roots!;
  if (fault === 'duplicate') roots.roots[1].locator_sha256 = roots.roots[0].locator_sha256;
  if (fault === 'reversed') roots.roots.reverse();
  if (fault === 'extra') Object.assign(roots.roots[0], { path: 'raw private path' });
  if (fault === 'none') roots.basis = 'none';
  if (fault === 'unresolved') roots.status = 'unresolved';
  expect(() => parseConfigurationHistory(value, 'agt_one')).toThrow();
});
it('rejects raw source fields, invalid digests and extra configuration keys', () => {
  for (const target of ['source', 'configuration', 'digest']) {
    const value = page(); const c = value.items[0].configuration!;
    if (target === 'source') Object.assign(c.framework_source, { config: 'private' });
    if (target === 'configuration') Object.assign(c, { token: 'private' });
    if (target === 'digest') c.batch_digest = 'not-a-digest';
    expect(() => parseConfigurationHistory(value, 'agt_one')).toThrow();
  }
});
it('keeps microsecond received order, ties by ID, unique IDs and exact last cursor', () => {
  const value = page(); value.items.push({ ...snapshot(), observation_id: 'rco_zz', received_at: '2026-09-25T00:00:00.123455Z' });
  value.next_cursor = 'rco_zz'; expect(parseConfigurationHistory(value, 'agt_one').items).toHaveLength(2);
  value.items.reverse(); expect(() => parseConfigurationHistory(value, 'agt_one')).toThrow();
  value.items = [snapshot(), { ...snapshot(), observation_id: 'rco_y' }]; value.next_cursor = 'rco_y';
  expect(parseConfigurationHistory(value, 'agt_one').items).toHaveLength(2);
  expect(() => parseConfigurationHistory(value, 'agt_one', 'rco_y')).toThrow();
  value.items[1].observation_id = 'rco_z'; expect(() => parseConfigurationHistory(value, 'agt_one')).toThrow();
});
it('accepts empty history without a cursor and rejects unbounded pages', () => {
  expect(parseConfigurationHistory({ ...page(), items: [] }, 'agt_one').items).toEqual([]);
  expect(() => parseConfigurationHistory({ ...page(), items: [], next_cursor: 'rco_z' }, 'agt_one')).toThrow();
  expect(() => parseConfigurationHistory({ ...page(), items: Array(51).fill(snapshot()) }, 'agt_one')).toThrow();
});
