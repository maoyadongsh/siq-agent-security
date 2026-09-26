import { get } from './client';
import { isSkillObservation, type SkillObservation } from './skillInventory';

export interface SkillHistoryPage {
  schema_version: 'enterprise-skill-history/v1';
  installation_id: string;
  items: SkillObservation[];
  next_cursor: string | null;
}

function older(a: SkillObservation, b: SkillObservation): boolean {
  const timeA = Date.parse(a.observed_at), timeB = Date.parse(b.observed_at);
  return timeA < timeB || (timeA === timeB && a.observation_id < b.observation_id);
}

export function isSkillHistoryPage(value: unknown, installationId: string, after?: SkillObservation): value is SkillHistoryPage {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  if (v.schema_version !== 'enterprise-skill-history/v1' || v.installation_id !== installationId
    || !Array.isArray(v.items) || v.items.length > 200 || !v.items.every(isSkillObservation)) return false;
  const rows: SkillObservation[] = v.items;
  if (new Set(rows.map(row => row.observation_id)).size !== rows.length) return false;
  if (!rows.every((row, index) => /^smo_[A-Za-z0-9_-]{1,60}$/.test(row.observation_id)
    && (index === 0 ? !after || older(row, after) : older(row, rows[index - 1])))) return false;
  return v.next_cursor === null || (rows.length > 0 && v.next_cursor === rows[rows.length - 1].observation_id);
}

export async function getSkillHistory(installationId: string, after?: SkillObservation): Promise<SkillHistoryPage> {
  const value = await get<unknown>(`/skill-installations/${encodeURIComponent(installationId)}/observations`, {
    query: { limit: 50, cursor: after?.observation_id },
  });
  if (!isSkillHistoryPage(value, installationId, after)) throw new Error('技能历史响应无法核验');
  return value;
}
