import { expect, it, vi } from 'vitest';
import { getFrameworkRoleInventory, parseFrameworkRoleInventory } from './frameworkRoleInventory';

const get = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ get }));

// 注意：本仓库 vitest 4.1 环境下，beforeEach 钩子里 mockReset/mockClear 会使后续
// mockRejectedValue 的拒绝被误报为未处理拒绝（实测复现），故改在每个测试体内首行重置。
const reset = () => { get.mockReset(); };

const sourceView = (assetId: string, overrides: Record<string, unknown> = {}) => ({
  schema_version: 'enterprise-framework-source-view/v1', asset_id: assetId,
  status: 'historical_reported_source', runtime_status: 'unverified',
  skill_relationship_status: 'unresolved', effective_permissions: null,
  source: {
    framework: 'openclaw', instance_key: 'a'.repeat(64), environment_id: 'env-one',
    device_id: 'edge-one', device_revoked: false, config_sha256: 'b'.repeat(64),
    evidence_id: 'ev:one', observation_id: 'evo-one', observed_at: '2026-09-25T12:00:00Z',
  },
  ...overrides,
});

const item = (assetId: string, overrides: Record<string, unknown> = {}) => ({
  asset_id: assetId, name: `角色 ${assetId}`, reported_framework: 'openclaw',
  asset_status: 'confirmed', framework_source: sourceView(assetId), ...overrides,
});

const page = (items: unknown[], nextCursor: string | null = null) => ({
  schema_version: 'enterprise-framework-role-inventory/v1',
  coverage: 'page_of_tenant_assets', items, next_cursor: nextCursor,
});

it('accepts mixed v2 inventory but rejects a v2 source inside v1', () => {
  const source = sourceView('agt_b');
  const hermes = item('agt_b', { reported_framework: 'hermes', framework_source: {
    ...source, schema_version: 'enterprise-framework-source-view/v2', source: { ...source.source, framework: 'hermes' },
  } });
  const value = page([item('agt_a'), hermes]);
  expect(() => parseFrameworkRoleInventory(value)).toThrow();
  const result = parseFrameworkRoleInventory({ ...value, schema_version: 'enterprise-framework-role-inventory/v2' });
  expect(result.items[1].framework_source.source?.framework).toBe('hermes');
});

it('consumes a valid page using only GET without identity overrides', async () => {
  reset();
  get.mockResolvedValue(page([item('agt_a'), item('agt_b')], 'agt_b'));
  const result = await getFrameworkRoleInventory({ environmentId: 'env-one', deviceId: 'edge-one' });
  expect(result.items.map(row => row.asset_id)).toEqual(['agt_a', 'agt_b']);
  expect(result.next_cursor).toBe('agt_b');
  expect(get).toHaveBeenCalledExactlyOnceWith('/framework-role-inventory', {
    query: { environment_id: 'env-one', device_id: 'edge-one', cursor: undefined, limit: 50 },
  });
  const [, options] = get.mock.calls[0];
  expect(JSON.stringify(options)).not.toContain('tenant');
});

it('passes the cursor through unchanged for the next page', async () => {
  reset();
  get.mockResolvedValue(page([item('agt_c')]));
  await getFrameworkRoleInventory({ cursor: 'agt_b' });
  expect(get).toHaveBeenCalledExactlyOnceWith('/framework-role-inventory', {
    query: { environment_id: undefined, device_id: undefined, cursor: 'agt_b', limit: 50 },
  });
});

it.each([
  { schema_version: 'other' }, { coverage: 'whole_tenant' }, { next_cursor: undefined },
  { extra: 'field' }, { items: {} },
])('rejects malformed envelopes %#', patch => {
  const value = page([item('agt_a')]);
  expect(() => parseFrameworkRoleInventory({ ...value, ...patch })).toThrow('无法核验');
});

it('rejects more than 100 items', () => {
  const items = Array.from({ length: 101 }, (_, index) => item(`agt_${String(index).padStart(4, '0')}`));
  expect(() => parseFrameworkRoleInventory(page(items))).toThrow('无法核验');
});

