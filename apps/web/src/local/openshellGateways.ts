export interface RegisteredGateway {
  gateway_id: string; name: string; endpoint_display: string; native_active: boolean; configuration_fingerprint: string;
}
export interface GatewayCatalog {
  schema_version: 'local-openshell-gateways/v1'; observed_at: string;
  state: 'unconfigured' | 'unsupported' | 'unavailable' | 'available'; items: RegisteredGateway[];
  started_gateway: false; changed_native_selection: false;
}
export function isGatewayCatalog(value: unknown): value is GatewayCatalog {
  if (!value || typeof value !== 'object') return false;
  const v = value as GatewayCatalog;
  if (v.schema_version !== 'local-openshell-gateways/v1' || typeof v.observed_at !== 'string' || !Number.isFinite(Date.parse(v.observed_at))
    || !['unconfigured', 'unsupported', 'unavailable', 'available'].includes(v.state)
    || v.started_gateway !== false || v.changed_native_selection !== false || !Array.isArray(v.items) || v.items.length > 128
    || (v.state !== 'available' && v.items.length !== 0)) return false;
  const ids = new Set<string>(); const names = new Set<string>(); let active = 0;
  return v.items.every((row) => {
    if (!row || typeof row.gateway_id !== 'string' || !/^og-[0-9a-f]{32}$/.test(row.gateway_id) || ids.has(row.gateway_id)
      || typeof row.name !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$/.test(row.name) || names.has(row.name)
      || typeof row.configuration_fingerprint !== 'string' || !/^[0-9a-f]{64}$/.test(row.configuration_fingerprint)
      || typeof row.endpoint_display !== 'string' || row.endpoint_display.length > 2048 || typeof row.native_active !== 'boolean') return false;
    try { const u = new URL(row.endpoint_display); if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password || u.search || u.hash || u.pathname !== '/') return false; } catch { return false; }
    ids.add(row.gateway_id); names.add(row.name); if (row.native_active) active += 1;
    return active <= 1;
  });
}
