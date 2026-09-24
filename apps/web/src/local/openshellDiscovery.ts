export interface DiscoveredSandbox { sandbox_id: string; name: string; phase: string; policy_version: string }
export interface OpenShellTargets {
  schema_version: 'local-openshell-targets/v1'; observed_at: string;
  state: 'unconfigured' | 'unreachable' | 'catalog_unavailable' | 'available';
  cli_found: boolean; source: string; cli_version: string; gateway: string;
  endpoint_fingerprint: string; can_inspect: boolean; items: DiscoveredSandbox[]; started_gateway: false;
}
export interface OpenShellInspection {
  schema_version: 'local-openshell-target-inspection/v1'; sandbox_id: string; name: string;
  endpoint_fingerprint: string; observed_at: string; expires_at: string;
  state: 'policy_readable'; revision: string; policy_digest: string; enforcement_verified: false;
}
const hash = (v: unknown) => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
const uuid = (v: unknown) => typeof v === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const date = (v: unknown) => typeof v === 'string' && Number.isFinite(Date.parse(v));
export function isOpenShellTargets(value: unknown): value is OpenShellTargets {
  if (!value || typeof value !== 'object') return false;
  const v = value as OpenShellTargets;
  if (v.schema_version !== 'local-openshell-targets/v1' || !date(v.observed_at) || !['unconfigured','unreachable','catalog_unavailable','available'].includes(v.state)
    || typeof v.cli_found !== 'boolean' || typeof v.can_inspect !== 'boolean' || v.started_gateway !== false
    || !['none','invalid','path','env_sh','env_pair'].includes(v.source) || typeof v.gateway !== 'string' || typeof v.cli_version !== 'string'
    || !(v.endpoint_fingerprint === '' || hash(v.endpoint_fingerprint)) || !Array.isArray(v.items) || v.items.length >= 1000
    || (v.state !== 'available' && (v.items.length !== 0 || v.can_inspect)) || (v.can_inspect && !hash(v.endpoint_fingerprint))) return false;
  const ids = new Set<string>(); const names = new Set<string>();
  return v.items.every((item) => {
    if (!item || !uuid(item.sandbox_id) || typeof item.name !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$/.test(item.name)
      || !['Ready','Pending','Creating','Running','Stopping','Stopped','Error','Terminated','Unknown'].includes(item.phase)
      || !/^(0|[1-9][0-9]*)$/.test(item.policy_version) || ids.has(item.sandbox_id) || names.has(item.name)) return false;
    ids.add(item.sandbox_id); names.add(item.name); return true;
  });
}
export function isOpenShellInspection(value: unknown, item: DiscoveredSandbox, catalog: OpenShellTargets): value is OpenShellInspection {
  if (!value || typeof value !== 'object') return false;
  const v = value as OpenShellInspection;
  return v.schema_version === 'local-openshell-target-inspection/v1' && v.sandbox_id === item.sandbox_id && v.name === item.name
    && hash(v.endpoint_fingerprint) && v.endpoint_fingerprint === catalog.endpoint_fingerprint
    && date(v.observed_at) && date(v.expires_at) && Date.parse(v.expires_at) > Date.parse(v.observed_at)
    && v.state === 'policy_readable' && typeof v.revision === 'string' && v.revision !== '' && hash(v.policy_digest) && v.enforcement_verified === false;
}
