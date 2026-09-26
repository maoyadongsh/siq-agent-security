import { describe, expect, it } from 'vitest';
import type { PolicyRow } from '@/api/types';
import {
  EMPTY_POLICY_FILTERS,
  MODE_LABELS,
  extractAgentIds,
  filterPolicies,
  hasActivePolicyFilters,
  listPolicyStatuses,
  modeExpectationText,
  modeLabel,
  safeLookup,
} from './policyExplorer';

function policy(overrides: Partial<PolicyRow>): PolicyRow {
  return {
    id: 'pol-x',
    name: '测试策略',
    selector: { agent_ids: ['agt-1'] },
    enforcement_mode: 'warn',
    version: 1,
    status: 'draft',
    unsupported_by_backend: [],
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  };
}

describe('AND 组合筛选与搜索', () => {
  const rows = [
    policy({ id: 'p1', name: '财务网络策略', enforcement_mode: 'block', status: 'approved', selector: { agent_ids: ['agt-fin-01'] }, unsupported_by_backend: [] }),
    policy({ id: 'p2', name: '研发审计策略', enforcement_mode: 'audit_only', status: 'draft', selector: { agent_ids: ['agt-dev-01'] }, unsupported_by_backend: ['process.seccomp'] }),
    policy({ id: 'p3', name: '告警策略', enforcement_mode: 'warn', status: 'approved', selector: { agent_ids: ['agt-ops-01'] }, unsupported_by_backend: [] }),
  ];

  it('档位/状态/未覆盖项/搜索 AND 组合', () => {
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, mode: 'block' })).toHaveLength(1);
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, mode: 'block', status: 'approved' })).toHaveLength(1);
    expect(filterPolicies(rows, { mode: 'block', status: 'approved', unsupported: 'empty', query: '' })).toHaveLength(1);
    expect(filterPolicies(rows, { mode: 'block', status: 'approved', unsupported: 'with', query: '' })).toHaveLength(0);
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, unsupported: 'with' }).map((r) => r.id)).toEqual(['p2']);
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, unsupported: 'empty' })).toHaveLength(2);
  });

  it('搜索覆盖名称/策略 ID/目标资产 ID；大小写与空白不敏感；selector 其他字段不进搜索', () => {
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, query: ' 财务 ' }).map((r) => r.id)).toEqual(['p1']);
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, query: 'P2' }).map((r) => r.id)).toEqual(['p2']);
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, query: 'AGT-OPS-01' }).map((r) => r.id)).toEqual(['p3']);
    const withLabels = [
      policy({ id: 'p9', selector: { agent_ids: ['agt-1'], labels: { team: 'secret-team' }, system_ref: 'secret-sys' } }),
    ];
    expect(filterPolicies(withLabels, { ...EMPTY_POLICY_FILTERS, query: 'secret-team' })).toHaveLength(0);
    expect(filterPolicies(withLabels, { ...EMPTY_POLICY_FILTERS, query: 'secret-sys' })).toHaveLength(0);
  });

  it('清除筛选；空列表与无匹配；不修改输入', () => {
    expect(hasActivePolicyFilters(EMPTY_POLICY_FILTERS)).toBe(false);
    expect(hasActivePolicyFilters({ ...EMPTY_POLICY_FILTERS, query: ' ' })).toBe(false);
    expect(hasActivePolicyFilters({ ...EMPTY_POLICY_FILTERS, unsupported: 'empty' })).toBe(true);
    expect(filterPolicies([], EMPTY_POLICY_FILTERS)).toEqual([]);
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, query: '不存在' })).toEqual([]);
    const before = rows.map((r) => ({ ...r }));
    expect(filterPolicies(rows, { ...EMPTY_POLICY_FILTERS, mode: 'warn' })).not.toBe(rows);
    expect(rows).toEqual(before);
  });

  it('不同策略的相同资产不合并；状态选项来自真实值且含未知值', () => {
    const sameTarget = [
      policy({ id: 'pa', selector: { agent_ids: ['agt-x'] } }),
      policy({ id: 'pb', selector: { agent_ids: ['agt-x'] } }),
    ];
    expect(filterPolicies(sameTarget, EMPTY_POLICY_FILTERS)).toHaveLength(2);
    expect(filterPolicies(sameTarget, { ...EMPTY_POLICY_FILTERS, query: 'agt-x' })).toHaveLength(2);
    const weird = policy({ id: 'pw', status: 'pending_review_custom', enforcement_mode: 'strange' as PolicyRow['enforcement_mode'] });
    const out = filterPolicies([...rows, weird], EMPTY_POLICY_FILTERS);
    expect(out).toHaveLength(4);
    expect(listPolicyStatuses([...rows, weird])).toEqual(['approved', 'draft', 'pending_review_custom']);
  });
});

describe('档位与未覆盖项语义', () => {
  it('block 显示为「期望：阻断」，不出现 effective/已生效', () => {
    expect(modeExpectationText('block')).toBe('期望：阻断');
    expect(modeExpectationText('block')).not.toContain('生效');
    expect(modeLabel('audit_only')).toBe('仅审计');
    expect(modeLabel('unknown-mode')).toBe('unknown-mode');
  });

  it('原型属性名不会取到原型成员', () => {
    expect(safeLookup(MODE_LABELS, '__proto__')).toBeUndefined();
    expect(safeLookup(MODE_LABELS, 'constructor')).toBeUndefined();
    expect(safeLookup(MODE_LABELS, 'toString')).toBeUndefined();
    expect(modeLabel('toString')).toBe('toString');
  });
});

describe('selector.agent_ids 白名单提取', () => {
  it('缺失/null/非对象 → missing；类型异常 → invalid；空数组保留为空', () => {
    expect(extractAgentIds(null)).toEqual({ kind: 'missing' });
    expect(extractAgentIds(undefined)).toEqual({ kind: 'missing' });
    expect(extractAgentIds({})).toEqual({ kind: 'missing' });
    expect(extractAgentIds('x' as unknown as Record<string, unknown>)).toEqual({ kind: 'missing' });
    expect(extractAgentIds({ agent_ids: 'agt-1' })).toEqual({ kind: 'invalid' });
    expect(extractAgentIds({ agent_ids: ['a', 1] })).toEqual({ kind: 'invalid' });
    expect(extractAgentIds({ agent_ids: [] })).toEqual({ kind: 'ok', ids: [] });
    expect(extractAgentIds({ agent_ids: ['a', 'a', 'b'] })).toEqual({ kind: 'ok', ids: ['a', 'a', 'b'] });
  });

  it('通过原型链的 agent_ids 不被当作自身属性', () => {
    const polluted = Object.create({ agent_ids: ['inherited'] });
    expect(extractAgentIds(polluted)).toEqual({ kind: 'missing' });
  });
});
