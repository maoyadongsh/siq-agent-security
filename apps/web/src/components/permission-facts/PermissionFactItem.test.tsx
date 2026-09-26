import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { PermissionFactRow } from '@/api/types';
import PermissionFactsOverview from './PermissionFactsOverview';
import PermissionFactItem from './PermissionFactItem';

const NOW = Date.parse('2026-09-25T12:00:00Z');

function fact(overrides: Partial<PermissionFactRow>): PermissionFactRow {
  return {
    id: 'pf-x',
    environment_id: 'env-1',
    subject_type: 'agent_instance',
    subject_id: 'subject-a',
    delegated_user: null,
    domain: 'filesystem',
    action: 'fs.read',
    resource_type: 'path',
    resource_value: '/data/a',
    effect: 'allow',
    conditions: {},
    state: 'declared',
    authority: 'siq-iam',
    authority_revision: 'r1',
    evidence_ids: ['ev-1'],
    valid_from: null,
    valid_until: null,
    ...overrides,
  };
}

describe('状态概览', () => {
  it('五种状态全部展示并计数，明确仅统计已加载记录', () => {
    const html = renderToStaticMarkup(
      <PermissionFactsOverview
        rows={[
          fact({ id: 'a', state: 'declared' }),
          fact({ id: 'b', state: 'inferred' }),
          fact({ id: 'c', state: 'observed' }),
          fact({ id: 'd', state: 'effective' }),
          fact({ id: 'e', state: 'unknown' }),
        ]}
      />,
    );
    for (const label of ['声明', '推断', '观测', '生效', '未知']) {
      expect(html).toContain(label);
    }
    expect(html).toContain('已加载 5 条记录');
    expect(html).toContain('不代表组织全量');
    expect(html).not.toContain('全面保护');
    expect(html).not.toContain('阻断已验证');
  });
});

describe('权限事实详情', () => {
  it.each(['__proto__', 'constructor', 'toString'])('特殊枚举 %s 不作为对象或函数渲染', (value) => {
    const row = fact({ state: value as PermissionFactRow['state'], domain: value,
      effect: value as PermissionFactRow['effect'], subject_type: value });
    const html = renderToStaticMarkup(<PermissionFactItem row={row} now={NOW} />);
    expect(html).toContain(value);
    expect(html).toContain('未识别的事实状态');
    expect(html).not.toContain('[object Object]');
    expect(html).not.toContain('function Object');
  });
  it('过期 effective 记录展示过期提示，不出现无保留成功文案', () => {
    const html = renderToStaticMarkup(
      <PermissionFactItem
        row={fact({ state: 'effective', valid_until: '2026-09-25T11:00:00Z' })}
        now={NOW}
      />,
    );
    expect(html).toContain('生效');
    expect(html).toContain('已过期');
    expect(html).toContain('按当前设备时间判断');
    expect(html).not.toContain('全面保护');
    expect(html).not.toContain('阻断已验证');
    expect(html).toContain('pf-item-expired');
  });

  it('详情含 revision、证据 ID 与缺失字段提示；证据仅作标识', () => {
    const html = renderToStaticMarkup(
      <PermissionFactItem
        row={fact({
          environment_id: null,
          authority_revision: null,
          evidence_ids: ['ev-long-0001', 'ev-long-0002'],
          valid_from: '2026-09-01T00:00:00Z',
        })}
        now={NOW}
      />,
    );
    expect(html).toContain('未提供'); // environment_id / authority_revision / valid_until
    expect(html).toContain('ev-long-0001');
    expect(html).toContain('ev-long-0002');
    expect(html).toContain('不代表证据内容已被核验');
    expect(html).not.toContain('href='); // 不生成猜测链接
  });

  it('恶意 HTML 字符串只作为文本渲染', () => {
    const html = renderToStaticMarkup(
      <PermissionFactItem
        row={fact({
          subject_id: '<script>alert(1)</script>',
          resource_value: '<img src=x onerror=alert(1)>',
          authority: '<b>evil</b>',
        })}
        now={NOW}
      />,
    );
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<b>evil</b>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&lt;b&gt;evil&lt;/b&gt;');
  });

  it('不展开 delegated_user 或 conditions 原始 JSON', () => {
    const html = renderToStaticMarkup(
      <PermissionFactItem
        row={fact({
          delegated_user: { user_id: 'user-secret-name', token_ref: 'tok' },
          conditions: { purpose: 'secret-purpose' },
        })}
        now={NOW}
      />,
    );
    expect(html).not.toContain('user-secret-name');
    expect(html).not.toContain('secret-purpose');
  });

  it('使用原生 details/summary，键盘可展开', () => {
    const html = renderToStaticMarkup(<PermissionFactItem row={fact({})} now={NOW} />);
    expect(html).toContain('<details');
    expect(html).toContain('<summary');
    expect(html).toContain('查看详情');
  });
});
