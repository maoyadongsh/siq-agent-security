import { beforeEach, expect, it, vi } from 'vitest';
import { getFrameworkSource, parseFrameworkSource } from './frameworkSource';
const get = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ get }));
const fixture = () => ({ schema_version: 'enterprise-framework-source-view/v1', asset_id: 'agt-one',
  status: 'historical_reported_source', runtime_status: 'unverified', skill_relationship_status: 'unresolved',
  effective_permissions: null, source: { framework: 'openclaw', instance_key: 'a'.repeat(64),
    environment_id: 'env-one', device_id: 'edge-one', device_revoked: false, config_sha256: 'b'.repeat(64),
    evidence_id: 'ev:one', observation_id: 'evo-one', observed_at: '2026-09-25T12:00:00Z' } });
beforeEach(() => get.mockReset());
it('accepts only the Hermes v2 version/framework pair', () => {
  const original = fixture();
  const hermes = { ...original, schema_version: 'enterprise-framework-source-view/v2', source: { ...original.source, framework: 'hermes' } };
  expect(parseFrameworkSource(hermes, original.asset_id)).toEqual(hermes);
  expect(() => parseFrameworkSource({ ...original, schema_version: hermes.schema_version }, original.asset_id)).toThrow();
});
it('consumes a scoped historical source using only GET', async () => {
  get.mockResolvedValue(fixture());
  expect(await getFrameworkSource('agt-one')).toEqual(fixture());
  expect(get).toHaveBeenCalledExactlyOnceWith('/agents/agt-one/framework-source');
});
it.each(['no_recorded_source', 'source_unavailable'])('requires null source for %s', status => {
  expect(parseFrameworkSource({ ...fixture(), status, source: null }, 'agt-one').source).toBeNull();
  expect(() => parseFrameworkSource({ ...fixture(), status }, 'agt-one')).toThrow();
});
it.each([
  { asset_id: 'foreign' }, { schema_version: 'other' }, { status: 'effective' },
  { runtime_status: 'verified' }, { skill_relationship_status: 'resolved' },
  { effective_permissions: [] }, { extra: 'private' }, { source: null },
])('rejects invalid scope or authority %#', patch => {
  expect(() => parseFrameworkSource({ ...fixture(), ...patch }, 'agt-one')).toThrow();
});
it.each([{ framework: 'hermes' }, { instance_key: 'bad' }, { config_sha256: 'bad' },
  { device_revoked: 'false' }, { observed_at: 'yesterday' }, { device_id: '' }, { secret: 'private' }])(
  'rejects invalid nested source %#', patch => {
    const value = fixture();
    expect(() => parseFrameworkSource({ ...value, source: { ...value.source, ...patch } }, 'agt-one')).toThrow();
  },
);
it.each(['', '../other', 'x/y', 'x?tenant=b', 'x'.repeat(65)])('rejects invalid asset before network %s', async id => {
  await expect(getFrameworkSource(id)).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
});
