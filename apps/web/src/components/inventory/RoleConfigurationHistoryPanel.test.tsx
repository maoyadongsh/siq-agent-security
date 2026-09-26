// 交互测试需要最小 DOM shim（必须在 react/react-dom 之前安装全局）。
import { FakeElement, fakeDocument } from '../../pages/runtimeBindingPageDomShim';
import { renderToStaticMarkup } from 'react-dom/server';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import RoleConfigurationHistoryPanel, { ConfigurationHistoryDetails } from './RoleConfigurationHistoryPanel';
import type { ConfigurationHistoryPage, ConfigurationSnapshot } from '@/api/roleConfigurationHistory';
import type { SnapshotComparisonPage } from '@/api/roleSkillSnapshotComparison';
const context = vi.hoisted(() => vi.fn());
vi.mock('@/components/ConsoleContext', () => ({ useConsoleContext: context }));
const historyMock = vi.hoisted(() => vi.fn());
vi.mock('@/api/roleConfigurationHistory', async () => {
  const actual = await vi.importActual<typeof import('@/api/roleConfigurationHistory')>('@/api/roleConfigurationHistory');
  return { ...actual, getConfigurationHistory: historyMock };
});
const comparisonMock = vi.hoisted(() => vi.fn());
vi.mock('@/api/roleSkillSnapshotComparison', async () => {
  const actual = await vi.importActual<typeof import('@/api/roleSkillSnapshotComparison')>('@/api/roleSkillSnapshotComparison');
  return { ...actual, getSnapshotComparison: comparisonMock };
});
it.each(['loading', 'error'])('does not expose history during identity %s', status => {
  context.mockReturnValue({ status });
  expect(renderToStaticMarkup(<RoleConfigurationHistoryPanel assetId="agt_one" />)).toBe('');
});
it.each([{ agents: false, environments: true }, { agents: true, environments: false }])('requires both read permissions %#', access => {
  context.mockReturnValue({ status: 'ready', data: { access } });
  expect(renderToStaticMarkup(<RoleConfigurationHistoryPanel assetId="agt_one" />)).toBe('');
});
it('uses current card/button styling and does not manufacture zero while loading', () => {
  context.mockReturnValue({ status: 'ready', data: { access: { agents: true, environments: true }, tenant: { id: 'fixture' }, actor: { type: 'user', id: 'fixture' } } });
  const html = renderToStaticMarkup(<RoleConfigurationHistoryPanel assetId="agt_one" />);
  expect(html).toContain('class="card"'); expect(html).toContain('class="btn"');
  expect(html).toContain('正在读取配置历史'); expect(html).not.toContain('本页 0');
});
const page: ConfigurationHistoryPage = { schema_version: 'enterprise-role-configuration-history/v1', asset_id: 'agt_one',
  coverage: 'recorded_configuration_observations', items: [], next_cursor: null, runtime_status: 'unverified', effective_permissions: null };
it('empty history is not evidence of absence or protection', () => {
  const html = renderToStaticMarkup(<ConfigurationHistoryDetails value={page} />);
  expect(html).toContain('无可读配置历史'); expect(html).toContain('不代表未安装智能体或技能');
});
it('renders identifiers as text, separate times, missing roots and revoked history', () => {
  const html = renderToStaticMarkup(<ConfigurationHistoryDetails value={{ ...page, items: [{
    observation_id: 'rco_one', environment_id: 'env-one', device_id: 'edge-one', device_revoked: true,
    observed_at: '2026-09-24T00:00:00Z', received_at: '2026-09-25T00:00:00Z', status: 'recorded_snapshot',
    configuration: { task_id: 'task-one', batch_digest: 'a'.repeat(64), skill_source_roots: null,
      framework_source: { schema_version: 'enterprise-framework-source/v1', framework: 'openclaw', instance_key: 'b'.repeat(64), config_sha256: 'c'.repeat(64), evidence_id: '<script>bad()</script>' } },
  }] }} />);
  expect(html).toContain('<summary>'); expect(html).toContain('&lt;script&gt;'); expect(html).not.toContain('<script>');
  expect(html).toContain('本快照未记录，不从最新配置补填'); expect(html).toContain('已吊销，仅保留历史');
  expect(html).toContain('2026-09-24T00:00:00Z'); expect(html).toContain('2026-09-25T00:00:00Z');
  expect(html).toContain('不是原批重新验签证明'); expect(html).toContain('不证明角色已加载技能或权限已生效');
});
it('unavailable record does not fall back to latest configuration', () => {
  const html = renderToStaticMarkup(<ConfigurationHistoryDetails value={{ ...page, items: [{
    observation_id: 'rco_one', environment_id: 'env-one', device_id: 'edge-one', device_revoked: false,
    observed_at: '2026-09-24T00:00:00Z', received_at: '2026-09-25T00:00:00Z', status: 'snapshot_unavailable', configuration: null,
  }] }} />);
  expect(html).toContain('配置快照不可核对'); expect(html).toContain('也不回退最新配置'); expect(html).not.toContain('配置内容摘要');
});

