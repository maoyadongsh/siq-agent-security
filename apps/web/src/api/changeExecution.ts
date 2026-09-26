import { get } from './client';

export interface DeploymentHistory {
  id: string; environment_id: string; environment_name: string | null; binding_id: string | null; target: string;
  status: string; created_at: string;
  verification_level: 'none' | 'config_readback' | 'behavior_enforced' | 'failed' | 'stale' | 'unknown';
  independent_result: 'not_checked' | 'verified' | 'mismatch' | 'unreachable' | 'no_receipt' | 'unknown';
  backend_mutated: boolean | null; error_digest: string | null;
}
export interface ChangeExecution {
  schema_version: 'change-execution/v1'; change_id: string; change_status: string; evaluated_at: string;
  deployments: DeploymentHistory[]; deployments_truncated: boolean; expanded: boolean;
  audit_access: 'allowed' | 'denied'; audit_truncated: boolean;
  audit_events: { id: string; action: string; actor_id: string; resource_id: string; created_at: string; review_digest: string | null; error_digest: string | null }[];
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max = 64): v is string => typeof v === 'string' && v.length <= max;
const nullableText = (v: unknown, max = 64) => v === null || text(v, max);
const oneOf = (v: unknown, allowed: readonly string[]): v is string => typeof v === 'string' && allowed.includes(v);
// Date.parse 会把 2026-02-30 之类不存在的日期滚动到邻近日期：用 UTC 回读校验日历日期真实存在。
const date = (v: unknown) => {
  if (!text(v, 40) || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(v)) return false;
  const time = Date.parse(v);
  if (!Number.isFinite(time)) return false;
  const d = new Date(time);
  const pad = (n: number, width: number) => String(n).padStart(width, '0');
  return v.slice(0, 10) === `${pad(d.getUTCFullYear(), 4)}-${pad(d.getUTCMonth() + 1, 2)}-${pad(d.getUTCDate(), 2)}`;
};
const digest = (v: unknown) => v === null || typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => k in v);
export function parseChangeExecution(v: unknown, id: string): ChangeExecution {
  if (!object(v) || !exact(v, ['schema_version', 'change_id', 'change_status', 'evaluated_at', 'deployments', 'deployments_truncated', 'audit_access', 'audit_events', 'audit_truncated', 'expanded']) || v.schema_version !== 'change-execution/v1' || v.change_id !== id || !text(v.change_status, 32) || !date(v.evaluated_at) || typeof v.expanded !== 'boolean' || typeof v.deployments_truncated !== 'boolean' || typeof v.audit_truncated !== 'boolean' || !oneOf(v.audit_access, ['allowed', 'denied'])) throw new Error('执行记录响应不完整或对象不匹配');
  if (!Array.isArray(v.deployments) || v.deployments.length > (v.expanded ? 100 : 20) || !v.deployments.every(d => object(d) && exact(d, ['id', 'environment_id', 'environment_name', 'binding_id', 'target', 'status', 'created_at', 'verification_level', 'independent_result', 'backend_mutated', 'error_digest']) && text(d.id) && text(d.environment_id) && nullableText(d.environment_name, 128) && nullableText(d.binding_id) && text(d.target, 128) && text(d.status, 32) && date(d.created_at) && oneOf(d.verification_level, ['none', 'config_readback', 'behavior_enforced', 'failed', 'stale', 'unknown']) && oneOf(d.independent_result, ['not_checked', 'verified', 'mismatch', 'unreachable', 'no_receipt', 'unknown']) && (d.backend_mutated === null || typeof d.backend_mutated === 'boolean') && digest(d.error_digest))) throw new Error('部署记录响应不完整');
  if (!Array.isArray(v.audit_events) || v.audit_events.length > (v.expanded ? 200 : 50) || !v.audit_events.every(e => object(e) && exact(e, ['id', 'action', 'actor_id', 'resource_id', 'created_at', 'review_digest', 'error_digest']) && text(e.id) && text(e.action) && text(e.actor_id, 256) && text(e.resource_id) && date(e.created_at) && digest(e.review_digest) && digest(e.error_digest)) || v.audit_access === 'denied' && (v.audit_events.length || v.audit_truncated)) throw new Error('审计记录响应不完整');
  if (new Set(v.deployments.map(d => d.id)).size !== v.deployments.length || new Set(v.audit_events.map(e => e.id)).size !== v.audit_events.length) throw new Error('结果包含重复记录');
  return v as unknown as ChangeExecution;
}
export async function readChangeExecution(id: string, expanded = false) {
  return parseChangeExecution(await get<unknown>(`/change-requests/${encodeURIComponent(id)}/execution`, { query: { expanded } }), id);
}

export const deploymentStatus = (status: string) => ({ pending: '待执行', sent: '已创建下发任务', verifying: '验证中', effective: '后端标记已生效', failed: '部署失败', rolled_back: '已回滚' }[status] ?? '状态待核对');
export function executionEvidence(d: DeploymentHistory): { label: string; detail: string; tone: 'ok' | 'warn' | 'err' } {
  if (d.status === 'failed') return { label: '部署失败，需核对执行端', detail: d.backend_mutated ? '已有修改后端的证据，请核对当前配置与回滚结果。' : '失败不证明后端没有变化；请结合错误摘要和执行端检查。', tone: 'err' };
  if (d.status === 'rolled_back') return { label: '已记录回滚', detail: '此前的部署验证不代表当前状态，请核对回滚后的执行端。', tone: 'warn' };
  if (d.independent_result === 'mismatch') return { label: '独立读回与部署回执不一致', detail: '可能存在带外变更；旧验证不能作为当前生效依据，请联系运维核对。', tone: 'err' };
  if (d.independent_result === 'unreachable') return { label: '最近独立读回无法连接执行端', detail: '暂不能确认当前状态；恢复连接后再核对。', tone: 'warn' };
  if (d.independent_result === 'no_receipt') return { label: '缺少可核对的部署回执', detail: '当前证据不足，不能确认执行状态。', tone: 'warn' };
  if (d.independent_result === 'unknown') return { label: '独立读回结果待核对', detail: '不能依赖此前的成功记录推断当前状态。', tone: 'warn' };
  if (d.verification_level === 'stale' || d.verification_level === 'failed') return { label: d.verification_level === 'stale' ? '验证证据已过期' : '验证未通过', detail: '需要重新核对执行端。', tone: 'err' };
  if (d.status !== 'effective') return { label: '尚无生效验证', detail: '任务已创建或正在处理，不代表配置已经应用。', tone: 'warn' };
  if (d.verification_level === 'config_readback') return { label: '配置已读回，行为未验证', detail: '历史读回证明当时配置一致，尚未证明实际工具调用受到拦截。', tone: 'warn' };
  if (d.verification_level === 'behavior_enforced') return { label: '已有行为验证记录', detail: '仅代表该次验证及其覆盖范围，不是持续保护保证。', tone: 'ok' };
  return { label: '验证证据不足', detail: '仅有后端状态或版本核对，不能确认完整配置及行为。', tone: 'warn' };
}

export const auditAction = (action: string) => ({ 'change.request.create': '提出变更', 'change.approve': '批准变更', 'change.reject': '驳回变更', 'deployment.reserve': '保存部署请求', 'deployment.create': '创建部署任务', 'deployment.verify': '核对部署配置', 'deployment.fail': '部署失败', 'deployment.receipt_verify': '独立核对部署回执', 'deployment.rollback': '回滚部署', 'deployment.rollback_fail': '回滚失败' }[action] ?? '其他审计操作');
