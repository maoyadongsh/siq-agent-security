import { afterEach, describe, expect, it, vi } from 'vitest';
import { inspectEnterpriseConnection, isEnterpriseConnection, type EnterpriseConnection } from './enterpriseConnection';

const fixture: EnterpriseConnection = {
  schema_version: 'enterprise-openshell-connection/v1', environment_id: 'env', scope: 'control_plane_connection',
  status: 'handshake_verified', ready_for_deployment: false, version_compatibility: 'unverified',
  credential_scope: 'unverified', execution_evidence: 'none', endpoint_fingerprint: 'a'.repeat(64),
  gateway_name_sha256: 'b'.repeat(64), cli_version: '0.0.104', gateway_version: '0.0.104',
  configuration_capabilities: { 'network.dynamic_update': true, 'enforcement_mode.block': true },
};
afterEach(() => vi.unstubAllGlobals());
describe('enterprise connection diagnostic boundary', () => {
  it('accepts only scoped handshake or honest missing configuration', () => {
    expect(isEnterpriseConnection(fixture, 'env')).toBe(true);
    expect(isEnterpriseConnection({ ...fixture, status: 'version_unknown', gateway_version: 'unknown' }, 'env')).toBe(true);
    expect(isEnterpriseConnection({ ...fixture, status: 'not_configured', endpoint_fingerprint: null,
      gateway_name_sha256: null, cli_version: 'unknown', gateway_version: 'unknown', configuration_capabilities: {} }, 'env')).toBe(true);
  });
  it.each([
    { environment_id: 'other' }, { scope: 'environment_owned' }, { ready_for_deployment: true },
    { execution_evidence: 'enforced' }, { version_compatibility: 'verified' }, { credential_scope: 'least_privilege' },
    { schema_version: 'other' }, { status: 'protected' }, { status: 'probe_failed' },
    { gateway_version: 'unknown' }, { gateway_version: '<script>' }, { endpoint_fingerprint: 'bad' },
    { configuration_capabilities: {} }, { configuration_capabilities: { 'network.dynamic_update': true, 'enforcement_mode.block': true, unsafe: true } },
  ])('rejects misleading or malformed result %j', patch => {
    expect(isEnterpriseConnection({ ...fixture, ...patch }, 'env')).toBe(false);
  });
  it('uses encoded environment identity and read-only request', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture), { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    await expect(inspectEnterpriseConnection('other/id')).rejects.toThrow('无法核验');
    expect(String(fetch.mock.calls[0][0])).toContain('/environments/other%2Fid/openshell-connection');
    expect(fetch.mock.calls[0][1].method).toBe('GET');
  });
});
