import { describe, expect, it, vi, afterEach } from 'vitest';
import { getDiscoveryOrigin, isDiscoveryOrigin, type DiscoveryOrigin } from './discoveryOrigin';

export const originFixture: DiscoveryOrigin = {
  schema_version: 'enterprise-discovery-origin/v1', asset_id: 'asset-1', status: 'device_bound',
  environment: { id: 'env-1', name: '测试环境' }, device: { id: 'edge-1', identity: 'device-1', revoked: false },
  reported_framework: 'hermes', assigned_role: null, observations_truncated: false,
  observations: [{ observation_id: 'obs-1', evidence_id: 'ev-1', content_hash: 'a'.repeat(64), observed_at: '2026-09-25T00:00:00Z' }],
};
afterEach(() => vi.unstubAllGlobals());
describe('asset discovery origin boundary', () => {
  it('accepts current source and unresolved historical source', () => {
    expect(isDiscoveryOrigin(originFixture, 'asset-1')).toBe(true);
    expect(isDiscoveryOrigin({ ...originFixture, status: 'legacy_unresolved', environment: null, device: null, observations: [] }, 'asset-1')).toBe(true);
  });
  it.each([
    { asset_id: 'other' }, { status: 'protected' }, { device: null }, { environment: null },
    { schema_version: 'unknown' }, { status: 'legacy_unresolved' },
    { observations: [originFixture.observations[0], originFixture.observations[0]] },
    { observations: [{ ...originFixture.observations[0], content_hash: 'invalid' }] },
    { observations: [{ ...originFixture.observations[0], observed_at: 'invalid' }] },
    { observations: Array(201).fill(originFixture.observations[0]) },
  ])('rejects mismatched or malformed source %j', patch => {
    expect(isDiscoveryOrigin({ ...originFixture, ...patch }, 'asset-1')).toBe(false);
  });
  it('encodes identity and rejects a response for another asset', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(originFixture), { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    await expect(getDiscoveryOrigin('other/id')).rejects.toThrow('无法核验');
    expect(String(fetch.mock.calls[0][0])).toContain('/agents/other%2Fid/discovery-origin');
  });
});
