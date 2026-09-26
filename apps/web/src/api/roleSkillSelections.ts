import { get } from './client';

export interface RoleSkillSelection {
  schema_version: 'enterprise-openclaw-skill-selection/v1';
  source: 'agent' | 'defaults' | 'none';
  status: 'declared_list' | 'unconfigured' | 'unsupported';
  names: string[];
}
export interface RoleSkillObservation {
  id: string;
  device: { id: string; revoked: boolean };
  task_id: string;
  batch_digest: string;
  selection: RoleSkillSelection;
  source_evidence: { evidence_id: string; content_hash: string; observed_at: string }[];
  observed_at: string;
  received_at: string;
}
export interface RoleSkillHistory {
  schema_version: 'enterprise-role-skill-observations/v1';
  asset_id: string;
  status: 'historical_declarations' | 'no_recorded_declaration';
  relationship_status: 'unresolved';
  effective_permissions: null;
  observations_truncated: boolean;
  observations: RoleSkillObservation[];
}

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max = 64): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const timestamp = (v: unknown): v is string => text(v)
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(v) && Number.isFinite(Date.parse(v));

function isSelection(v: unknown): v is RoleSkillSelection {
  if (!object(v) || v.schema_version !== 'enterprise-openclaw-skill-selection/v1'
    || (typeof v.source !== 'string' || !['agent', 'defaults', 'none'].includes(v.source))
    || (typeof v.status !== 'string' || !['declared_list', 'unconfigured', 'unsupported'].includes(v.status))
    || !Array.isArray(v.names) || v.names.length > 64
    || !v.names.every(n => typeof n === 'string' && /^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$/.test(n))) return false;
  if ((v.source === 'none') !== (v.status === 'unconfigured') || (v.status !== 'declared_list' && v.names.length)) return false;
  const names = v.names;
  return new Set(names).size === names.length && [...names].sort().every((n, i) => n === names[i]);
}

function isObservation(v: unknown): v is RoleSkillObservation {
  return object(v) && text(v.id) && text(v.task_id) && object(v.device) && text(v.device.id)
    && typeof v.device.revoked === 'boolean' && hash(v.batch_digest) && isSelection(v.selection)
    && timestamp(v.observed_at) && timestamp(v.received_at)
    && Array.isArray(v.source_evidence) && v.source_evidence.length >= 1 && v.source_evidence.length <= 64
    && v.source_evidence.every(e => object(e) && text(e.evidence_id, 128) && hash(e.content_hash) && timestamp(e.observed_at))
    && new Set(v.source_evidence.map(e => e.evidence_id)).size === v.source_evidence.length;
}

export function isRoleSkillHistory(v: unknown, assetId: string): v is RoleSkillHistory {
  if (!object(v) || v.schema_version !== 'enterprise-role-skill-observations/v1' || v.asset_id !== assetId
    || v.relationship_status !== 'unresolved' || v.effective_permissions !== null
    || typeof v.observations_truncated !== 'boolean' || !Array.isArray(v.observations)
    || v.observations.length > 100 || !v.observations.every(isObservation)) return false;
  const observations = v.observations;
  if (v.status !== (observations.length ? 'historical_declarations' : 'no_recorded_declaration')
    || (v.observations_truncated && observations.length !== 100)
    || new Set(observations.map(o => o.id)).size !== observations.length
    || new Set(observations.map(o => o.task_id)).size !== observations.length) return false;
  return observations.every((o, i) => i === 0 || Date.parse(o.received_at) <= Date.parse(observations[i - 1].received_at));
}

export async function getRoleSkillHistory(assetId: string): Promise<RoleSkillHistory> {
  const value = await get<unknown>(`/agents/${encodeURIComponent(assetId)}/skill-selections`);
  if (!isRoleSkillHistory(value, assetId)) throw new Error('角色技能声明响应无法核验');
  return value;
}