it.each([
  { asset_id: 'foreign' }, { name: 1 }, { reported_framework: '' }, { asset_status: null },
  { extra: 'field' },
])('rejects malformed items %#', patch => {
  expect(() => parseFrameworkRoleInventory(page([{ ...item('agt_a'), ...patch }]))).toThrow('无法核验');
});

it('rejects a source projection whose asset_id does not match the item', () => {
  expect(() => parseFrameworkRoleInventory(page([{
    ...item('agt_a'), framework_source: sourceView('agt_other'),
  }]))).toThrow('无法核验');
});

it.each([
  { status: 'no_recorded_source' }, { status: 'source_unavailable' },
])('keeps unknown-source items with null source (%s)', ({ status }) => {
  const result = parseFrameworkRoleInventory(page([item('agt_a', {
    framework_source: sourceView('agt_a', { status, source: null }),
  })]));
  expect(result.items[0].framework_source.status).toBe(status);
  expect(result.items[0].framework_source.source).toBeNull();
});

it.each([
  { runtime_status: 'verified' }, { skill_relationship_status: 'resolved' },
  { effective_permissions: [] }, { status: 'historical_reported_source', source: null },
])('never rewrites unknown runtime/permission state %#', patch => {
  expect(() => parseFrameworkRoleInventory(page([item('agt_a', {
    framework_source: sourceView('agt_a', patch),
  })]))).toThrow('无法核验');
});

it('rejects non-ascending or duplicate asset ids', () => {
  expect(() => parseFrameworkRoleInventory(page([item('agt_b'), item('agt_a')]))).toThrow('无法核验');
  expect(() => parseFrameworkRoleInventory(page([item('agt_a'), item('agt_a')]))).toThrow('无法核验');
});

it('rejects items at or before the requested cursor', () => {
  expect(() => parseFrameworkRoleInventory(page([item('agt_a')]), { cursor: 'agt_a' })).toThrow('无法核验');
  expect(() => parseFrameworkRoleInventory(page([item('agt_a')]), { cursor: 'agt_b' })).toThrow('无法核验');
});

it.each([
  { next_cursor: 'agt_other' }, { next_cursor: 'bad cursor' },
])('rejects inconsistent cursors %#', patch => {
  expect(() => parseFrameworkRoleInventory({ ...page([item('agt_a')]), ...patch })).toThrow('无法核验');
});

it('rejects a next_cursor without items', () => {
  expect(() => parseFrameworkRoleInventory(page([], 'agt_a'))).toThrow('无法核验');
});

it('rejects historical sources outside the applied environment/device filter', () => {
  const filtered = { environmentId: 'env-one', deviceId: 'edge-one' };
  expect(() => parseFrameworkRoleInventory(page([item('agt_a', {
    framework_source: sourceView('agt_a', {
      source: { ...sourceView('agt_a').source, environment_id: 'env-other' },
    }),
  })]), filtered)).toThrow('无法核验');
  expect(() => parseFrameworkRoleInventory(page([item('agt_a', {
    framework_source: sourceView('agt_a', {
      source: { ...sourceView('agt_a').source, device_id: 'edge-other' },
    }),
  })]), filtered)).toThrow('无法核验');
});

it('keeps unknown-source items under an applied filter (contract allows them)', () => {
  const result = parseFrameworkRoleInventory(page([item('agt_a', {
    framework_source: sourceView('agt_a', { status: 'no_recorded_source', source: null }),
  })]), { environmentId: 'env-one' });
  expect(result.items).toHaveLength(1);
});

it.each([
  { limit: 0 }, { limit: 101 }, { limit: 1.5 }, { cursor: 'not-a-cursor' },
  { environmentId: '' }, { deviceId: 'x'.repeat(65) },
])('rejects invalid request parameters before any network call %#', async query => {
  reset();
  await expect(getFrameworkRoleInventory(query)).rejects.toThrow('请求参数无效');
  expect(get).not.toHaveBeenCalled();
});

it('propagates API failure instead of falling back to an empty list', async () => {
  reset();
  get.mockRejectedValue(new Error('HTTP 500'));
  await expect(getFrameworkRoleInventory()).rejects.toThrow('HTTP 500');
});
