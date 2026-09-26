import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { RuntimeBindingRow } from '@/api/types';
import RuntimeBindingItem from './RuntimeBindingItem';
import RuntimeBindingFilters from './RuntimeBindingFilters';
import { EMPTY_BINDING_FILTERS } from './runtimeBindingExplorer';

function binding(overrides: Partial<RuntimeBindingRow> = {}): RuntimeBindingRow {
  return {
    id: 'rb-x',
    tenant_id: 't1',
    environment_id: 'env-1',
    agent_instance_id: 'inst-1',
    asset_id: 'agt-1',
    backend: 'openshell-cli',
    backend_target_id: 'target-1',
    attestation: { backend_version: 'v0.0.83', secret: 'SHOULD-NOT-RENDER' },
    status: 'active',
    created_at: '2026-09-01T00:00:00Z',
    revoked_at: null,
    ...overrides,
  };
}

const render = (b: RuntimeBindingRow, renderActions?: (b: RuntimeBindingRow) => React.ReactNode) =>
  renderToStaticMarkup(<RuntimeBindingItem binding={b} renderActions={renderActions} />);

describe('绑定详情', () => {
  it('展示后端字段原文；缺失字段显示「未提供」', () => {
    const html = render(binding({ environment_id: '', revoked_at: null }));
    expect(html).toContain('rb-x');
    expect(html).toContain('agt-1');
    expect(html).toContain('inst-1');
    expect(html).toContain('target-1');
    expect(html).toContain('2026-09-01T00:00:00Z');
    expect(html).toContain('未提供'); // environment_id 空
  });

  it('attestation 不展开、不序列化、不复制原始字典', () => {
    const html = render(binding());
    expect(html).not.toContain('SHOULD-NOT-RENDER');
    expect(html).not.toContain('backend_version');
    expect(html).not.toContain('attestation');
  });

  it('不渲染 tenant_id', () => {
    const html = render(binding({ tenant_id: 'tenant-secret-value' }));
    expect(html).not.toContain('tenant-secret-value');
  });

  it('原型属性名作为未知枚举时仍按纯文本渲染（不继承标签/类）', () => {
    const html = render(binding({ status: '__proto__' as RuntimeBindingRow['status'] }));
    expect(html).toContain('__proto__');
    expect(html).not.toContain('[object Object]');
    expect(html).not.toContain('tag-ok'); // 未知状态不映射 active 标签
    expect(html).not.toContain('tag-err');
  });

  it('active 状态不推导「已验证/已保护」', () => {
    const html = render(binding({ status: 'active' }));
    expect(html).not.toContain('已验证');
    expect(html).not.toContain('已保护');
    expect(html).toContain('不等于运行时防护生效');
  });

  it('revoked 状态说明不等于进程已停止', () => {
    const html = render(binding({ status: 'revoked', revoked_at: '2026-09-02T00:00:00Z' }));
    expect(html).toContain('不等于进程已停止');
    expect(html).toContain('2026-09-02T00:00:00Z');
    expect(html).toContain('revoked');
  });

  it('恶意 HTML 只作为文本渲染', () => {
    const html = render(binding({
      id: '<script>alert(1)</script>',
      backend_target_id: '<img src=x onerror=alert(1)>',
    }));
    expect(html).not.toContain('<script>alert(1)</script>');
    expect(html).not.toContain('<img src=x');
  });

  it('renderActions 注入的内容原样渲染；页面传 null 时不渲染操作区', () => {
    const withAction = render(binding({ status: 'active' }), () => <button>吊销</button>);
    expect(withAction).toContain('吊销');
    // 组件不自行判断状态：是否注入由页面决定（非 active 时页面传 null）
    const noAction = render(binding({ status: 'revoked' }), () => null);
    expect(noAction).not.toContain('rb-explorer-actions');
  });
});

describe('筛选条', () => {
  it('后端/环境下拉从已加载数据推导', () => {
    const rows = [
      binding({ backend: 'hermes-sandbox', environment_id: 'env-2' }),
      binding({ backend: 'openshell-cli', environment_id: 'env-1' }),
    ];
    const html = renderToStaticMarkup(
      <RuntimeBindingFilters rows={rows} filters={EMPTY_BINDING_FILTERS} onChange={() => {}} />,
    );
    expect(html).toContain('hermes-sandbox');
    expect(html).toContain('openshell-cli');
    expect(html).toContain('env-1');
    expect(html).toContain('env-2');
    expect(html).toContain('清除筛选');
  });

  it('空数据时后端/环境下拉无选项（不猜测）', () => {
    const html = renderToStaticMarkup(
      <RuntimeBindingFilters rows={[]} filters={EMPTY_BINDING_FILTERS} onChange={() => {}} />,
    );
    expect(html).toContain('全部后端');
    expect(html).toContain('全部环境');
  });
});
