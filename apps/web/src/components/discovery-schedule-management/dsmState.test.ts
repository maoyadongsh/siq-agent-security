import { describe, expect, it } from 'vitest';
import type { DiscoveryScheduleItem, DiscoverySchedulePage } from '@/api/discoveryScheduleManagement';
import { canOfferRevoke, dsmReducer, initialDsmState, remainingBudget, revokeFailureMessage, statusLabel,
  windowLabel, windowState } from './dsmState';

const item = (over: Partial<DiscoveryScheduleItem> = {}): DiscoveryScheduleItem => ({
  schedule_id: 'eds-' + 'a'.repeat(32), edge_agent_id: 'edge-1', status: 'active', revision: 3,
  starts_at: '2026-09-26T00:00:00Z', expires_at: '2026-09-27T00:00:00Z', interval_seconds: 900,
  max_runs: 4, reserved_runs: 1, last_reserved_slot: 0, created_at: '2026-09-25T00:00:00Z', ...over,
});
const page = (items: DiscoveryScheduleItem[], over: Partial<DiscoverySchedulePage> = {}): DiscoverySchedulePage => ({
  schema_version: 'enterprise-discovery-schedule-management/v1', environment_id: 'env-1',
  evaluated_at: '2026-09-26T01:00:00Z', can_revoke: true, items, next_cursor: null, ...over,
});

describe('load lifecycle', () => {
  it('starts empty, replaces on success, and ignores late responses from a previous load', () => {
    let state = initialDsmState();
    state = dsmReducer(state, { type: 'loadStart', ticket: 1 });
    expect(state.phase).toBe('loading');
    state = dsmReducer(state, { type: 'loadSuccess', ticket: 1, page: page([item()], { next_cursor: 'eds-' + 'b'.repeat(32) }) });
    expect(state.phase).toBe('ready');
    expect(state.items).toHaveLength(1);
    expect(state.nextCursor).toBe('eds-' + 'b'.repeat(32));
    expect(state.canRevoke).toBe(true);
    // A→B 迟到隔离：旧请求的响应不得覆盖新范围。
    const ready = state;
    state = dsmReducer(state, { type: 'loadStart', ticket: 2 });
    state = dsmReducer(state, { type: 'loadSuccess', ticket: 1, page: page([item({ schedule_id: 'eds-' + 'c'.repeat(32) })]) });
    expect(state.phase).toBe('loading');
    expect(state.items).toHaveLength(0);
    state = dsmReducer(state, { type: 'loadSuccess', ticket: 2, page: page([]) });
    expect(state.phase).toBe('ready');
    expect(state.items).toHaveLength(0);
    expect(ready.items).toHaveLength(1);
  });

  it('first failure sets an alert with retry, keeps nothing fabricated', () => {
    let state = initialDsmState();
    state = dsmReducer(state, { type: 'loadStart', ticket: 1 });
    state = dsmReducer(state, { type: 'loadFailure', ticket: 1 });
    expect(state.phase).toBe('error');
    expect(state.message?.kind).toBe('alert');
    expect(state.items).toHaveLength(0);
    const stale = state;
    state = dsmReducer(state, { type: 'loadFailure', ticket: 999 });
    expect(state).toBe(stale);
  });

  it('load-more failure keeps loaded pages and the same cursor for retry', () => {
    let state = initialDsmState();
    state = dsmReducer(state, { type: 'loadStart', ticket: 1 });
    state = dsmReducer(state, { type: 'loadSuccess', ticket: 1, page: page([item()], { next_cursor: 'eds-' + 'b'.repeat(32) }) });
    state = dsmReducer(state, { type: 'loadMoreStart', ticket: 2 });
    expect(state.morePhase).toBe('loading');
    state = dsmReducer(state, { type: 'loadMoreFailure', ticket: 2 });
    expect(state.morePhase).toBe('error');
    expect(state.canRevoke).toBe(false);
    expect(state.items).toHaveLength(1);
    expect(state.nextCursor).toBe('eds-' + 'b'.repeat(32));
    // 同游标重试成功后追加，不替换。
    state = dsmReducer(state, { type: 'loadMoreStart', ticket: 3 });
    state = dsmReducer(state, { type: 'loadMoreSuccess', ticket: 3, page: page([item({ schedule_id: 'eds-' + 'b'.repeat(32) })]) });
    expect(state.items.map(row => row.schedule_id)).toEqual(['eds-' + 'a'.repeat(32), 'eds-' + 'b'.repeat(32)]);
    expect(state.nextCursor).toBeNull();
    expect(state.morePhase).toBe('idle');
    expect(state.message).toBeNull();
  });

  it('a refresh invalidates an in-flight load-more and stale appends are ignored', () => {
    let state = initialDsmState();
    state = dsmReducer(state, { type: 'loadStart', ticket: 1 });
    state = dsmReducer(state, { type: 'loadSuccess', ticket: 1, page: page([item()], { next_cursor: 'eds-' + 'b'.repeat(32) }) });
    state = dsmReducer(state, { type: 'loadMoreStart', ticket: 2 });
    state = dsmReducer(state, { type: 'loadStart', ticket: 3 });
    state = dsmReducer(state, { type: 'loadMoreSuccess', ticket: 2, page: page([item({ schedule_id: 'eds-' + 'c'.repeat(32) })]) });
    expect(state.phase).toBe('loading');
    expect(state.items).toHaveLength(0);
  });

  it('loadMoreStart is refused outside a ready page', () => {
    let state = initialDsmState();
    state = dsmReducer(state, { type: 'loadMoreStart', ticket: 1 });
    expect(state.morePhase).toBe('idle');
    expect(state.moreTicket).toBe(0);
  });
});

