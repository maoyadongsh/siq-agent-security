import type { Grant } from './types';

export interface GrantBatchPlan {
  schema_version: 'grant-batch-revoke-plan/v1';
  signing_schema: 'local_canonical/v1';
  signature: string;
  batch_id: string;
  actor_id: string;
  action: 'revoke';
  expires_at: string;
  items: { grant_id: string; expected_revision: number; subject_id: string; platform: string; status: string }[];
}
export interface GrantBatchResult {
  schema_version: 'grant-batch-revoke-result/v1';
  batch_id: string;
  items: { grant_id: string; status: 'revoked' | 'already_revoked' | 'conflict' | 'unavailable'; state_revision?: number }[];
}
export const revocableStatuses = ['draft', 'pending_approval', 'approved', 'deployed', 'effective'];
export const canBatchRevoke = (g: Grant) => revocableStatuses.includes(g.status)
  && Number.isSafeInteger(g.state_revision) && g.state_revision! >= 0;

/** Reject mismatched server responses; HTTP 200 alone never means the batch succeeded. */
export function validBatchPlan(value: unknown, targets: { grant_id: string; expected_revision: number }[], actor: string): value is GrantBatchPlan {
  const p = value as GrantBatchPlan | null;
  return !!p && p.schema_version === 'grant-batch-revoke-plan/v1' && p.signing_schema === 'local_canonical/v1'
    && /^[a-f0-9]{128}$/.test(p.signature) && /^gb-[a-f0-9]{64}$/.test(p.batch_id)
    && p.actor_id === actor.trim() && p.action === 'revoke' && Date.parse(p.expires_at) > Date.now()
    && Array.isArray(p.items) && p.items.length === targets.length && p.items.length > 0 && p.items.length <= 50
    && p.items.every((item, i) => item?.grant_id === targets[i].grant_id && item.expected_revision === targets[i].expected_revision
      && typeof item.subject_id === 'string' && typeof item.platform === 'string' && revocableStatuses.includes(item.status));
}
export function validBatchResult(value: unknown, p: GrantBatchPlan): value is GrantBatchResult {
  const r = value as GrantBatchResult | null;
  return !!r && r.schema_version === 'grant-batch-revoke-result/v1' && r.batch_id === p.batch_id
    && Array.isArray(r.items) && r.items.length === p.items.length
    && r.items.every((item, i) => item?.grant_id === p.items[i].grant_id
      && ['revoked', 'already_revoked', 'conflict', 'unavailable'].includes(item.status)
      && (item.state_revision === undefined || (Number.isSafeInteger(item.state_revision) && item.state_revision >= 0))
      && (item.status !== 'revoked' || item.state_revision === p.items[i].expected_revision + 1)
      && (!['revoked', 'already_revoked'].includes(item.status) || item.state_revision !== undefined));
}
