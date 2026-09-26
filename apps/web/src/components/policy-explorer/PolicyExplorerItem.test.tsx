import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { PolicyRow } from '@/api/types';
import PolicyExplorerItem from './PolicyExplorerItem';

function policy(overrides: Partial<PolicyRow>): PolicyRow {
  return {
    id: 'pol-x',
    name: '测试策略',
    selector: { agent_ids: ['agt-1'] },
    enforcement_mode: 'warn',
    version: 2,
    status: 'draft',
    unsupported_by_backend: [],
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  };
}

const render = (p: PolicyRow) => renderToStaticMarkup(<PolicyExplorerItem policy={p} />);

describe('策略详情', () => {
  it('展示 ID/名称/版本/期望档位/状态/资产/更新时间；block 不使用 effective 样式', () => {
    const html = render(policy({ enforcement_mode: 'block', status: 'approved' }));
    expect(html).toContain('pol-x');
    expect(html).toContain('v2');
    expect(html).toContain('期望：阻断');
    expect(html).toContain('approved');
    expect(html).toContain('agt-1');
    expect(html).toContain('2026-09-01T00:00:00Z');
    // 不借用 effective 视觉与文案（详情注释中的「已生效」只出现在否定语义句中）
    expect(html).not.toContain('state-tag effective');
    expect(html).not.toContain('>已生效<');
    expect(html).toContain('实际生效情况需结合审批、部署及独立后端读回核对');
  });

  it('未覆盖项为空不推断「全部支持/全部受保护/已验证兼容」', () => {
    const html = render(policy({ unsupported_by_backend: [] }));
    expect(html).toContain('本条响应未列出未覆盖项');
    // 只允许出现在否定语义句中，不得作为结论标签
    expect(html).toContain('不等于全部支持');
    expect(html).not.toContain('>全部支持<');
    expect(html).not.toContain('>全部受保护<');
    expect(html).not.toContain('>已验证兼容<');
    const withItems = render(policy({ unsupported_by_backend: ['process.seccomp_profile', 'tool_policies'] }));
    expect(withItems).toContain('process.seccomp_profile');
    expect(withItems).toContain('tool_policies');
  });

  it('selector 异常与缺失明确提示；空列表不等于全部资产；重复 ID 有稳定 key', () => {
    expect(render(policy({ selector: {} }))).toContain('未提供');
    expect(render(policy({ selector: { agent_ids: 'agt-1' } as unknown as PolicyRow['selector'] }))).toContain('格式异常');
    const empty = render(policy({ selector: { agent_ids: [] } }));
    expect(empty).toContain('空列表（不代表全部资产）');
    const dup = render(policy({ selector: { agent_ids: ['a', 'a'] } }));
    expect(dup).toContain('<code>a</code>');
  });

  it('selector 其他字段不展示', () => {
    const html = render(
      policy({ selector: { agent_ids: ['agt-1'], labels: { team: 'secret-team' }, system_ref: 'secret-sys' } }),
    );
    expect(html).not.toContain('secret-team');
    expect(html).not.toContain('secret-sys');
    expect(html).not.toContain('labels');
  });

  it('恶意 HTML 仅按文本渲染；不生成猜测链接；原型名状态不崩溃', () => {
    const html = render(
      policy({
        name: '<img src=x onerror=alert(1)>',
        id: '<script>alert(1)</script>',
        status: '__proto__',
        enforcement_mode: 'constructor' as PolicyRow['enforcement_mode'],
      }),
    );
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;img');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('href=');
    expect(html).toContain('__proto__');
    expect(html).toContain('期望：constructor');
  });

  it('原生 details/summary', () => {
    const html = render(policy({}));
    expect(html).toContain('<details');
    expect(html).toContain('<summary');
    expect(html).toContain('查看详情');
  });
});
