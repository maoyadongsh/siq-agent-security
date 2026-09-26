import { afterEach, describe, expect, it, vi } from 'vitest';
import { getRoleSkillHistory, isRoleSkillHistory, type RoleSkillHistory } from './roleSkillSelections';

export const historyFixture: RoleSkillHistory = {
  schema_version: 'enterprise-role-skill-observations/v1', asset_id: 'asset', status: 'historical_declarations',
  relationship_status: 'unresolved', effective_permissions: null, observations_truncated: false,
  observations: [{
    id: 'rso-fixture', device: { id: 'edge-fixture', revoked: true }, task_id: 'task-fixture',
    batch_digest: 'a'.repeat(64), observed_at: '2026-09-25T00:00:00Z', received_at: '2026-09-25T00:00:01Z',
    selection: { schema_version: 'enterprise-openclaw-skill-selection/v1', source: 'defaults', status: 'declared_list', names: ['docs'] },
    source_evidence: [{ evidence_id: 'ev-fixture', content_hash: 'b'.repeat(64), observed_at: '2026-09-25T00:00:00Z' }],
  }],
};
afterEach(() => vi.unstubAllGlobals());
describe('role skill history boundary', () => {
  it('accepts declared, empty, unconfigured, unsupported, and no history distinctly', () => {
    expect(isRoleSkillHistory(historyFixture, 'asset')).toBe(true);
    for (const patch of [{ names: [] }, { names: [], source: 'none', status: 'unconfigured' }, { names: [], status: 'unsupported' }]) {
      const value = structuredClone(historyFixture);
      Object.assign(value.observations[0].selection, patch);
      expect(isRoleSkillHistory(value, 'asset')).toBe(true);
    }
    expect(isRoleSkillHistory({ ...historyFixture, observations: [], status: 'no_recorded_declaration' }, 'asset')).toBe(true);
  });
  it.each([
    { asset_id: 'other' }, { schema_version: 'wrong' }, { relationship_status: 'installed' },
    { effective_permissions: [] }, { observations_truncated: true }, { status: 'no_recorded_declaration' },
    { observations: [historyFixture.observations[0], historyFixture.observations[0]] },
    { observations: Array(101).fill(historyFixture.observations[0]) },
  ])('rejects mismatched top-level fields %j', patch => {
    expect(isRoleSkillHistory({ ...historyFixture, ...patch }, 'asset')).toBe(false);
  });
  it.each([
    { source: ['defaults'] }, { status: ['declared_list'] },
    { names: ['z', 'a'] }, { names: ['docs', 'docs'] }, { names: ['<script>'] }, { names: ['x'.repeat(129)] },
    { names: Array(65).fill('docs') }, { status: 'effective' }, { source: 'none' }, { status: 'unsupported' },
    { schema_version: 'other' },
  ])('rejects inconsistent declarations %j', patch => {
    const value = structuredClone(historyFixture);
    Object.assign(value.observations[0].selection, patch);
    expect(isRoleSkillHistory(value, 'asset')).toBe(false);
  });
  it.each([
    { source_evidence: [] }, { source_evidence: Array(65).fill(historyFixture.observations[0].source_evidence[0]) },
    { source_evidence: [{ evidence_id: 'ev', content_hash: 'bad', observed_at: '2026-09-25T00:00:00Z' }] },
    { received_at: 'invalid' }, { observed_at: '1' }, { batch_digest: 'bad' }, { device: { id: 'edge', revoked: 'yes' } },
  ])('rejects malformed source %j', patch => {
    const value = structuredClone(historyFixture);
    Object.assign(value.observations[0], patch);
    expect(isRoleSkillHistory(value, 'asset')).toBe(false);
  });
  it('does not accept ascending history as latest-first', () => {
    const value = structuredClone(historyFixture);
    value.observations.push({ ...value.observations[0], id: 'new', task_id: 'new-task', received_at: '2026-09-25T01:00:00Z' });
    expect(isRoleSkillHistory(value, 'asset')).toBe(false);
  });
  it('encodes asset identity and rejects another asset response', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(historyFixture), { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    await expect(getRoleSkillHistory('other/asset')).rejects.toThrow('无法核验');
    expect(String(fetch.mock.calls[0][0])).toContain('/agents/other%2Fasset/skill-selections');
  });
});
