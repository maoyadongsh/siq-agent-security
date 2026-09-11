import type { Confirmation, Grant } from './types';

export const NOTICE_LIMIT = 512;
export const NOTICE_INTERVAL_MS = 15000;
export interface NoticeTarget { key: string; href: string }
export interface NoticeState { keys: string[]; sentAt: number }

export function noticeTargets(items: Confirmation[], grants: Grant[], now: number): NoticeTarget[] {
  return [
    ...items.filter((item) => item.status === 'pending' && item.expires_at && Date.parse(item.expires_at) > now)
      .map((item) => ({ key: `call:${item.action_id}:${item.decision_hash}`, href: `/confirmations?request=${encodeURIComponent(item.action_id)}` })),
    ...grants.filter((grant) => grant.status === 'pending_approval')
      .map((grant) => ({ key: `grant:${grant.grant_id}:${grant.state_revision}`, href: `/grants?grant=${encodeURIComponent(grant.grant_id)}` })),
  ];
}
export function readNoticeState(raw: string | null): NoticeState {
  try {
    if (!raw || raw.length > 40000) return { keys: [], sentAt: 0 };
    const data: unknown = JSON.parse(raw);
    if (data && typeof data === 'object' && 'keys' in data && 'sentAt' in data
      && Array.isArray(data.keys) && data.keys.length <= NOTICE_LIMIT
      && data.keys.every((key: unknown) => typeof key === 'string' && /^[a-f0-9]{64}$/.test(key))
      && typeof data.sentAt === 'number' && Number.isFinite(data.sentAt) && data.sentAt >= 0) {
      return { keys: data.keys, sentAt: data.sentAt };
    }
  } catch { /* Invalid notification metadata grants no authority. */ }
  return { keys: [], sentAt: 0 };
}
export function newNoticeKeys(keys: string[], previous: NoticeState, now: number): string[] {
  if (now >= previous.sentAt && now - previous.sentAt < NOTICE_INTERVAL_MS) return [];
  const seen = new Set(previous.keys);
  return keys.filter((key) => !seen.has(key));
}
