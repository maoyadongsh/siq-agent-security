import { afterEach, describe, expect, it, vi } from 'vitest';
import { installApi, isInstallOptions, isMatchingInstallPlan, type InstallOptions } from './installPlan';

const options: InstallOptions = {
  schema_version: 'enterprise-install-options/v1', environment_id: 'env-1', control_plane_origin: 'https://security.example.com',
  allowed_service_modes: ['user'], purpose: 'discovery_only', release_signature_verified: false,
  releases: [{ target_arch: 'arm64', release_version: '1.0.0', release_manifest_sha256: 'a'.repeat(64), connectors: [{
    id: 'hermes', version: '1.0.0', artifact_sha256: 'b'.repeat(64), protocol_version: 'connector-protocol.v1',
    scope: { roots: ['~/.hermes/profiles/*'], include: ['SOUL.md'] },
  }] }],
};
const plan = () => ({ ...options.releases[0], schema_version: 'enterprise-install-plan/v1', plan_id: 'eip-' + 'c'.repeat(32),
  tenant_id: 'tenant-1', environment_id: 'env-1', control_plane_origin: options.control_plane_origin,
  issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 600_000).toISOString(),
  target_os: 'linux', service_mode: 'user', purpose: 'discovery_only',
});
afterEach(() => vi.unstubAllGlobals());
describe('enterprise install plan boundary', () => {
  it('accepts read-only configured options', () => expect(isInstallOptions(options, 'env-1')).toBe(true));
  it.each([
    { environment_id: 'other' }, { purpose: 'enforce' }, { release_signature_verified: true },
    { control_plane_origin: 'http://192.168.2.121' }, { allowed_service_modes: ['system'] },
    { releases: [] }, { releases: [options.releases[0], options.releases[0]] },
  ])('rejects untrusted options %j', change => expect(isInstallOptions({ ...options, ...change }, 'env-1')).toBe(false));
  it('accepts a current plan matching displayed consent', () => expect(isMatchingInstallPlan(plan(), options, options.releases[0], ['hermes'])).toBe(true));
  it.each([
    { environment_id: 'other' }, { purpose: 'enforce' }, { target_arch: 'amd64' }, { service_mode: 'system' },
    { release_manifest_sha256: 'd'.repeat(64) }, { control_plane_origin: 'https://other.example.com' },
    { expires_at: '2020-01-01T00:00:00Z' }, { expires_at: '2099-01-01T00:00:00Z' }, { connectors: [] },
  ])('rejects changed/expired plan %j', change => expect(isMatchingInstallPlan({ ...plan(), ...change }, options, options.releases[0], ['hermes'])).toBe(false));
  it('rejects widened scope', () => {
    const value = plan();
    value.connectors = [{ ...value.connectors[0], scope: { roots: ['/'], include: ['SOUL.md'] } }];
    expect(isMatchingInstallPlan(value, options, options.releases[0], ['hermes'])).toBe(false);
  });
  it('reads options without issuing a plan or registering a device', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(options), { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    await installApi.options('env-1');
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toMatch(/\/environments\/env-1\/install-options$/);
    expect(fetch.mock.calls[0][1].method).toBe('GET');
  });
  it('posts only the explicit selection, not tenant, origin, or scope overrides', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(plan()), { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    await installApi.create(options, options.releases[0], ['hermes']);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ schema_version: 'enterprise-install-request/v1', target_arch: 'arm64', service_mode: 'user', connectors: ['hermes'] });
  });
  it('rejects duplicate selection before any network side effect', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    await expect(installApi.create(options, options.releases[0], ['hermes', 'hermes'])).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });
});
