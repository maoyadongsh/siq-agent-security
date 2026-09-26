import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, expect, it, vi } from 'vitest';
import FrameworkSourcePanel, { FrameworkSourceDetails } from './FrameworkSourcePanel';
import type { FrameworkSourceView } from '@/api/frameworkSource';
const context = vi.hoisted(() => vi.fn());
vi.mock('@/components/ConsoleContext', () => ({ useConsoleContext: context }));
const value: FrameworkSourceView = { schema_version: 'enterprise-framework-source-view/v1', asset_id: 'agt',
  status: 'no_recorded_source', source: null, runtime_status: 'unverified', skill_relationship_status: 'unresolved', effective_permissions: null };
beforeEach(() => context.mockReset());
it.each(['loading', 'error'])('hides source when identity is %s', status => {
  context.mockReturnValue({ status });
  expect(renderToStaticMarkup(<FrameworkSourcePanel assetId="agt" />)).toBe('');
});
it.each([{ agents: false, environments: true }, { agents: true, environments: false }])('filters read permissions independently', access => {
  context.mockReturnValue({ status: 'ready', data: { access } });
  expect(renderToStaticMarkup(<FrameworkSourcePanel assetId="agt" />)).toBe('');
});
it('uses current card and button styles with a loading state', () => {
  context.mockReturnValue({ status: 'ready', data: { access: { agents: true, environments: true }, tenant: { id: 't' }, actor: { id: 'u', type: 'user' } } });
  const html = renderToStaticMarkup(<FrameworkSourcePanel assetId="agt" />);
  expect(html).toContain('class="card"'); expect(html).toContain('class="btn"');
  expect(html).toContain('正在核对'); expect(html).not.toContain('尚无框架');
});
it('distinguishes missing and unavailable without claiming absence', () => {
  expect(renderToStaticMarkup(<FrameworkSourceDetails value={value} />)).toContain('不代表未安装');
  expect(renderToStaticMarkup(<FrameworkSourceDetails value={{ ...value, status: 'source_unavailable' }} />)).toContain('不能按名称');
});
it.each(['openclaw', 'hermes'] as const)('escapes identifiers and labels %s history, revocation and unresolved skills', framework => {
  const html = renderToStaticMarkup(<FrameworkSourceDetails value={{ ...value, schema_version: framework === 'hermes' ? 'enterprise-framework-source-view/v2' : 'enterprise-framework-source-view/v1', status: 'historical_reported_source', source: {
    framework, instance_key: 'a'.repeat(64), environment_id: 'env', device_id: 'edge', device_revoked: true,
    config_sha256: 'b'.repeat(64), evidence_id: '<script>bad()</script>', observation_id: 'obs', observed_at: '2026-09-25T00:00:00Z',
  } }} />);
  expect(html).not.toContain('<script>'); expect(html).toContain('&lt;script&gt;');
  expect(html).toContain('已吊销，仅保留历史'); expect(html).toContain('技能安装关系仍未确认');
  expect(html).toContain('<summary>配置来源证据</summary>');
  expect(html).toContain(framework === 'hermes' ? 'Hermes profile' : 'OpenClaw 配置实例');
});
