import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listDiscoverySchedules, parseDiscoverySchedulePage, revokeDiscoverySchedule } from './discoveryScheduleManagement';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ get, post }));

beforeEach(() => { get.mockReset(); post.mockReset(); });

const id = (char: string) => `eds-${char.repeat(32)}`;
const item = (hex: string, over: Record<string, unknown> = {}): Record<string, unknown> => ({
  schedule_id: id(hex), edge_agent_id: 'edge-1', status: 'active', revision: 3,
  starts_at: '2026-09-26T00:00:00Z', expires_at: '2026-09-27T00:00:00Z', interval_seconds: 900,
  max_runs: 4, reserved_runs: 1, last_reserved_slot: 0, created_at: '2026-09-25T00:00:00Z', ...over,
});
const page = (over: Record<string, unknown> = {}, items = [item('a')]): Record<string, unknown> => ({
  schema_version: 'enterprise-discovery-schedule-management/v1', environment_id: 'env-1',
  evaluated_at: '2026-09-26T01:00:00Z', can_revoke: true, items, next_cursor: null, ...over,
});
const state = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  schema_version: 'enterprise-discovery-schedule-state/v1', schedule_id: id('a'),
  status: 'revoked', revision: 4, intent_digest: 'a'.repeat(64), ...over,
});

describe('parseDiscoverySchedulePage', () => {
  it('accepts a well-formed page and enforces ascending schedule ids', () => {
    const parsed = parseDiscoverySchedulePage(page({ items: [item('a'), item('b')] }), 'env-1');
    expect(parsed.items).toHaveLength(2);
    expect(parsed.next_cursor).toBeNull();
    expect(() => parseDiscoverySchedulePage(page({ items: [item('b'), item('a')] }), 'env-1')).toThrow('周期发现计划列表待核对');
  });

  it('rejects mismatched environment echo, versions and unknown statuses', () => {
    expect(() => parseDiscoverySchedulePage(page({ environment_id: 'env-2' }), 'env-1')).toThrow('周期发现计划列表待核对');
    expect(() => parseDiscoverySchedulePage(page({ schema_version: 'enterprise-discovery-schedule-management/v2' }), 'env-1')).toThrow();
    expect(() => parseDiscoverySchedulePage(page({ items: [item('a', { status: 'running' })] }), 'env-1')).toThrow('周期发现计划条目待核对');
  });

  it.each([
    { schema_version: 'x' },
    { evaluated_at: '2026-09-26T01:00:00+08:00' },
    { can_revoke: 'true' },
    { items: 'no' },
    { next_cursor: 'eds-AABB' },
    { extra: 1 },
  ])('rejects page patch %j', patch => {
    expect(() => parseDiscoverySchedulePage({ ...page(), ...patch }, 'env-1')).toThrow('周期发现计划列表待核对');
  });

  it.each([
    { revision: -1 }, { reserved_runs: 1.5 }, { starts_at: '2026-09-26 00:00:00Z' },
    { expires_at: '2026-01-01T00:00:00Z' }, { last_reserved_slot: -2 }, { schedule_id: 'eds-' + 'g'.repeat(32) },
    { extra: true },
  ])('rejects item patch %j', patch => {
    expect(() => parseDiscoverySchedulePage(page({ items: [item('a', patch)] }), 'env-1')).toThrow('周期发现计划条目待核对');
  });

  it('rejects inherited fields via Object.create', () => {
    const inherited = Object.create(page());
    inherited.items = [item('a')];
    expect(() => parseDiscoverySchedulePage(inherited, 'env-1')).toThrow();
  });

  it('rejects inconsistent next cursors and impossible calendar dates', () => {
    expect(() => parseDiscoverySchedulePage(page({ next_cursor: id('b') }), 'env-1')).toThrow();
    expect(() => parseDiscoverySchedulePage(page({ next_cursor: id('a'), items: [] }), 'env-1')).toThrow();
    expect(() => parseDiscoverySchedulePage(page({ evaluated_at: '2026-02-30T00:00:00Z' }), 'env-1')).toThrow();
    expect(() => parseDiscoverySchedulePage(page({}, [item('a', { reserved_runs: 5 })]), 'env-1')).toThrow();
  });
});

describe('listDiscoverySchedules', () => {
  it('requests the management endpoint and validates before returning', async () => {
    get.mockResolvedValueOnce(page());
    await expect(listDiscoverySchedules('env-1')).resolves.toMatchObject({ environment_id: 'env-1' });
    expect(get).toHaveBeenCalledExactlyOnceWith('/environments/env-1/discovery-schedules', { query: undefined });
    get.mockResolvedValueOnce(page({ next_cursor: id('b'), items: [item('b')] }));
    await expect(listDiscoverySchedules('env-1', id('a'))).resolves.toMatchObject({ next_cursor: id('b') });
    expect(get).toHaveBeenLastCalledWith('/environments/env-1/discovery-schedules', { query: { cursor: id('a') } });
  });

  it('rejects a non-advancing page instead of appending duplicates', async () => {
    get.mockResolvedValueOnce(page({ items: [item('a')] }));
    await expect(listDiscoverySchedules('env-1', id('a'))).rejects.toThrow();
  });

  it('rejects invalid environment or cursor before any request', async () => {
    await expect(listDiscoverySchedules('../other')).rejects.toThrow('环境标识无效');
    await expect(listDiscoverySchedules('env-1', 'not-a-cursor')).rejects.toThrow('分页游标无效');
    expect(get).not.toHaveBeenCalled();
  });

  it('propagates transport errors and never retries', async () => {
    get.mockRejectedValueOnce(new Error('network down'));
    await expect(listDiscoverySchedules('env-1')).rejects.toThrow('network down');
    expect(get).toHaveBeenCalledExactlyOnceWith('/environments/env-1/discovery-schedules', { query: undefined });
  });
});

describe('revokeDiscoverySchedule', () => {
  it('posts exactly the expected_revision payload and requires a matching revoked state', async () => {
    post.mockResolvedValueOnce(state());
    await expect(revokeDiscoverySchedule('env-1', id('a'), 3)).resolves.toMatchObject({ status: 'revoked' });
    expect(post).toHaveBeenCalledExactlyOnceWith('/environments/env-1/discovery-schedules/' + id('a') + '/revoke',
      { expected_revision: 3 });
  });

  it('rejects responses that do not match the requested plan or the state contract', async () => {
    const patches = [
      { schedule_id: id('b') }, { status: 'active' }, { schema_version: 'other/v1' },
      { intent_digest: 'z'.repeat(64) }, { extra: 1 }, { revision: '4' },
      { revision: 2 },
    ];
    for (const patch of patches) {
      post.mockResolvedValueOnce({ ...state(), ...patch });
      await expect(revokeDiscoverySchedule('env-1', id('a'), 3)).rejects.toThrow('撤销结果待核对');
    }
    expect(post).toHaveBeenCalledTimes(patches.length);
  });

  it('rejects invalid inputs before any write', async () => {
    await expect(revokeDiscoverySchedule('env-1', 'eds-short', 0)).rejects.toThrow();
    await expect(revokeDiscoverySchedule('env-1', id('a'), -1)).rejects.toThrow('计划版本无效');
    expect(post).not.toHaveBeenCalled();
  });

  it('propagates transport errors; caller decides, no automatic resend', async () => {
    post.mockRejectedValueOnce(new Error('timeout'));
    await expect(revokeDiscoverySchedule('env-1', id('a'), 0)).rejects.toThrow('timeout');
    expect(post).toHaveBeenCalledTimes(1);
  });
});