/* ---------------- 交互测试（最小 DOM shim + react-dom/client，非源码字符串匹配） ---------------- */
const apiError = (status: number) => new ApiError(status, `请求失败（HTTP ${status}）`);
function defer<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
function snapshotRow(id: string, revoked = true): ConfigurationSnapshot {
  return { observation_id: id, observed_at: '2026-09-24T00:00:00Z', received_at: '2026-09-25T00:00:00Z',
    environment_id: 'env-one', device_id: 'edge-one', device_revoked: revoked, status: 'recorded_snapshot',
    configuration: { task_id: 'task-one', batch_digest: 'a'.repeat(64),
      skill_source_roots: { schema_version: 'enterprise-role-skill-roots/v1', basis: 'agent_workspace', status: 'declared',
        roots: [{ kind: 'workspace_skills', locator_sha256: 'c'.repeat(64) }, { kind: 'project_agent_skills', locator_sha256: 'd'.repeat(64) }] },
      framework_source: { schema_version: 'enterprise-framework-source/v1', framework: 'openclaw', instance_key: 'b'.repeat(64),
        config_sha256: 'e'.repeat(64), evidence_id: 'ev-one' } } };
}
function historyPage(items: ConfigurationSnapshot[], nextCursor: string | null): ConfigurationHistoryPage {
  return { schema_version: 'enterprise-role-configuration-history/v1', asset_id: 'agt_one',
    coverage: 'recorded_configuration_observations', items, next_cursor: nextCursor, runtime_status: 'unverified', effective_permissions: null };
}
function comparisonPage(observationId: string, patch: Partial<SnapshotComparisonPage> = {}): SnapshotComparisonPage {
  return { schema_version: 'enterprise-role-skill-snapshot-comparison/v1', asset_id: 'agt_one',
    configuration_observation: snapshotRow(observationId), status: 'historical_comparison',
    comparison_basis: 'latest_skill_observations_against_saved_configuration', coverage: 'page_of_device_installations',
    runtime_status: 'unverified', effective_permissions: null,
    items: [{ installation_id: 'ski_one', locator_sha256: 'f'.repeat(64), relationship_status: 'historical_source_match',
      matched_sources: [{ kind: 'workspace_skills', locator_sha256: 'c'.repeat(64) }],
      observation: { observation_id: 'smo-one', manifest_sha256: '1'.repeat(64), parser_version: 'enterprise-skill-manifest/v1',
        parse_status: 'parsed', name: 'demo-skill', allowed_tools_present: false, declared_tools: [],
        observed_at: '2026-09-25T01:00:00Z', batch_digest: '2'.repeat(64) } }],
    next_cursor: null, ...patch };
}
function readyContext() {
  context.mockReturnValue({ status: 'ready', data: { access: { agents: true, environments: true },
    tenant: { id: 'fixture' }, actor: { type: 'user', id: 'fixture' } } });
}
async function renderPanel() {
  const container = new FakeElement('div');
  container.ownerDocument = fakeDocument;
  const root: Root = createRoot(container as unknown as DocumentFragment);
  await act(async () => { root.render(<RoleConfigurationHistoryPanel assetId="agt_one" />); });
  const click = (target: FakeElement) => {
    const event = { type: 'click', target, currentTarget: container, nativeEvent: null, bubbles: true, cancelable: true,
      preventDefault() {}, stopPropagation() {}, stopImmediatePropagation() {},
      isDefaultPrevented: () => false, isPropagationStopped: () => false, persist() {} };
    for (const fn of container.listeners.click ?? []) fn(event);
  };
  const button = (name: string) => container.querySelectorAll('button').find(b => b.textContent?.includes(name)) ?? null;
  return { container, root, html: () => container.innerHTML, click, button };
}
beforeEach(() => {
  historyMock.mockReset();
  comparisonMock.mockReset();
});
describe('快照对照交互', () => {
  // 历史页校验要求 received_at 降序（同时间戳时 observation_id 降序），故 rco_b 在前。
  const twoRows = () => historyPage([snapshotRow('rco_b'), snapshotRow('rco_a')], null);
  const compareButton = (container: FakeElement, index: number) =>
    container.querySelectorAll('details')[index]?.querySelectorAll('button')
      .find(b => b.textContent?.includes('与最新技能观察对照')) ?? null;
  it('点击前零对照请求；点击后仅请求所选快照', async () => {
    readyContext();
    historyMock.mockResolvedValue(twoRows());
    comparisonMock.mockResolvedValue(comparisonPage('rco_b'));
    const { html, root, click, button } = await renderPanel();
    await act(async () => {});
    expect(comparisonMock).not.toHaveBeenCalled();
    expect(button('与最新技能观察对照')).toBeTruthy();
    await act(async () => { click(button('与最新技能观察对照')!); });
    expect(comparisonMock).toHaveBeenCalledExactlyOnceWith('agt_one', 'rco_b', undefined);
    await act(async () => {});
    expect(html()).toContain('rco_b');
    expect(html()).not.toContain('正在读取所选快照的技能对照');
    root.unmount();
  });
  it('A→B 乱序成功：A 的迟到成功不能覆盖 B', async () => {
    readyContext();
    historyMock.mockResolvedValue(twoRows());
    const { container, html, root, click } = await renderPanel();
    await act(async () => {});
    const first = defer<SnapshotComparisonPage>();
    const second = defer<SnapshotComparisonPage>();
    comparisonMock.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    await act(async () => { click(compareButton(container, 0)!); });
    expect(comparisonMock).toHaveBeenLastCalledWith('agt_one', 'rco_b', undefined);
    await act(async () => { click(container.querySelectorAll('button').find(b => b.textContent?.includes('关闭对照'))!); });
    await act(async () => { click(compareButton(container, 1)!); });
    expect(comparisonMock).toHaveBeenLastCalledWith('agt_one', 'rco_a', undefined);
    second.resolve(comparisonPage('rco_a'));
    await act(async () => {});
    expect(html()).toContain('rco_a');
    const late = comparisonPage('rco_b');
    late.items[0].observation!.name = 'late-success-marker';
    first.resolve(late);
    await act(async () => {});
    expect(html()).toContain('rco_a');
    expect(html()).not.toContain('late-success-marker'); // A 的迟到成功被丢弃
    root.unmount();
  });
  it('A→B 乱序失败：A 的迟到失败不能覆盖 B 的成功', async () => {
    readyContext();
    historyMock.mockResolvedValue(twoRows());
    const { container, html, root, click } = await renderPanel();
    await act(async () => {});
    const first = defer<SnapshotComparisonPage>();
    const second = defer<SnapshotComparisonPage>();
    comparisonMock.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    await act(async () => { click(compareButton(container, 0)!); });
    await act(async () => { click(container.querySelectorAll('button').find(b => b.textContent?.includes('关闭对照'))!); });
    await act(async () => { click(compareButton(container, 1)!); });
    second.resolve(comparisonPage('rco_a'));
    await act(async () => {});
    expect(html()).toContain('rco_a');
    first.reject(apiError(503));
    await act(async () => {});
    expect(html()).toContain('rco_a');
    expect(html()).not.toContain('role="alert"');
    root.unmount();
  });
  it('分页失败保留已成功页，重试使用同一快照与失败游标', async () => {
    readyContext();
    historyMock.mockResolvedValue(historyPage([snapshotRow('rco_b')], null));
    const { html, root, click, button } = await renderPanel();
    await act(async () => {});
    const pg = comparisonPage('rco_b', { next_cursor: 'ski_one' });
    comparisonMock.mockResolvedValueOnce(pg);
    await act(async () => { click(button('与最新技能观察对照')!); });
    await act(async () => {});
    expect(html()).toContain('ski_one');
    comparisonMock.mockRejectedValueOnce(apiError(503));
    await act(async () => { click(button('下一页对照')!); });
    await act(async () => {});
    expect(html()).toContain('快照技能对照读取失败');
    expect(html()).toContain('ski_one'); // 已成功页保留
    expect(comparisonMock).toHaveBeenLastCalledWith('agt_one', 'rco_b', 'ski_one');
    const retriedPage = defer<SnapshotComparisonPage>();
    comparisonMock.mockReturnValueOnce(retriedPage.promise);
    await act(async () => { click(button('重试本页对照')!); });
    expect(html()).toContain('正在读取下一页对照');
    expect(html()).toContain('ski_one');
    expect(html()).not.toContain('快照技能对照读取失败');
    retriedPage.resolve(comparisonPage('rco_b', { next_cursor: null, items: [] }));
    await act(async () => {});
    expect(html()).toContain('当前页没有安装记录');
    expect(comparisonMock).toHaveBeenLastCalledWith('agt_one', 'rco_b', 'ski_one');
    root.unmount();
  });
  it('旧分页响应不污染新快照', async () => {
    readyContext();
    historyMock.mockResolvedValue(twoRows());
    const { container, html, root, click } = await renderPanel();
    await act(async () => {});
    const firstPage = defer<SnapshotComparisonPage>();
    const stalePage = defer<SnapshotComparisonPage>();
    comparisonMock.mockReturnValueOnce(firstPage.promise).mockReturnValueOnce(stalePage.promise);
    await act(async () => { click(compareButton(container, 0)!); });
    firstPage.resolve(comparisonPage('rco_b', { next_cursor: 'ski_one' }));
    await act(async () => {});
    await act(async () => { click(container.querySelectorAll('button').find(b => b.textContent?.includes('下一页对照'))!); });
    // 在旧分页响应返回前关闭并切换到另一快照
    await act(async () => { click(container.querySelectorAll('button').find(b => b.textContent?.includes('关闭对照'))!); });
    comparisonMock.mockResolvedValue(comparisonPage('rco_a'));
    await act(async () => { click(compareButton(container, 1)!); });
    await act(async () => {});
    expect(html()).toContain('rco_a');
    const stale = comparisonPage('rco_b', { next_cursor: null });
    stale.items[0].observation!.name = 'stale-page-marker';
    stalePage.resolve(stale);
    await act(async () => {});
    expect(html()).toContain('rco_a');
    expect(html()).not.toContain('stale-page-marker'); // 旧分页（rco_b 的页）被丢弃
    root.unmount();
  });
  it('关闭对照后迟到结果不重新显示', async () => {
    readyContext();
    historyMock.mockResolvedValue(historyPage([snapshotRow('rco_b')], null));
    const { html, root, click, button } = await renderPanel();
    await act(async () => {});
    const pending = defer<SnapshotComparisonPage>();
    comparisonMock.mockReturnValue(pending.promise);
    await act(async () => { click(button('与最新技能观察对照')!); });
    await act(async () => { click(button('关闭对照')!); });
    pending.resolve(comparisonPage('rco_b'));
    await act(async () => {});
    expect(html()).not.toContain('与最新技能观察对照</h3>');
    expect(html()).not.toContain('smo-one');
    root.unmount();
  });
  it('刷新与历史翻页清除对照选择', async () => {
    readyContext();
    historyMock.mockResolvedValue(historyPage([snapshotRow('rco_b'), snapshotRow('rco_a')], 'rco_a'));
    const { html, root, click, button } = await renderPanel();
    await act(async () => {});
    comparisonMock.mockResolvedValue(comparisonPage('rco_b'));
    await act(async () => { click(button('与最新技能观察对照')!); });
    await act(async () => {});
    expect(html()).toContain('与最新技能观察对照</h3>');
    await act(async () => { click(button('刷新配置历史')!); });
    await act(async () => {});
    expect(html()).not.toContain('与最新技能观察对照</h3>');
    expect(comparisonMock).toHaveBeenCalledTimes(1);
    // 重新选择后翻页清除
    await act(async () => { click(button('与最新技能观察对照')!); });
    await act(async () => {});
    expect(html()).toContain('与最新技能观察对照</h3>');
    await act(async () => { click(button('下一页配置历史')!); });
    await act(async () => {});
    expect(html()).not.toContain('与最新技能观察对照</h3>');
    root.unmount();
  });
  it('403/404 安全提示，不渲染异常原文', async () => {
    readyContext();
    historyMock.mockResolvedValue(historyPage([snapshotRow('rco_b')], null));
    const { html, root, click, button } = await renderPanel();
    await act(async () => {});
    comparisonMock.mockRejectedValue(apiError(403));
    await act(async () => { click(button('与最新技能观察对照')!); });
    await act(async () => {});
    expect(html()).toContain('当前账号无权读取该快照的技能对照');
    comparisonMock.mockRejectedValue(apiError(404));
    await act(async () => { click(button('重试本页对照')!); });
    await act(async () => {});
    expect(html()).toContain('不可读取或不存在');
    expect(html()).not.toContain('HTTP 404');
    root.unmount();
  });
  it('snapshot_unavailable 明确不可对照，不回退最新来源', async () => {
    readyContext();
    historyMock.mockResolvedValue(historyPage([snapshotRow('rco_b')], null));
    const { html, root, click, button } = await renderPanel();
    await act(async () => {});
    comparisonMock.mockResolvedValue(comparisonPage('rco_b', { status: 'snapshot_unavailable', items: [], next_cursor: null }));
    await act(async () => { click(button('与最新技能观察对照')!); });
    await act(async () => {});
    expect(html()).toContain('该快照不可对照');
    expect(html()).toContain('不回退最新配置');
    expect(html()).not.toContain('ski_one');
    root.unmount();
  });
  it('XSS 内容仅作为文本；配置与技能两侧时间正确展示', async () => {
    readyContext();
    historyMock.mockResolvedValue(historyPage([snapshotRow('rco_b')], null));
    const { container, html, root, click, button } = await renderPanel();
    await act(async () => {});
    const xssPage = comparisonPage('rco_b');
    xssPage.items[0].observation!.name = '<script>window.__cmp_xss=1</script>';
    comparisonMock.mockResolvedValue(xssPage);
    await act(async () => { click(button('与最新技能观察对照')!); });
    await act(async () => {});
    // shim 的 innerHTML 不做 HTML 转义（真实 DOM 会），故断言不存在 <script> 元素节点；
    // 转义行为由上方 renderToStaticMarkup 用例（&lt;script&gt;）覆盖。
    expect(container.querySelectorAll('script').length).toBe(0);
    expect(html()).toContain('<script>window.__cmp_xss=1</script>'); // 仅作为文本内容
    expect(html()).toContain('2026-09-24T00:00:00Z'); // 配置观察时间
    expect(html()).toContain('2026-09-25T00:00:00Z'); // 接收时间
    expect(html()).toContain('2026-09-25T01:00:00Z'); // 技能观察时间
    expect(html()).toContain('已吊销，仅保留历史');
    root.unmount();
  });
});
