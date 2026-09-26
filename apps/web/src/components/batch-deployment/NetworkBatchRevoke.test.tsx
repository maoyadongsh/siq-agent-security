import { beforeEach, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import NetworkBatchRevoke, { NetworkBatchRecovery } from './NetworkBatchRevoke';
const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ get, post }));
beforeEach(() => { get.mockReset(); post.mockReset(); });
const policies = [{ id: 'p1', name: 'Policy <script>unsafe()</script>', version: 1 }];
it('starts with no selected policies or writes and escapes names', () => {
  const html = renderToStaticMarkup(<MemoryRouter><NetworkBatchRevoke policies={policies} /></MemoryRouter>);
  expect(html).toContain('已选 0 份策略');
  expect(html).toContain('不是立即撤权');
  expect(html).not.toContain('<script>');
  expect(html).not.toContain('checked=""');
  expect(get).not.toHaveBeenCalled(); expect(post).not.toHaveBeenCalled();
});
it.each(['?revoke_request=old', '?revoke_batch=11111111-1111-4111-8111-111111111111'])('locks new work while recovering %s', search => {
  const html = renderToStaticMarkup(<MemoryRouter initialEntries={[`/permissions${search}`]}><NetworkBatchRevoke policies={policies} /></MemoryRouter>);
  expect(html).toContain('当前不允许另建批次');
  expect(html).toContain('disabled=""');
  expect(post).not.toHaveBeenCalled();
});
it('recovery has an explicit loading state, not a successful zero count', () => {
  const html = renderToStaticMarkup(<MemoryRouter><NetworkBatchRecovery requestKey="11111111-1111-4111-8111-111111111111" /></MemoryRouter>);
  expect(html).toContain('正在查询原批次');
  expect(html).not.toContain('当前状态');
  expect(html).toContain('不重放申请');
  expect(post).not.toHaveBeenCalled();
});
