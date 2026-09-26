import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import EnterpriseConnectionPanel from './EnterpriseConnectionPanel';

it('starts collapsed without automatically claiming a connection', () => {
  const html = renderToStaticMarkup(<EnterpriseConnectionPanel environmentId="env" />);
  expect(html).toContain('高级诊断');
  expect(html).not.toContain('open=""');
  expect(html).not.toContain('本次握手已确认');
  expect(html).toContain('不会创建沙箱、发布策略或授予智能体权限');
});
