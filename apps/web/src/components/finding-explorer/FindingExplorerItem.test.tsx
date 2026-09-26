import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Finding } from '@/api/types';
import FindingExplorerItem from './FindingExplorerItem';

function finding(overrides: Partial<Finding>): Finding {
  return {
    id: 'fnd-x',
    rule_id: 'R-TEST-001',
    rule_version: 3,
    severity: 'high',
    domain: 'credential',
    asset_id: 'agt-1',
    evidence_ids: ['ev-1', 'ev-2'],
    impact: '委托 token 链路异常',
    remediation: '修复 IAM 链路',
    status: 'open',
    owner_user_id: null,
    due_at: null,
    risk_acceptance: null,
    first_seen_at: '2026-09-01T00:00:00Z',
    last_seen_at: '2026-09-02T00:00:00Z',
    ...overrides,
  };
}

const render = (f: Finding, renderActions?: (f: Finding) => React.ReactNode) =>
  renderToStaticMarkup(<FindingExplorerItem finding={f} renderActions={renderActions} />);

describe('风险详情', () => {
  it('原型属性名作为未知枚举时仍按纯文本渲染', () => {
    const html = render(finding({
      severity: '__proto__' as Finding['severity'],
      status: 'constructor' as Finding['status'],
    }));
    expect(html).toContain('__proto__');
    expect(html).toContain('constructor');
    expect(html).not.toContain('[object Object]');
    expect(html).not.toContain('function Object');
  });
  it('展示规则版本、证据 ID、时间与负责人；缺失字段显示「未提供」', () => {
    const html = render(finding({ asset_id: null, due_at: null, owner_user_id: null }));
    expect(html).toContain('R-TEST-001 / v3');
    expect(html).toContain('ev-1');
    expect(html).toContain('ev-2');
    expect(html).toContain('2026-09-01T00:00:00Z');
    expect(html).toContain('2026-09-02T00:00:00Z');
    expect(html).toContain('未提供'); // asset_id / due_at / owner_user_id
    expect(html).not.toContain('href='); // 不生成猜测链接
  });

  it('恶意 HTML 只作为文本渲染', () => {
    const html = render(
      finding({
        id: '<script>alert(1)</script>',
        impact: '<img src=x onerror=alert(1)>',
        remediation: '<b>run me</b>',
        asset_id: '<svg onload=alert(1)>',
      }),
    );
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<b>run me</b>');
    expect(html).not.toContain('<svg');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&lt;b&gt;run me&lt;/b&gt;');
  });

  it('不展开 risk_acceptance 原始 JSON', () => {
    const html = render(
      finding({ risk_acceptance: { reason: 'secret-reason', accepted_by: 'secret-user' } }),
    );
    expect(html).not.toContain('secret-reason');
    expect(html).not.toContain('secret-user');
  });

  it('使用原生 details/summary，键盘可展开；状态带语义说明', () => {
    const html = render(finding({ status: 'acknowledged' }));
    expect(html).toContain('<details');
    expect(html).toContain('<summary');
    expect(html).toContain('查看详情');
    expect(html).toContain('已确认（不等于已解决）');
  });

  it('终态记录页面不传操作时不出现确认/解决按钮', () => {
    const html = render(finding({ status: 'resolved' }));
    expect(html).not.toContain('<button');
    expect(html).not.toContain('finding-explorer-actions');
    expect(html).toContain('已终态');
  });

  it('操作经 renderActions 注入（组件本身不含业务逻辑）', () => {
    const html = render(finding({}), () => <button type="button">确认</button>);
    expect(html).toContain('确认');
  });
});
