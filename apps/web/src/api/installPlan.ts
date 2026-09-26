import { get, post } from './client';
import { controlPlaneURL } from './onboarding';

export interface InstallConnector {
  id: string; version: string; artifact_sha256: string; protocol_version: 'connector-protocol.v1';
  scope: { roots: string[]; include: string[] };
}
export interface InstallRelease {
  target_arch: 'arm64' | 'amd64'; release_version: string; release_manifest_sha256: string;
  connectors: InstallConnector[];
}
export interface InstallOptions {
  schema_version: 'enterprise-install-options/v1'; environment_id: string; control_plane_origin: string;
  allowed_service_modes: ['user']; releases: InstallRelease[]; purpose: 'discovery_only'; release_signature_verified: false;
}
export interface InstallPlan extends InstallRelease {
  schema_version: 'enterprise-install-plan/v1'; plan_id: string; tenant_id: string; environment_id: string;
  control_plane_origin: string; issued_at: string; expires_at: string; target_os: 'linux'; service_mode: 'user'; purpose: 'discovery_only';
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 4096;
const digest = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.length > 0 && v.length <= 128 && v.every(text);
const ids = new Set(['hermes', 'openclaw', 'directory', 'docker', 'process', 'systemd', 'kubernetes', 'mcp', 'piagent', 'workbuddy', 'dify', 'siq']);
function release(v: unknown): v is InstallRelease {
  return object(v) && ['arm64', 'amd64'].includes(String(v.target_arch)) && text(v.release_version) && digest(v.release_manifest_sha256)
    && Array.isArray(v.connectors) && v.connectors.length > 0 && v.connectors.length <= 12
    && v.connectors.every(c => object(c) && ids.has(String(c.id)) && text(c.version) && digest(c.artifact_sha256)
      && c.protocol_version === 'connector-protocol.v1' && object(c.scope) && strings(c.scope.roots) && strings(c.scope.include)
      && Object.keys(c.scope).every(k => ['roots', 'include'].includes(k)))
    && new Set(v.connectors.map(c => c.id)).size === v.connectors.length;
}
export function isInstallOptions(v: unknown, environment: string): v is InstallOptions {
  return object(v) && v.schema_version === 'enterprise-install-options/v1' && v.environment_id === environment
    && text(v.control_plane_origin) && controlPlaneURL(v.control_plane_origin) !== null
    && Array.isArray(v.allowed_service_modes) && v.allowed_service_modes.length === 1 && v.allowed_service_modes[0] === 'user'
    && v.purpose === 'discovery_only' && v.release_signature_verified === false && Array.isArray(v.releases)
    && v.releases.length > 0 && v.releases.length <= 2 && v.releases.every(release)
    && new Set(v.releases.map(r => r.target_arch)).size === v.releases.length;
}
export function isMatchingInstallPlan(v: unknown, options: InstallOptions, selected: InstallRelease, connectors: string[], now = Date.now()): v is InstallPlan {
  if (!release(v) || !object(v)) return false;
  const issued = typeof v.issued_at === 'string' ? Date.parse(v.issued_at) : NaN;
  const expires = typeof v.expires_at === 'string' ? Date.parse(v.expires_at) : NaN;
  return v.schema_version === 'enterprise-install-plan/v1' && typeof v.plan_id === 'string' && /^eip-[a-f0-9]{32}$/.test(v.plan_id)
    && text(v.tenant_id) && v.environment_id === options.environment_id && v.control_plane_origin === options.control_plane_origin
    && v.target_os === 'linux' && v.target_arch === selected.target_arch && v.service_mode === 'user' && v.purpose === 'discovery_only'
    && v.release_version === selected.release_version && v.release_manifest_sha256 === selected.release_manifest_sha256
    && issued <= now + 60_000 && expires > now && expires > issued && expires - issued <= 900_000
    && v.connectors.length === connectors.length && v.connectors.every(c => {
      const expected = selected.connectors.find(item => item.id === c.id);
      return connectors.includes(c.id) && expected !== undefined && c.version === expected.version && c.artifact_sha256 === expected.artifact_sha256
        && JSON.stringify(c.scope.roots) === JSON.stringify(expected.scope.roots) && JSON.stringify(c.scope.include) === JSON.stringify(expected.scope.include);
    });
}
export const installApi = {
  options: async (environment: string) => {
    const value = await get<unknown>(`/environments/${encodeURIComponent(environment)}/install-options`);
    if (!isInstallOptions(value, environment)) throw new Error('安装选项无法核验');
    return value;
  },
  create: async (options: InstallOptions, selected: InstallRelease, connectors: string[]) => {
    if (!connectors.length || new Set(connectors).size !== connectors.length || connectors.some(id => !selected.connectors.some(c => c.id === id))) throw new Error('请选择有效采集器');
    const value = await post<unknown>(`/environments/${encodeURIComponent(options.environment_id)}/install-plans`, {
      schema_version: 'enterprise-install-request/v1', target_arch: selected.target_arch, service_mode: 'user', connectors,
    });
    if (!isMatchingInstallPlan(value, options, selected, connectors)) throw new Error('安装计划与确认范围不一致');
    return value;
  },
};
