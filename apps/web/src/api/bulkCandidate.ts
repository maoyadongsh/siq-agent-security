import { api, post } from './client';
import type { AgentAsset } from './types';

const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
export function validBulkSelection(rows: AgentAsset[]): boolean {
  return rows.length > 0 && rows.length <= 50 && new Set(rows.map(row => row.id)).size === rows.length
    && rows.every(row => !!row.id && ['candidate', 'needs_review'].includes(row.status)
      && typeof row.updated_at === 'string' && Number.isFinite(Date.parse(row.updated_at)));
}
export type BulkAction = 'confirm' | 'dismiss';
export type DismissReason = 'duplicate' | 'out_of_scope' | 'not_agent';
export function assertBulkReadback(value: unknown, rows: AgentAsset[], action: BulkAction = 'confirm'): void {
  if (!record(value) || value.schema_version !== `enterprise-candidate-bulk-${action}-result/v1`
    || !Array.isArray(value.items) || value.items.length !== rows.length
    || !value.items.every((item, index) => record(item) && item.id === rows[index].id && item.status === (action === 'confirm' ? 'confirmed' : 'dismissed')
      && typeof item.updated_at === 'string' && Number.isFinite(Date.parse(item.updated_at)))) {
    throw new Error('批量处理结果尚未核对');
  }
}
export async function confirmCandidateBatch(rows: AgentAsset[]): Promise<void> {
  if (!validBulkSelection(rows)) throw new Error('请选择 1–50 个有效候选');
  const result = await post<unknown>('/candidates/bulk-confirm', {
    schema_version: 'enterprise-candidate-bulk-confirm/v1',
    items: rows.map(row => ({ asset_id: row.id, expected_updated_at: row.updated_at })),
  });
  assertBulkReadback(result, rows);
}
export async function dismissCandidateBatch(rows: AgentAsset[], reason: DismissReason): Promise<void> {
  if (!validBulkSelection(rows) || !['duplicate', 'out_of_scope', 'not_agent'].includes(reason)) throw new Error('请选择有效候选和驳回原因');
  const result = await post<unknown>('/candidates/bulk-dismiss', {
    schema_version: 'enterprise-candidate-bulk-dismiss/v1', reason_code: reason,
    items: rows.map(row => ({ asset_id: row.id, expected_updated_at: row.updated_at })),
  });
  assertBulkReadback(result, rows, 'dismiss');
}
export async function readCandidateBatch(rows: AgentAsset[]): Promise<AgentAsset[]> {
  if (!rows.length || rows.length > 50 || new Set(rows.map(row => row.id)).size !== rows.length) throw new Error('无效选择');
  const result: AgentAsset[] = [];
  // Independent reads, bounded concurrency; never retry the write to reconcile.
  for (let start = 0; start < rows.length; start += 5) {
    const group = rows.slice(start, start + 5);
    const current = await Promise.all(group.map(row => api.getAgent(row.id)));
    if (current.some((row, index) => !row || row.id !== group[index].id || !Number.isFinite(Date.parse(row.updated_at))
      || !['candidate', 'needs_review', 'confirmed', 'managed', 'stale', 'retired', 'dismissed'].includes(row.status))) {
      throw new Error('候选身份或状态无法核验');
    }
    result.push(...current);
  }
  return result;
}
