/**
 * 页面级（SSR 一次性渲染，effects 不执行 → useApiList 停留在 loading）：
 * 加载期间不得把旧记录/示例/零值展示成成功结果，也不得出现可执行处置入口。
 */
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import FindingsPage from './FindingsPage';

describe('FindingsPage 加载态', () => {
  it('loading 时显示加载提示，不出现示例风险或确认/解决按钮', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <FindingsPage />
      </MemoryRouter>,
    );
    expect(html).toContain('正在加载风险记录');
    expect(html).toContain('零条风险不代表当前系统安全');
    // 示例占位数据不得出现
    expect(html).not.toContain('fnd-0001');
    expect(html).not.toContain('R-AGENT-001');
    // 加载态无可执行处置入口
    expect(html).not.toContain('>确认<');
    expect(html).not.toContain('>解决<');
  });
});
