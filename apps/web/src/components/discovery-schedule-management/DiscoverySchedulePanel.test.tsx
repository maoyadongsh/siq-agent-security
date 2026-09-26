/** vitest 为 node 环境且无 testing-library，用 renderToStaticMarkup 做权限门禁与未展开零请求检查。 */
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const useConsoleContext = vi.hoisted(() => vi.fn());
const listDiscoverySchedules = vi.hoisted(() => vi.fn());
vi.mock('@/components/ConsoleContext', () => ({ useConsoleContext }));
vi.mock('@/api/client', () => ({ ApiError: class extends Error { constructor(public status: number) { super('api'); } } }));
vi.mock('@/api/discoveryScheduleManagement', () => ({ listDiscoverySchedules }));
vi.mock('./discovery-schedule-management.css', () => ({}));

import DiscoverySchedulePanel from './DiscoverySchedulePanel';

const context = (access: boolean) => ({
  status: 'ready' as const,
  data: { tenant: { id: 'tnt' }, actor: { type: 'user', id: 'u' }, access: { environments: access } },
});

describe('DiscoverySchedulePanel permission gates', () => {
  it('renders nothing while identity is loading or environment read is unavailable', () => {
    useConsoleContext.mockReturnValue({ status: 'loading', data: undefined });
    expect(renderToStaticMarkup(<DiscoverySchedulePanel environmentId="env-1" />)).toBe('');
    useConsoleContext.mockReturnValue({ status: 'error', data: undefined });
    expect(renderToStaticMarkup(<DiscoverySchedulePanel environmentId="env-1" />)).toBe('');
    useConsoleContext.mockReturnValue(context(false));
    expect(renderToStaticMarkup(<DiscoverySchedulePanel environmentId="env-1" />)).toBe('');
    expect(listDiscoverySchedules).not.toHaveBeenCalled();
  });

  it('renders collapsed with zero requests until the user expands', () => {
    useConsoleContext.mockReturnValue(context(true));
    const html = renderToStaticMarkup(<DiscoverySchedulePanel environmentId="env-1" />);
    expect(html).toContain('周期发现计划');
    expect(html).toContain('aria-expanded="false"');
    expect(listDiscoverySchedules).not.toHaveBeenCalled();
  });
});
