import { get, post, requestWithHeaders } from './client';
import { parseListMeta } from './listMeta';

export interface BehaviorScope {
  target: string; policy_revision: string; policy_digest: string; transport: 'direct_tcp' | 'http_connect';
  endpoint: string; allow_path: string; deny_path: string; attempts: number;
}
export interface BehaviorOperation {
  schema_version: 'deployment-behavior-operation/v1'; deployment_id: string; verification_id: string;
  profile_id: string | null; state: 'prepared' | 'running' | 'accepted' | 'rejected' | 'unknown' | 'expired';
  reason_code: string | null; issued_at: string; expires_at: string; observed_at: string | null;
  time_window: 'within' | 'expired'; current_enforcement_verified: false; observation_count: number; scope: BehaviorScope;
}
export interface BehaviorProfile {
  profile_id: string; profile_sha256: string; issued_at: string; expires_at: string; timeout_ms: number; scope: BehaviorScope;
}
export interface BehaviorAssessment {
  schema_version: 'deployment-behavior-assessment/v1'; deployment_id: string; verification_id: string;
  evaluated_at: string; valid_until: string | null; state: 'verified' | 'not_accepted' | 'expired' | 'changed' | 'unavailable';
  level: 'enforcement_verified' | 'unverified'; current_enforcement_verified: boolean; reason_code: string; scope: BehaviorScope;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const token = (v: unknown): v is string => text(v, 128) && /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(v);
const digest = (v: unknown): v is string => text(v, 64) && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown): v is string => text(v, 36) && /^opv-[a-f0-9]{32}$/.test(v);
const integer = (v: unknown, min: number, max: number): v is number => typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max;
const date = (v: unknown): v is string => text(v, 40) && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/.test(v)
  && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const oneOf = (v: unknown, values: string[]) => typeof v === 'string' && values.includes(v);
const path = (v: unknown) => text(v, 512) && v.startsWith('/') && !v.includes('//') && !v.split('/').some(p => p === '.' || p === '..');
const endpoint = (v: unknown) => {
  if (!text(v, 21) || !/^\d{1,3}(\.\d{1,3}){3}:\d{1,5}$/.test(v)) return false;
  const [host, port] = v.split(':');
  return host.split('.').every(n => String(Number(n)) === n && Number(n) <= 255)
    && String(Number(port)) === port && Number(port) >= 1 && Number(port) <= 65535;
};
const scope = (v: unknown): v is BehaviorScope => object(v)
  && exact(v, ['target', 'policy_revision', 'policy_digest', 'transport', 'endpoint', 'allow_path', 'deny_path', 'attempts'])
  && token(v.target) && token(v.policy_revision) && digest(v.policy_digest) && oneOf(v.transport, ['direct_tcp', 'http_connect'])
  && endpoint(v.endpoint)
  && path(v.allow_path) && path(v.deny_path) && v.allow_path !== v.deny_path && integer(v.attempts, 3, 10);
const sameScope = (a: BehaviorScope, b: BehaviorScope) => (Object.keys(a) as (keyof BehaviorScope)[]).every(k => a[k] === b[k]);

export function parseBehaviorOperation(v: unknown, deployment: string, expectedId?: string): BehaviorOperation {
  if (!object(v) || !exact(v, ['schema_version', 'deployment_id', 'verification_id', 'profile_id', 'state', 'reason_code', 'issued_at', 'expires_at', 'observed_at', 'time_window', 'current_enforcement_verified', 'observation_count', 'scope'])
    || v.schema_version !== 'deployment-behavior-operation/v1' || v.deployment_id !== deployment || !id(v.verification_id)
    || expectedId !== undefined && v.verification_id !== expectedId || !(v.profile_id === null || token(v.profile_id))
    || !oneOf(v.state, ['prepared', 'running', 'accepted', 'rejected', 'unknown', 'expired'])
    || !(v.reason_code === null || text(v.reason_code, 80)) || !date(v.issued_at) || !date(v.expires_at)
    || Date.parse(v.expires_at) <= Date.parse(v.issued_at) || !(v.observed_at === null || date(v.observed_at))
    || !oneOf(v.time_window, ['within', 'expired']) || v.current_enforcement_verified !== false
    || !integer(v.observation_count, 0, 40) || !scope(v.scope)
    || v.state === 'accepted' && (v.observed_at === null || v.observation_count !== v.scope.attempts * 4)) {
    throw new Error('行为测评记录不完整或对象不匹配');
  }
  return v as unknown as BehaviorOperation;
}

