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
