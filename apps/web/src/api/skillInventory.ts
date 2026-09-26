import { get } from './client';

export interface SkillInstallation {
  installation_id: string;
  locator_sha256: string;
  environment: { id: string; name: string };
  device: { id: string; identity: string; revoked: boolean };
  presence: 'observed_not_verified_current';
  relationship_status: 'unresolved';
  effective_permissions: null;
  latest_observation: null | {
    observation_id: string; manifest_sha256: string; parser_version: string;
    parse_status: 'parsed' | 'missing_frontmatter' | 'unsupported' | 'invalid_utf8';
    name: string | null; allowed_tools_present: boolean; declared_tools: string[];
    observed_at: string; batch_digest: string;
  };
}
export interface SkillInventoryPage {
  schema_version: 'enterprise-skill-inventory/v1'; items: SkillInstallation[]; next_cursor: string | null;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 4096;
const digest = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown): v is string => typeof v === 'string' && /^ski_[A-Za-z0-9_-]{1,60}$/.test(v);
function installation(v: unknown): v is SkillInstallation {
  if (!object(v) || !id(v.installation_id) || !digest(v.locator_sha256)
    || !object(v.environment) || !text(v.environment.id) || !text(v.environment.name)
    || !object(v.device) || !text(v.device.id) || !text(v.device.identity) || typeof v.device.revoked !== 'boolean'
    || v.presence !== 'observed_not_verified_current' || v.relationship_status !== 'unresolved'
    || v.effective_permissions !== null) return false;
  const o = v.latest_observation;
  if (o === null) return true;
  return isSkillObservation(o);
}
export type SkillObservation = NonNullable<SkillInstallation['latest_observation']>;
export function isSkillObservation(o: unknown): o is SkillObservation {
  if (!object(o) || !text(o.observation_id) || !digest(o.manifest_sha256) || !digest(o.batch_digest)
    || o.parser_version !== 'enterprise-skill-manifest/v1' || typeof o.allowed_tools_present !== 'boolean'
    || !Array.isArray(o.declared_tools) || o.declared_tools.length > 64 || !o.declared_tools.every(text)
    || new Set(o.declared_tools).size !== o.declared_tools.length
    || !text(o.observed_at) || !Number.isFinite(Date.parse(o.observed_at))) return false;
  if (o.parse_status === 'parsed') return text(o.name) && (o.allowed_tools_present || o.declared_tools.length === 0);
  return ['missing_frontmatter', 'unsupported', 'invalid_utf8'].includes(String(o.parse_status))
    && o.name === null && !o.allowed_tools_present && o.declared_tools.length === 0;
}
export function isSkillInventoryPage(v: unknown): v is SkillInventoryPage {
  if (!object(v) || v.schema_version !== 'enterprise-skill-inventory/v1' || !Array.isArray(v.items)
    || v.items.length > 200 || !v.items.every(installation)) return false;
  const ids = v.items.map(row => row.installation_id);
  return ids.every((value, index) => index === 0 || value > ids[index - 1])
    && (v.next_cursor === null || (id(v.next_cursor) && ids.length > 0 && v.next_cursor === ids[ids.length - 1]));
}
export async function getSkillInventory(environmentId: string, deviceId: string, cursor?: string): Promise<SkillInventoryPage> {
  const value = await get<unknown>('/skill-installations', { query: {
    environment_id: environmentId || undefined, device_id: deviceId || undefined, cursor, limit: 50,
  } });
  if (!isSkillInventoryPage(value) || value.items.some(row =>
    (environmentId && row.environment.id !== environmentId) || (deviceId && row.device.id !== deviceId)
    || (cursor && row.installation_id <= cursor))) throw new Error('技能清单响应无法核验');
  return value;
}
