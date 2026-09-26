import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, expect, it, vi } from 'vitest';
import RoleSkillSourcesPanel, { RoleSkillSourceDetails } from './RoleSkillSourcesPanel';
import type { RoleSkillSourcePage } from '@/api/roleSkillSources';
const context = vi.hoisted(() => vi.fn());
vi.mock('@/components/ConsoleContext', () => ({ useConsoleContext: context }));
beforeEach(() => context.mockReset());
it.each(['loading', 'error'])('hides data for identity %s', status => {
  context.mockReturnValue({ status });
  expect(renderToStaticMarkup(<RoleSkillSourcesPanel assetId="agt-one" />)).toBe('');
});
it.each([{ agents: false, environments: true }, { agents: true, environments: false }])('filters permissions independently', access => {
  context.mockReturnValue({ status: 'ready', data: { access } });
  expect(renderToStaticMarkup(<RoleSkillSourcesPanel assetId="agt-one" />)).toBe('');
});
it('reuses current styling and never shows a zero while loading', () => {
  context.mockReturnValue({ status: 'ready', data: { access: { agents: true, environments: true }, tenant: { id: 't' }, actor: { id: 'u', type: 'user' } } });
  const html = renderToStaticMarkup(<RoleSkillSourcesPanel assetId="agt-one" />);
  expect(html).toContain('class="card"'); expect(html).toContain('class="btn"');
  expect(html).toContain('正在核对技能安装来源'); expect(html).not.toContain('本页 0');
});
const value: RoleSkillSourcePage = { schema_version: 'enterprise-role-skill-sources-view/v1', asset_id: 'agt-one',
  status: 'source_unavailable', coverage: 'page_of_device_installations', items: [], declared_roots: null, next_cursor: null,
  runtime_status: 'unverified', effective_permissions: null, framework_source: { schema_version: 'enterprise-framework-source-view/v1',
    asset_id: 'agt-one', status: 'no_recorded_source', source: null, runtime_status: 'unverified', skill_relationship_status: 'unresolved', effective_permissions: null } };
it('labels unavailable without claiming no installed skills', () => {
  expect(renderToStaticMarkup(<RoleSkillSourceDetails value={value} />)).toContain('不代表未安装技能');
});
it('uses native details, plain text and historical semantics', () => {
  const html = renderToStaticMarkup(<RoleSkillSourceDetails value={{ ...value, status: 'historical_comparison', items: [{
    installation_id: 'ski_one', locator_sha256: 'a'.repeat(64), relationship_status: 'outside_declared_sources', matched_sources: [],
    observation: { observation_id: 'obs', manifest_sha256: 'b'.repeat(64), batch_digest: 'c'.repeat(64), name: '<script>bad()</script>',
      parse_status: 'parsed', parser_version: 'enterprise-skill-manifest/v1', allowed_tools_present: false, declared_tools: [], observed_at: '2026-09-25T00:00:00Z' },
  }] }} />);
  expect(html).toContain('<summary>'); expect(html).toContain('&lt;script&gt;'); expect(html).not.toContain('<script>');
  expect(html).toContain('不代表该角色不可使用'); expect(html).toContain('不证明当前存在');
  expect(html).toContain('未提供工具声明，不代表无权限');
});
