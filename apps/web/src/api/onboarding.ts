import { get, post } from './client';
import type { Environment, EnvironmentType } from './types';

export interface OnboardingAccess { schema_version: 'environment-onboarding-access/v1'; can_create: boolean; can_enroll: boolean; can_scan: boolean; can_view_assets: boolean }
export interface OnboardingDevice { id: string; device_identity: string; version: string; registered_at: string; last_seen_at: string | null; status: 'waiting' | 'online' | 'stale' | 'revoked'; connectors: string[] }
export interface OnboardingScan { id: string; connector: string; status: 'pending' | 'uploaded' | 'delivered' | 'failed' | 'expired'; created_at: string; expires_at: string; device_identity: string | null; candidate_count: number | null; evidence_count: number | null }
export interface OnboardingStatus { schema_version: 'environment-onboarding/v1'; environment_id: string; evaluated_at: string; heartbeat_stale_seconds: number; device_count: number; devices: OnboardingDevice[]; devices_truncated: boolean; evidence_count: number; last_evidence_at: string | null; scans: OnboardingScan[]; scans_truncated: boolean }
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const time = (value: unknown) => text(value) && value.endsWith('Z') && Number.isFinite(Date.parse(value));
export function isOnboardingStatus(value: unknown, id: string): value is OnboardingStatus {
  if (!object(value) || value.schema_version !== 'environment-onboarding/v1' || value.environment_id !== id || !time(value.evaluated_at)
    || !count(value.heartbeat_stale_seconds) || value.heartbeat_stale_seconds < 1 || !count(value.device_count) || !count(value.evidence_count)
    || !(value.last_evidence_at === null || time(value.last_evidence_at)) || typeof value.devices_truncated !== 'boolean' || typeof value.scans_truncated !== 'boolean'
    || !Array.isArray(value.devices) || value.devices.length > 100 || value.device_count < value.devices.length
    || value.devices_truncated !== (value.device_count > value.devices.length) || !Array.isArray(value.scans) || value.scans.length > 20) return false;
  const devices = value.devices.every(d => object(d) && text(d.id) && text(d.device_identity) && typeof d.version === 'string' && time(d.registered_at)
    && (d.last_seen_at === null || time(d.last_seen_at)) && ['waiting', 'online', 'stale', 'revoked'].includes(String(d.status))
    && (d.status !== 'online' || (time(d.last_seen_at) && Date.parse(d.last_seen_at as string) <= Date.parse(value.evaluated_at as string)
      && Date.parse(d.last_seen_at as string) >= Date.parse(value.evaluated_at as string) - (value.heartbeat_stale_seconds as number) * 1000))
    && Array.isArray(d.connectors) && d.connectors.length <= 4 && d.connectors.every(c => ['hermes', 'openclaw', 'directory', 'docker'].includes(String(c))));
  return devices && new Set(value.devices.map(d => d.id)).size === value.devices.length
    && value.scans.every(s => object(s) && text(s.id) && text(s.connector) && time(s.created_at) && time(s.expires_at)
      && ['pending', 'uploaded', 'delivered', 'failed', 'expired'].includes(String(s.status)) && (s.device_identity === null || text(s.device_identity))
      && (s.candidate_count === null || count(s.candidate_count)) && (s.evidence_count === null || count(s.evidence_count)))
    && new Set(value.scans.map(s => s.id)).size === value.scans.length;
}
export const onboardingApi = {
  access: async () => {
    const value = await get<OnboardingAccess>('/environments/access');
    if (!value || value.schema_version !== 'environment-onboarding-access/v1' || ['can_create', 'can_enroll', 'can_scan', 'can_view_assets'].some(k => typeof value[k as keyof OnboardingAccess] !== 'boolean')) throw new Error('接入权限响应无效');
    return value;
  },
  create: (name: string, env_type: EnvironmentType) => post<Environment>('/environments', { name, env_type }),
  status: async (id: string) => {
    const value = await get<unknown>(`/environments/${encodeURIComponent(id)}/onboarding`);
    if (!isOnboardingStatus(value, id)) throw new Error('接入进度无法核验');
    return value;
  },
  enroll: async (id: string) => {
    const value = await post<{ code: string; expires_at: string }>(`/environments/${encodeURIComponent(id)}/edge-enrollment`, {});
    if (!value || !/^enr-[A-Za-z0-9_-]{20,100}$/.test(value.code) || !Number.isFinite(Date.parse(value.expires_at))) throw new Error('注册码响应无效，请刷新进度后再处理');
    return value;
  },
  scan: (id: string, connector: 'hermes' | 'openclaw') => post<{task_id: string}>('/scans', { environment_id: id, connector, scope: connector === 'hermes'
    ? { roots: ['~/.hermes/profiles/*'], include: ['config.yaml', 'SOUL.md'] } : { roots: ['~/.openclaw'] } }),
};

export function controlPlaneURL(raw: string): string | null {
  if (/[\u0000-\u0020\u007f]/.test(raw)) return null;
  try {
    const url = new URL(raw);
    if (url.username || url.password || url.search || url.hash || url.pathname !== '/' || !url.hostname
      || !(url.protocol === 'https:' || url.protocol === 'http:' && ['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname))) return null;
    return url.href.replace(/\/+$/, '');
  } catch { return null; }
}
export function edgeCommands(address: string, os: 'bash' | 'powershell'): { register: string; heartbeat: string; tasks: string } | null {
  const url = controlPlaneURL(address);
  if (!url) return null;
  if (os === 'powershell') return {
    register: `$siqEnrollment = Read-Host '注册码'\n$siqEnrollment | .\\edge-agent.exe register --control-plane '${url.replace(/'/g, "''")}' --enrollment-code-stdin\nRemove-Variable siqEnrollment`,
    heartbeat: '.\\edge-agent.exe heartbeat', tasks: '.\\edge-agent.exe tasks',
  };
  return { register: `read -r -s -p '注册码：' siq_enrollment\nprintf '\\n'\nprintf '%s\\n' "$siq_enrollment" | ./edge-agent register --control-plane '${url.replace(/'/g, "'\\''")}' --enrollment-code-stdin\nunset siq_enrollment`,
    heartbeat: './edge-agent heartbeat', tasks: './edge-agent tasks' };
}
