import type { Receipt } from './types';

export interface SkillAttributionLabel {
  text: string;
  trusted: boolean;
  detail?: string;
}

/**
 * skillAttributionLabel renders the backend-attributed skill identity of a
 * receipt (N05/R01). Only `verified` with a recognized evidence level is shown
 * as trusted; anything else — including a contract-violating verified without
 * evidence level — renders as unverified. The console never upgrades partial
 * or missing evidence.
 */
export function skillAttributionLabel(a: Receipt['skill_attribution']): SkillAttributionLabel {
  if (!a) return { text: '—', trusted: false };
  if (a.status === 'verified' && a.evidence_level === 'controlled_task' && a.context_id) {
    return { text: `任务级可信 · ${a.skill_id ?? ''}`, trusted: true, detail: `SEC ${a.context_id}` };
  }
  if (a.status === 'verified' && a.evidence_level === 'controlled_session' && a.context_id) {
    return { text: `会话级可信（不含逐调用因果） · ${a.skill_id ?? ''}`, trusted: true, detail: `SEC ${a.context_id}` };
  }
  if (a.status === 'mismatch') return { text: '不匹配', trusted: false };
  return { text: '未验证', trusted: false };
}

const digest = /^[0-9a-f]{64}$/;
const signature = /^[0-9a-f]{128}$/;
const contextID = /^sec-[0-9a-f]{32}$/;
const callID = /^ncall-[0-9a-f]{32}$/;
const sessionID = /^nsess-[0-9a-f]{32}$/;
const matches = (pattern: RegExp, value: unknown): value is string => typeof value === 'string' && pattern.test(value);
const authorityValid = (value: unknown): boolean => {
  if (!value || typeof value !== 'object') return false;
  const ref = value as { grant_id?: unknown; grant_digest?: unknown };
  return typeof ref.grant_id === 'string' && ref.grant_id.trim().length > 0 && matches(digest, ref.grant_digest);
};

/** Display consistency only: signatures are verified by the daemon, never by this label. */
export function receiptSkillAttributionLabel(r: Receipt, chainVerified: unknown): SkillAttributionLabel {
  const a = r.skill_attribution;
  const p = r.native_invocation;
  if (!a && !p && !r.schema_version) return { text: '—', trusted: false };
  if (chainVerified !== true) return { text: '未验证', trusted: false, detail: '当前回执链未通过服务端验签。' };
  if (a?.status === 'mismatch') return { text: '不匹配', trusted: false };
  const unknown = { text: '未验证', trusted: false, detail: '权限上下文证明缺失、版本未知或关联不一致。' };
  if (r.schema_version !== 'runtime-receipt/v3') {
    if (p || a?.evidence_level === 'controlled_invocation' || (r.schema_version && r.schema_version !== 'runtime-receipt/v2')) return unknown;
    return skillAttributionLabel(a);
  }
  if (!p || !matches(callID, p.call_id) || !matches(signature, p.call_signature) ||
      !matches(sessionID, p.session_registration_id) || !matches(signature, p.session_signature) ||
      !matches(digest, p.request_binding) || !authorityValid(p.agent_authority) ||
      !Array.isArray(p.contexts) || p.contexts.length > 8 || typeof p.no_skill !== 'boolean' ||
      p.no_skill !== (p.contexts.length === 0)) return unknown;
  const ids = new Set<string>();
  for (const context of p.contexts) {
    if (!context || !matches(contextID, context.context_id) || !matches(signature, context.context_signature) ||
        !authorityValid(context.authority) || ids.has(context.context_id)) return unknown;
    ids.add(context.context_id);
  }
  const detail = `调用 ${p.call_id}；Agent 基线 ${p.agent_authority.grant_id}；${p.contexts.length} 层 Skill 权限约束。历史运行上下文证据，不证明当前授权仍有效、业务效果或模型指令因果。`;
  if (p.no_skill) return a !== undefined ? unknown : { text: '无 Skill · Agent 基线', trusted: true, detail };
  if (a?.status !== 'verified' || a.evidence_level !== 'controlled_invocation' || typeof a.skill_id !== 'string' || !a.skill_id.trim() ||
      !matches(digest, a.content_hash) || a.context_id !== p.contexts[0].context_id || a.call_binding !== p.request_binding) return unknown;
  return { text: `调用级可信 · ${a.skill_id}`, trusted: true, detail };
}