export function parseBehaviorProfiles(v: unknown, deployment: string): BehaviorProfile[] {
  if (!object(v) || !exact(v, ['schema_version', 'deployment_id', 'profiles'])
    || v.schema_version !== 'deployment-behavior-profiles/v1' || v.deployment_id !== deployment
    || !Array.isArray(v.profiles) || v.profiles.length > 32 || !v.profiles.every(p => object(p)
      && exact(p, ['profile_id', 'profile_sha256', 'issued_at', 'expires_at', 'timeout_ms', 'scope'])
      && token(p.profile_id) && digest(p.profile_sha256) && date(p.issued_at) && date(p.expires_at)
      && Date.parse(p.expires_at) > Date.parse(p.issued_at) && integer(p.timeout_ms, 100, 10000) && scope(p.scope))
    || new Set(v.profiles.map(p => p.profile_id)).size !== v.profiles.length) throw new Error('测评模板不完整或对象不匹配');
  return v.profiles as BehaviorProfile[];
}

export function parseBehaviorAssessment(v: unknown, operation: BehaviorOperation): BehaviorAssessment {
  if (!object(v) || !exact(v, ['schema_version', 'deployment_id', 'verification_id', 'evaluated_at', 'valid_until', 'state', 'level', 'current_enforcement_verified', 'reason_code', 'scope'])
    || v.schema_version !== 'deployment-behavior-assessment/v1' || v.deployment_id !== operation.deployment_id
    || v.verification_id !== operation.verification_id || !date(v.evaluated_at) || !text(v.reason_code, 80)
    || !oneOf(v.state, ['verified', 'not_accepted', 'expired', 'changed', 'unavailable']) || !scope(v.scope) || !sameScope(v.scope, operation.scope)) throw new Error('当前核验响应不完整或范围不匹配');
  if (v.state === 'verified') {
    if (operation.state !== 'accepted' || v.level !== 'enforcement_verified' || v.current_enforcement_verified !== true
      || !date(v.valid_until) || Date.parse(v.valid_until) > Date.parse(operation.expires_at)
      || Date.parse(v.valid_until) <= Date.parse(v.evaluated_at) || operation.observed_at === null
      || Date.parse(v.evaluated_at) < Date.parse(operation.observed_at)) throw new Error('核验时间或等级不一致');
  } else if (v.level !== 'unverified' || v.current_enforcement_verified !== false || v.valid_until !== null) {
    throw new Error('未通过的核验不能显示为已验证');
  }
  return v as unknown as BehaviorAssessment;
}

export const behaviorState = (s: BehaviorOperation['state']) => ({ prepared: '已准备，尚未探测', running: '探测进行中', accepted: '该次观测已采信', rejected: '该次观测未通过', unknown: '结果待核对', expired: '已过期，未执行' }[s]);
export function assessmentLabel(value: BehaviorAssessment | null, now: number): string {
  if (!value) return '尚未核验当前目标';
  if (value.state === 'verified') return value.valid_until && now < Date.parse(value.valid_until) ? '核验时，该范围行为已验证' : '核验证据已过期';
  return { not_accepted: '尚无可采信的行为证据', expired: '核验证据已过期', changed: '目标或策略与观测不一致', unavailable: '暂时无法核验当前目标' }[value.state];
}
const url = (deployment: string) => `/deployments/${encodeURIComponent(deployment)}`;
export async function readBehaviorHistory(deployment: string) {
  const { data, headers } = await requestWithHeaders<unknown>(url(deployment) + '/behavior-verifications');
  if (!Array.isArray(data) || data.length > 20) throw new Error('行为历史列表不完整');
  const rows = data.map(v => parseBehaviorOperation(v, deployment));
  if (new Set(rows.map(r => r.verification_id)).size !== rows.length) throw new Error('行为历史包含重复记录');
  return { rows, meta: parseListMeta(headers) };
}
export async function readBehaviorProfiles(deployment: string) {
  return parseBehaviorProfiles(await get<unknown>(url(deployment) + '/behavior-profiles'), deployment);
}
export async function readBehavior(deployment: string, verification: string) {
  return parseBehaviorOperation(await get<unknown>(url(deployment) + '/behavior-verifications/' + encodeURIComponent(verification)), deployment, verification);
}
export async function collectBehavior(deployment: string, profile: BehaviorProfile, verification: string) {
  return parseBehaviorOperation(await post<unknown>(url(deployment) + '/behavior-verifications', {
    schema_version: 'deployment-behavior-start/v2', profile_id: profile.profile_id,
    profile_sha256: profile.profile_sha256, verification_id: verification,
  }, { timeoutMs: 320000 }), deployment, verification);
}
export async function assessBehavior(operation: BehaviorOperation) {
  return parseBehaviorAssessment(await post<unknown>(url(operation.deployment_id) + '/behavior-assessment', {
    schema_version: 'deployment-behavior-assess/v1', verification_id: operation.verification_id,
  }, { timeoutMs: 60000 }), operation);
}
