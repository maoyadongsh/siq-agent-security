import { describe, expect, it } from 'vitest';
import type { Finding } from '@/api/types';
import {
  EMPTY_FINDING_FILTERS,
  filterFindings,
  hasActiveFindingFilters,
  isFinalStatus,
  listFindingDomains,
  severityLabel,
  statusLabel,
} from './findingExplorer';

function finding(overrides: Partial<Finding>): Finding {
  return {
    id: 'fnd-x',
    rule_id: 'R-TEST-001',
    rule_version: 1,
    severity: 'medium',
    domain: 'tool',
    asset_id: 'agt-1',
    evidence_ids: ['ev-1'],
    impact: '测试风险',
    remediation: '测试修复',
    status: 'open',
    owner_user_id: null,
    due_at: null,
    risk_acceptance: null,
    first_seen_at: '2026-09-01T00:00:00Z',
    last_seen_at: '2026-09-02T00:00:00Z',
    ...overrides,
  };
}

describe('AND 组合筛选', () => {
  const rows = [
    finding({ id: 'f1', severity: 'critical', status: 'open', domain: 'credential', rule_id: 'R-A', asset_id: 'agt-a', impact: '凭据外泄风险' }),
    finding({ id: 'f2', severity: 'high', status: 'acknowledged', domain: 'tool', rule_id: 'R-B', asset_id: 'agt-b', remediation: '收敛工具权限' }),
    finding({ id: 'f3', severity: 'critical', status: 'resolved', domain: 'credential', rule_id: 'R-C', asset_id: 'agt-a' }),
  ];

  it('级别/状态/域/搜索 AND 组合', () => {
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, severity: 'critical' })).toHaveLength(2);
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, severity: 'critical', status: 'open' })).toHaveLength(1);
    expect(
      filterFindings(rows, { severity: 'critical', status: 'open', domain: 'credential', query: 'r-a' }),
    ).toHaveLength(1);
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, severity: 'critical', status: 'acknowledged' })).toHaveLength(0);
  });

  it('文本搜索覆盖风险/规则/资产 ID、描述、修复建议，大小写与首尾空白不敏感', () => {
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, query: ' F2 ' }).map((r) => r.id)).toEqual(['f2']);
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, query: 'r-b' }).map((r) => r.id)).toEqual(['f2']);
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, query: 'AGT-A' })).toHaveLength(2);
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, query: '外泄' }).map((r) => r.id)).toEqual(['f1']);
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, query: '收敛' }).map((r) => r.id)).toEqual(['f2']);
  });

  it('清除筛选恢复全部；空列表与无匹配可区分', () => {
    expect(hasActiveFindingFilters(EMPTY_FINDING_FILTERS)).toBe(false);
    expect(hasActiveFindingFilters({ ...EMPTY_FINDING_FILTERS, query: '  ' })).toBe(false);
    expect(hasActiveFindingFilters({ ...EMPTY_FINDING_FILTERS, severity: 'low' })).toBe(true);
    expect(filterFindings([], EMPTY_FINDING_FILTERS)).toEqual([]);
    expect(filterFindings(rows, { ...EMPTY_FINDING_FILTERS, query: '不存在' })).toEqual([]);
  });

  it('同一资产的多条风险不被合并；未知枚举不丢记录、不冒充已解决', () => {
    const sameAsset = [
      finding({ id: 'f1', asset_id: 'agt-x' }),
      finding({ id: 'f2', asset_id: 'agt-x', rule_id: 'R-OTHER' }),
    ];
    expect(filterFindings(sameAsset, EMPTY_FINDING_FILTERS)).toHaveLength(2);

    const weird = finding({ id: 'fw', severity: 'weird' as Finding['severity'], status: 'pending_review' as Finding['status'] });
    const out = filterFindings([weird], EMPTY_FINDING_FILTERS);
    expect(out).toHaveLength(1);
    expect(isFinalStatus('pending_review')).toBe(false);
    expect(severityLabel('weird')).toBe('weird');
    expect(statusLabel('pending_review')).toBe('pending_review');
    expect(statusLabel('acknowledged')).toContain('不等于已解决');
    expect(statusLabel('risk_accepted')).toContain('不等于风险已消除');
  });

  it('不修改输入数组与后端状态字段', () => {
    const before = rows.map((r) => ({ ...r }));
    const out = filterFindings(rows, { ...EMPTY_FINDING_FILTERS, status: 'open' });
    expect(out).not.toBe(rows);
    expect(rows).toEqual(before);
  });

  it('listFindingDomains 跳过空域并去重排序', () => {
    expect(listFindingDomains([...rows, finding({ id: 'f4', domain: null })])).toEqual(['credential', 'tool']);
  });
});

describe('终态判定', () => {
  it.each(['__proto__', 'constructor', 'toString'])('未知值 %s 不从对象原型继承标签', (value) => {
    expect(severityLabel(value)).toBe(value);
    expect(statusLabel(value)).toBe(value);
  });
  it('resolved/risk_accepted 为终态；open/acknowledged/未知不是', () => {
    expect(isFinalStatus('resolved')).toBe(true);
    expect(isFinalStatus('risk_accepted')).toBe(true);
    expect(isFinalStatus('open')).toBe(false);
    expect(isFinalStatus('acknowledged')).toBe(false);
    expect(isFinalStatus('')).toBe(false);
  });
});
