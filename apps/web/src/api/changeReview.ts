import { get, post } from './client';

export const changeStatus = (status: string) => ({ proposed: '待审批', approved: '已批准，待部署', rejected: '已驳回', deploying: '部署中', effective: '后端标记已生效', failed: '部署失败', rolled_back: '已回滚', emergency_applied: '紧急已批准，仍需核对执行与复核', post_review_due: '待复核' }[status] ?? '状态待核对');
export const modeLabel = (mode: string) => ({ audit_only: '仅记录', warn: '提醒', block: '拦截' }[mode] ?? '未知模式');
export const blockerLabels: Record<string, string> = {
  missing_permission: '当前账号没有审批权限，请联系组织管理员。', not_proposed: '此变更已处理，不能再次审批。',
  own_proposal: '提出者不能批准自己的变更，请由另一位有权限的审批人处理。',
  incomplete_content: '内容包含已隐藏或超出展示上限的部分，无法完整审查；请提出者整理后重新提交。',
  policy_invalid: '策略尚未通过静态校验，请提出者修正后重新提交。',
  downgrade_requires_high_risk: '保护模式低于前一版本，需要按高风险变更重新提交。',
};
export interface ChangeReview {
  schema_version: 'change-review/v1'; change_id: string; status: string; policy_name: string; policy_version: number;
  enforcement_mode: 'audit_only' | 'warn' | 'block'; approval_policy: 'standard' | 'high_risk' | 'break_glass';
  proposer_id: string; approver_id: string | null; review_digest: string;
  sections: { key: string; label: string; content: string; redacted: boolean; truncated: boolean }[];
  can_approve: boolean; can_reject: boolean; approve_blockers: string[]; reject_blockers: string[];
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max = 256): v is string => typeof v === 'string' && v.length <= max;
const keys = (v: Record<string, unknown>, expected: string[]) => Object.keys(v).length === expected.length && expected.every(k => k in v);
export function parseChangeReview(value: unknown, id: string): ChangeReview {
  if (!object(value) || !keys(value, ['schema_version', 'change_id', 'status', 'policy_name', 'policy_version', 'enforcement_mode', 'approval_policy', 'proposer_id', 'approver_id', 'review_digest', 'sections', 'can_approve', 'can_reject', 'approve_blockers', 'reject_blockers']) || value.schema_version !== 'change-review/v1' || value.change_id !== id || !text(value.status, 64) || !text(value.policy_name, 6000) || !Number.isInteger(value.policy_version) || (value.policy_version as number) < 1 || !['audit_only', 'warn', 'block'].includes(String(value.enforcement_mode)) || !['standard', 'high_risk', 'break_glass'].includes(String(value.approval_policy)) || !text(value.proposer_id) || !(value.approver_id === null || text(value.approver_id)) || !text(value.review_digest) || !/^[a-f0-9]{64}$/.test(value.review_digest) || typeof value.can_approve !== 'boolean' || typeof value.can_reject !== 'boolean') throw new Error('审查响应不完整或对象不匹配');
  for (const k of ['approve_blockers', 'reject_blockers'] as const) {
    const list = value[k];
    if (!Array.isArray(list) || list.length > (k === 'approve_blockers' ? 6 : 2) || !list.every(x => typeof x === 'string' && Object.hasOwn(blockerLabels, x)) || new Set(list).size !== list.length) throw new Error('审批权限响应不完整');
  }
  if (value.can_approve !== ((value.approve_blockers as string[]).length === 0) || value.can_reject !== ((value.reject_blockers as string[]).length === 0)) throw new Error('审批权限响应不一致');
  if (!Array.isArray(value.sections) || value.sections.length !== 15 || !value.sections.every(s => object(s) && keys(s, ['key', 'label', 'content', 'redacted', 'truncated']) && text(s.key, 64) && text(s.label, 128) && text(s.content, 6000) && typeof s.redacted === 'boolean' && typeof s.truncated === 'boolean')) throw new Error('策略内容响应不完整');
  const required = ['selector', 'filesystem', 'network', 'process', 'model_routing', 'tools', 'tool_policies', 'data_scope_refs', 'secrets', 'resources', 'audit', 'exceptions', 'impact', 'validation', 'previous'];
  if (!required.every(k => (value.sections as ChangeReview['sections']).some(s => s.key === k)) || value.can_approve && (value.status !== 'proposed' || value.sections.some(s => s.redacted || s.truncated))) throw new Error('审查章节缺失或审批响应不一致');
  return value as unknown as ChangeReview;
}
export async function readChangeReview(id: string): Promise<ChangeReview> {
  return parseChangeReview(await get<unknown>(`/change-requests/${encodeURIComponent(id)}/review`), id);
}
export function submitChangeReview(snapshot: ChangeReview, decision: 'approve' | 'reject'): Promise<unknown> {
  return post(`/change-requests/${encodeURIComponent(snapshot.change_id)}/review-decision`, { schema_version: 'change-review-decision/v1', decision, review_digest: snapshot.review_digest });
}