describe('revoke flow', () => {
  const loadReady = () => {
    let state = initialDsmState();
    state = dsmReducer(state, { type: 'loadStart', ticket: 1 });
    return dsmReducer(state, { type: 'loadSuccess', ticket: 1, page: page([item()]) });
  };

  it('opens only for revocable records; cancel is a zero-write close', () => {
    let state = loadReady();
    state = dsmReducer(state, { type: 'revokeOpen', item: item() });
    expect(state.revokeTarget?.schedule_id).toBe(item().schedule_id);
    state = dsmReducer(state, { type: 'revokeCancel' });
    expect(state.revokeTarget).toBeNull();
    const nonRevocable = [item({ status: 'revoked' as const })];
    for (const candidate of nonRevocable) {
      expect(canOfferRevoke(candidate, true)).toBe(false);
      state = dsmReducer({ ...state, canRevoke: true }, { type: 'revokeOpen', item: candidate });
      expect(state.revokeTarget).toBeNull();
    }
    expect(canOfferRevoke(item(), false)).toBe(false);
  });

  it('guards double submit and closes the dialog with a confirmed message on success', () => {
    let state = loadReady();
    state = dsmReducer(state, { type: 'revokeOpen', item: item() });
    state = dsmReducer(state, { type: 'revokeStart' });
    expect(state.revokeBusy).toBe(true);
    expect(dsmReducer(state, { type: 'revokeStart' })).toBe(state);
    expect(dsmReducer(state, { type: 'revokeCancel' })).toBe(state);
    expect(dsmReducer(state, { type: 'loadStart', ticket: 2 })).toBe(state);
    state = dsmReducer(state, { type: 'revokeSuccess' });
    expect(state.revokeBusy).toBe(false);
    expect(state.revokeTarget).toBeNull();
    expect(state.message?.kind).toBe('status');
  });

  it('does not open or submit a revoke while a page or its permission is unverified', () => {
    let state = loadReady();
    state = dsmReducer(state, { type: 'revokeOpen', item: item() });
    state = dsmReducer(state, { type: 'loadStart', ticket: 2 });
    expect(state.revokeTarget).toBeNull();
    expect(dsmReducer(state, { type: 'revokeOpen', item: item() })).toBe(state);
    expect(dsmReducer(state, { type: 'revokeStart' })).toBe(state);
  });

  it('failure closes the dialog with the exact outcome text and never fakes success', () => {
    let state = loadReady();
    state = dsmReducer(state, { type: 'revokeOpen', item: item() });
    state = dsmReducer(state, { type: 'revokeStart' });
    state = dsmReducer(state, { type: 'revokeFailure', text: revokeFailureMessage(409) });
    expect(state.revokeBusy).toBe(false);
    expect(state.revokeTarget).toBeNull();
    expect(state.message?.kind).toBe('alert');
    expect(state.message?.text).toContain('不会自动用新版本重试');
    expect(state.canRevoke).toBe(false);
  });
});

describe('interpretation helpers', () => {
  it('labels statuses in Chinese without upgrading unknowns to active', () => {
    expect(statusLabel('pending_confirmation')).toBe('待设备确认');
    expect(statusLabel('active')).toBe('已确认的计划');
    expect(statusLabel('paused')).toBe('已暂停');
    expect(statusLabel('revoked')).toBe('已撤销');
  });

  it('derives window facts from the server evaluated_at only', () => {
    expect(windowLabel(windowState(item(), '2026-09-25T23:00:00Z'))).toBe('窗口未开始');
    expect(windowLabel(windowState(item(), '2026-09-26T12:00:00Z'))).toBe('窗口内');
    expect(windowLabel(windowState(item(), '2026-09-27T00:00:00Z'))).toBe('已过期');
  });

  it('explains budget as unreserved rounds, not successful scans', () => {
    expect(remainingBudget(item({ max_runs: 4, reserved_runs: 1 }))).toBe(3);
  });
});
