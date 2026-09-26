import { get, post } from './client';
export interface NetworkSelection { endpoint: string; binary_path: string }
export interface RevokeOptions {
  schema_version: 'enterprise-network-revoke-options/v1'; policy_id: string; policy_version: number;
  baseline_digest: string; selections: NetworkSelection[]; coverage: 'complete_policy_network';
}
export interface RevokeResult {
  schema_version: 'enterprise-network-revoke-proposal-result/v1'; source_policy_id: string;
  policy_id: string; change_request_id: string; requires_independent_approval: true; executed: false;
}
export interface RevokeRecovery {
  schema_version: 'enterprise-network-revoke-recovery/v1'; source_policy_id: string;
  policy_id: string; change_request_id: string; change_status: string; lookup_executed: false;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const keys = (v: Record<string, unknown>, expected: string[]) => Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
export const selectionKey = (s: NetworkSelection) => JSON.stringify([s.endpoint, s.binary_path]);
export function parseRevokeOptions(value: unknown, id: string): RevokeOptions {
  if (!object(value) || !keys(value, ['schema_version', 'policy_id', 'policy_version', 'baseline_digest', 'selections', 'coverage'])
    || value.schema_version !== 'enterprise-network-revoke-options/v1' || value.policy_id !== id
    || !Number.isSafeInteger(value.policy_version) || (value.policy_version as number) < 1
    || !text(value.baseline_digest, 64) || !/^[a-f0-9]{64}$/.test(value.baseline_digest)
    || value.coverage !== 'complete_policy_network' || !Array.isArray(value.selections) || value.selections.length > 256
    || !value.selections.every(s => object(s) && keys(s, ['endpoint', 'binary_path']) && text(s.endpoint, 512) && text(s.binary_path, 512))
    || new Set((value.selections as NetworkSelection[]).map(selectionKey)).size !== value.selections.length) throw new Error('撤除选项响应无效');
  return value as unknown as RevokeOptions;
}
export async function readRevokeOptions(id: string) {
  return parseRevokeOptions(await get<unknown>(`/policies/${encodeURIComponent(id)}/network-revoke-options`), id);
}
export async function readRevokeRecovery(policyId: string, requestKey: string): Promise<RevokeRecovery> {
  if (!text(policyId, 64) || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(requestKey)) throw new Error('恢复标识无效');
  const value = await get<unknown>(`/policies/${encodeURIComponent(policyId)}/network-revoke-proposals/${encodeURIComponent(requestKey)}`);
  if (!object(value) || !keys(value, ['schema_version', 'source_policy_id', 'policy_id', 'change_request_id', 'change_status', 'lookup_executed'])
    || value.schema_version !== 'enterprise-network-revoke-recovery/v1' || value.source_policy_id !== policyId
    || !text(value.policy_id, 64) || !text(value.change_request_id, 64) || !text(value.change_status, 64)
    || value.lookup_executed !== false) throw new Error('恢复响应无法核对');
  return value as unknown as RevokeRecovery;
}
export async function proposeNetworkRevoke(options: RevokeOptions, selections: NetworkSelection[], requestKey: string): Promise<RevokeResult> {
  const available = new Set(options.selections.map(selectionKey));
  if (!selections.length || selections.length > 256 || new Set(selections.map(selectionKey)).size !== selections.length
    || selections.some(s => !available.has(selectionKey(s)))) throw new Error('撤除选择无效');
  const value = await post<unknown>(`/policies/${encodeURIComponent(options.policy_id)}/network-revoke-proposals`, {
    schema_version: 'enterprise-network-revoke-proposal/v1', baseline_digest: options.baseline_digest,
    request_key: requestKey, selections,
  });
  if (!object(value) || !keys(value, ['schema_version', 'source_policy_id', 'policy_id', 'change_request_id', 'requires_independent_approval', 'executed'])
    || value.schema_version !== 'enterprise-network-revoke-proposal-result/v1' || value.source_policy_id !== options.policy_id
    || !text(value.policy_id, 64) || value.policy_id === options.policy_id || !text(value.change_request_id, 64)
    || value.requires_independent_approval !== true || value.executed !== false) throw new Error('申请结果待核对');
  return value as unknown as RevokeResult;
}
