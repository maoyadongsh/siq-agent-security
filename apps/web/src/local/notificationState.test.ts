import { describe, expect, it } from 'vitest';
import { NOTICE_LIMIT, newNoticeKeys, noticeTargets, readNoticeState } from './notificationState';
import type { Confirmation, Grant } from './types';

const digest = 'a'.repeat(64);
const item: Confirmation = { action_id: 'action-fixture', decision_receipt_id: 'receipt-fixture', decision_hash: digest,
  params_digest: digest, platform: 'hermes', agent_id: 'private-agent', session_id: 'private-session', tool: 'private-tool',
  tool_call_id: 'private-call', grant_id: 'grant-fixture', issued_at: '2026-09-10T00:00:00Z', expires_at: '2026-09-10T00:01:00Z',
  params_excerpt: '/private/path', status: 'pending' };

describe('notification metadata and selection', () => {
  it('excludes resolved/expired calls at the exact deadline and contains no tool or parameter text', () => {
    const now = Date.parse(item.expires_at!);
    expect(noticeTargets([item], [], now)).toEqual([]);
    const targets = noticeTargets([item, { ...item, status: 'approved' }], [], now - 1);
    expect(targets).toHaveLength(1);
    expect(targets[0].href).toBe('/confirmations?request=action-fixture');
    expect(JSON.stringify(targets)).not.toContain('private');
  });
  it('only selects pending grants and encodes the local detail URL', () => {
    const pending = { grant_id: 'fixture&other=1', state_revision: 2, status: 'pending_approval' } as Grant;
    const targets = noticeTargets([], [pending, { ...pending, status: 'approved' }], Date.now());
    expect(targets).toHaveLength(1);
    expect(targets[0].href).toBe('/grants?grant=fixture%26other%3D1');
  });
  it('rejects malformed or oversized stored metadata without accepting raw identifiers', () => {
    for (const value of [null, '{', JSON.stringify({ keys: ['raw-tool'], sentAt: 1 }), JSON.stringify({ keys: Array(NOTICE_LIMIT + 1).fill(digest), sentAt: 1 }), JSON.stringify({ keys: [], sentAt: -1 }), 'x'.repeat(40001)]) {
      expect(readNoticeState(value)).toEqual({ keys: [], sentAt: 0 });
    }
    expect(readNoticeState(JSON.stringify({ keys: [digest], sentAt: 100 }))).toEqual({ keys: [digest], sentAt: 100 });
  });
  it('deduplicates unchanged requests while allowing new requests after the cooldown', () => {
    const other = 'b'.repeat(64);
    const previous = { keys: [digest], sentAt: 10000 };
    expect(newNoticeKeys([digest, other], previous, 24999)).toEqual([]);
    expect(newNoticeKeys([digest, other], previous, 25000)).toEqual([other]);
    expect(newNoticeKeys([digest], previous, 99999)).toEqual([]);
    expect(newNoticeKeys([other], previous, 9000)).toEqual([other]);
  });
});
