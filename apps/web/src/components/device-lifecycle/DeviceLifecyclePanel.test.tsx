import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import DeviceLifecyclePanel from './DeviceLifecyclePanel';
const context = vi.hoisted(() => vi.fn());
vi.mock('@/components/ConsoleContext', () => ({ useConsoleContext: context }));
beforeEach(() => context.mockReturnValue({ status: 'ready', data: {
  tenant: { id: 'tenant' }, actor: { id: 'actor', type: 'user' },
  access: { environments: true }, actions: { enroll_devices: true },
} }));
const render = () => renderToStaticMarkup(<MemoryRouter><DeviceLifecyclePanel environmentId="env" /></MemoryRouter>);
it('starts collapsed, with no write control and explicit scope limitations', () => {
  const html = render();
  expect(html).toContain('aria-expanded="false"');
  expect(html).toContain('不撤销智能体业务权限');
  expect(html).not.toContain('确认吊销设备凭据');
});
it.each(['loading', 'error'])('hides management while identity is %s', status => {
  context.mockReturnValue({ ...context(), status });
  expect(render()).toBe('');
});
it.each(['access', 'actions'])('does not infer management from role labels: %s denied', field => {
  const value = context();
  value.data[field] = field === 'access' ? { environments: false } : { enroll_devices: false };
  context.mockReturnValue(value);
  expect(render()).toBe('');
});
