import { get, post } from './client';
import { parseRevokeOptions, selectionKey, type NetworkSelection, type RevokeOptions, type RevokeResult } from './networkRevoke';

export interface BatchRevokeSelection { options: RevokeOptions; selections: NetworkSelection[] }
export interface BatchRevokeResult {
  schema_version: 'enterprise-network-revoke-batch-result/v1';
  items: RevokeResult[]; requires_independent_approval: true; executed: false;
}
export interface BatchRevokeRecoveryItem {
  source_policy_id: string; policy_id: string; change_request_id: string; change_status: string;
}
export interface BatchRevokeRecovery {
  schema_version: 'enterprise-network-revoke-batch-recovery/v1';
  items: BatchRevokeRecoveryItem[]; lookup_executed: false;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string[]) => Object.keys(v).length === names.length && names.every(name => Object.hasOwn(v, name));
const text = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 64;
const uuid = (value: string) => value.length === 36 && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const bounded = (value: unknown): value is unknown[] => Array.isArray(value) && value.length > 0 && value.length <= 20;

export function buildRevokeBatch(items: BatchRevokeSelection[], requestKey: string) {
  if (!uuid(requestKey) || !bounded(items)) throw new Error('批量申请标识或数量无效');
  const entries = items.map(item => {
    if (!text(item.options.policy_id)) throw new Error('策略标识无效');
    const options = parseRevokeOptions(item.options, item.options.policy_id);
    // Reuse the strict pair/duplicate/budget checks without inferring authority from selected facts.
    parseRevokeOptions({ ...options, selections: item.selections }, options.policy_id);
    const available = new Set(options.selections.map(selectionKey));
    if (!item.selections.length || item.selections.some(selection => !available.has(selectionKey(selection)))) throw new Error('批量选择超出策略快照');
    return { policy_id: options.policy_id, baseline_digest: options.baseline_digest,
      selections: item.selections.map(selection => ({ endpoint: selection.endpoint, binary_path: selection.binary_path })) };
  });
  if (new Set(entries.map(item => item.policy_id)).size !== entries.length
    || entries.reduce((count, item) => count + item.selections.length, 0) > 512) throw new Error('批量策略重复或选择超过上限');
  return { schema_version: 'enterprise-network-revoke-batch/v1' as const, request_key: requestKey, items: entries };
}

function uniqueIdentities(items: Record<string, unknown>[]) {
  const sources = new Set(items.map(item => item.source_policy_id));
  return sources.size === items.length
    && new Set(items.map(item => item.policy_id)).size === items.length
    && new Set(items.map(item => item.change_request_id)).size === items.length
    && items.every(item => text(item.source_policy_id) && text(item.policy_id) && text(item.change_request_id) && !sources.has(item.policy_id));
}

export function parseRevokeBatchResult(value: unknown, expectedSources: string[]): BatchRevokeResult {
  if (!object(value) || !keys(value, ['schema_version', 'items', 'requires_independent_approval', 'executed'])
    || value.schema_version !== 'enterprise-network-revoke-batch-result/v1'
    || value.requires_independent_approval !== true || value.executed !== false || !bounded(value.items)
    || value.items.length !== expectedSources.length || new Set(expectedSources).size !== expectedSources.length
    || !value.items.every(item => object(item)
      && keys(item, ['schema_version', 'source_policy_id', 'policy_id', 'change_request_id', 'requires_independent_approval', 'executed'])
      && item.schema_version === 'enterprise-network-revoke-proposal-result/v1'
      && item.requires_independent_approval === true && item.executed === false
      && expectedSources.includes(item.source_policy_id as string))
    || !uniqueIdentities(value.items as Record<string, unknown>[])) throw new Error('批量申请结果待核对');
  return value as unknown as BatchRevokeResult;
}

export async function proposeRevokeBatch(items: BatchRevokeSelection[], requestKey: string) {
  const body = buildRevokeBatch(items, requestKey);
  return parseRevokeBatchResult(await post<unknown>('/network-revoke-batches', body), body.items.map(item => item.policy_id));
}

export async function readRevokeBatch(requestKey: string): Promise<BatchRevokeRecovery> {
  if (!uuid(requestKey)) throw new Error('批量恢复标识无效');
  const value = await get<unknown>(`/network-revoke-batches/${encodeURIComponent(requestKey)}`);
  if (!object(value) || !keys(value, ['schema_version', 'items', 'lookup_executed'])
    || value.schema_version !== 'enterprise-network-revoke-batch-recovery/v1' || value.lookup_executed !== false
    || !bounded(value.items) || !value.items.every(item => object(item)
      && keys(item, ['source_policy_id', 'policy_id', 'change_request_id', 'change_status']) && text(item.change_status))
    || !uniqueIdentities(value.items as Record<string, unknown>[])) throw new Error('批量恢复结果待核对');
  return value as unknown as BatchRevokeRecovery;
}
