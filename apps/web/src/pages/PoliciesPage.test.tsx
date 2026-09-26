/**
 * 页面级（SSR 一次性渲染，effects 不执行 → useApiList 停留在 loading）：
 * 加载期间不展示伪零/列表；新建策略入口仍在。
 */
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import PoliciesPage from './PoliciesPage';

describe('PoliciesPage 加载态', () => {
  it('loading 时显示加载提示与新建入口，不出现伪零计数或列表', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PoliciesPage />
      </MemoryRouter>,
    );
    expect(html).toContain('正在加载策略');
    expect(html).toContain('新建策略');
    expect(html).not.toContain('匹配 0 条');
    expect(html).not.toContain('policy-explorer-item');
  });
});
