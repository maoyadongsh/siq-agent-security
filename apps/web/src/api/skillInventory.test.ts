import { afterEach, expect, it, vi } from 'vitest';
import { getSkillInventory, isSkillInventoryPage, type SkillInstallation } from './skillInventory';

export const skillFixture: SkillInstallation = {
  installation_id: 'ski_a', locator_sha256: 'a'.repeat(64),
  environment: { id: 'env_a', name: '测试环境' }, device: { id: 'edge_a', identity: '测试设备', revoked: false },
  presence: 'observed_not_verified_current', relationship_status: 'unresolved', effective_permissions: null,
  latest_observation: { observation_id: 'smo_a', manifest_sha256: 'b'.repeat(64), parser_version: 'enterprise-skill-manifest/v1',
    parse_status: 'parsed', name: 'skill-name', allowed_tools_present: true, declared_tools: ['read_file'],
    observed_at: '2026-09-25T01:00:00Z', batch_digest: 'c'.repeat(64) },
};
const page = { schema_version: 'enterprise-skill-inventory/v1', items: [skillFixture], next_cursor: null };
afterEach(() => vi.unstubAllGlobals());
it('accepts observed and missing observations without inventing grants', () => {
  expect(isSkillInventoryPage(page)).toBe(true);
  expect(isSkillInventoryPage({ ...page, items: [{ ...skillFixture, latest_observation: null }] })).toBe(true);
});
it.each([
  { schema_version: 'unknown' }, { items: Array(201).fill(skillFixture) }, { next_cursor: 'ski_other' },
  { items: [skillFixture, skillFixture] }, { items: [{ ...skillFixture, effective_permissions: [] }] },
  { items: [{ ...skillFixture, presence: 'installed' }] },
  { items: [{ ...skillFixture, latest_observation: { ...skillFixture.latest_observation, parse_status: 'unsupported' } }] },
  { items: [{ ...skillFixture, latest_observation: { ...skillFixture.latest_observation, observed_at: 'invalid' } }] },
])('rejects malformed or misleading projections %j', patch => {
  expect(isSkillInventoryPage({ ...page, ...patch })).toBe(false);
});
it('encodes scope and rejects mismatched scope and regressing cursors', async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(page), { headers: { 'content-type': 'application/json' } })));
  vi.stubGlobal('fetch', fetch);
  await expect(getSkillInventory('env_a', 'edge_a')).resolves.toEqual(page);
  await expect(getSkillInventory('other&env', '')).rejects.toThrow('无法核验');
  expect(String(fetch.mock.calls[1][0])).toContain('other%26env');
  await expect(getSkillInventory('', '', 'ski_a')).rejects.toThrow('无法核验');
});
