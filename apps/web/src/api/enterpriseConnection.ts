import { get } from './client';

export const connectionStatuses = ['not_configured', 'configuration_rejected', 'probe_failed', 'identity_unverified', 'version_unknown', 'handshake_verified'] as const;
export interface EnterpriseConnection {
  schema_version: 'enterprise-openshell-connection/v1';
  environment_id: string;
  scope: 'control_plane_connection';
  status: typeof connectionStatuses[number];
  ready_for_deployment: false;
  version_compatibility: 'unverified';
  credential_scope: 'unverified';
  execution_evidence: 'none';
  endpoint_fingerprint: string | null;
  gateway_name_sha256: string | null;
  cli_version: string;
  gateway_version: string;
  configuration_capabilities: Record<string, boolean>;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const version = (v: unknown) => typeof v === 'string' && (v === 'unknown' || /^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/.test(v)) && v.length <= 128;
export function isEnterpriseConnection(v: unknown, environmentId: string): v is EnterpriseConnection {
  if (!object(v) || v.schema_version !== 'enterprise-openshell-connection/v1' || v.environment_id !== environmentId
    || v.scope !== 'control_plane_connection' || !connectionStatuses.some(s => s === v.status)
    || v.ready_for_deployment !== false || v.version_compatibility !== 'unverified'
    || v.credential_scope !== 'unverified' || v.execution_evidence !== 'none'
    || !version(v.cli_version) || !version(v.gateway_version) || !object(v.configuration_capabilities)) return false;
  const caps = v.configuration_capabilities;
  if (v.status === 'handshake_verified' || v.status === 'version_unknown') {
    return hash(v.endpoint_fingerprint) && hash(v.gateway_name_sha256)
      && (v.status === 'version_unknown') === (v.gateway_version === 'unknown')
      && Object.keys(caps).length === 2 && typeof caps['network.dynamic_update'] === 'boolean'
      && typeof caps['enforcement_mode.block'] === 'boolean';
  }
  return v.endpoint_fingerprint === null && v.gateway_name_sha256 === null
    && v.cli_version === 'unknown' && v.gateway_version === 'unknown' && Object.keys(caps).length === 0;
}
export async function inspectEnterpriseConnection(environmentId: string): Promise<EnterpriseConnection> {
  const result = await get<unknown>(`/environments/${encodeURIComponent(environmentId)}/openshell-connection`, { timeoutMs: 15000 });
  if (!isEnterpriseConnection(result, environmentId)) throw new Error('连接诊断响应无法核验');
  return result;
}
