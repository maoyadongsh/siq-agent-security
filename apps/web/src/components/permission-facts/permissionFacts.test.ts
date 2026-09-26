import { describe, expect, it } from 'vitest';
import type { PermissionFactRow } from '@/api/types';
import {
  EMPTY_FILTERS,
  PERMISSION_FACT_STATES,
  assessValidity,
  countByState,
  filterPermissionFacts,
  hasActiveFilters,
  listAuthorities,
  listDomains,
  permissionStateExplanation,
} from './permissionFacts';

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

describe('五态分组与计数', () => {
  it.each(['__proto__', 'constructor', 'toString'])('特殊未知状态 %s 计入未知且解释为文字', (state) => {
    const counts = countByState([fact({ state: state as PermissionFactRow['state'] })]);
    expect(counts).toEqual({ declared: 0, inferred: 0, observed: 0, effective: 0, unknown: 1 });
    expect(permissionStateExplanation(state)).toBe('未识别的事实状态，不得视为已生效');
  });
  it('对五类状态分别计数，键始终齐全', () => {
    const rows = [
      fact({ id: 'a', state: 'declared' }),
      fact({ id: 'b', state: 'inferred' }),
      fact({ id: 'c', state: 'observed' }),
      fact({ id: 'd', state: 'effective' }),
      fact({ id: 'e', state: 'unknown' }),
      fact({ id: 'f', state: 'effective' }),
    ];
    const counts = countByState(rows);
    expect(counts).toEqual({ declared: 1, inferred: 1, observed: 1, effective: 2, unknown: 1 });
    expect(Object.keys(counts).sort()).toEqual([...PERMISSION_FACT_STATES].sort());
  });

  it('空列表各状态为 0；未识别 state 计入 unknown', () => {
    expect(countByState([])).toEqual({ declared: 0, inferred: 0, observed: 0, effective: 0, unknown: 0 });
    expect(countByState([fact({ state: 'surprise' as PermissionFactRow['state'] })]).unknown).toBe(1);
  });

  it('相同 subject_id 的不同事实不会被合并', () => {
    const rows = [
      fact({ id: 'a', subject_id: 'same', action: 'fs.read' }),
      fact({ id: 'b', subject_id: 'same', action: 'fs.write' }),
    ];
    expect(countByState(rows).declared).toBe(2);
    expect(filterPermissionFacts(rows, EMPTY_FILTERS)).toHaveLength(2);
  });

  it('effective 与 authority 互不推导', () => {
    const openshellDeclared = fact({ authority: 'openshell', state: 'declared' });
    const iamEffective = fact({ id: 'b', authority: 'siq-iam', state: 'effective' });
    const rows = [openshellDeclared, iamEffective];
    expect(countByState(rows).declared).toBe(1);
    expect(countByState(rows).effective).toBe(1);
    // authority=openshell 不会被升级为 effective
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, authority: 'openshell' })[0].state).toBe('declared');
    // 状态解释不含「阻断已验证」之类结论
    for (const state of PERMISSION_FACT_STATES) {
      expect(permissionStateExplanation(state)).not.toContain('阻断已验证');
    }
  });
});

describe('组合筛选', () => {
  const rows = [
    fact({ id: 'a', authority: 'openshell', state: 'effective', domain: 'network', subject_id: 'agent-1', action: 'http.request', resource_value: 'api.example.com:443' }),
    fact({ id: 'b', authority: 'siq-iam', state: 'declared', domain: 'filesystem', subject_id: 'agent-2', action: 'fs.write', resource_value: '/var/data' }),
    fact({ id: 'c', authority: 'openshell', state: 'declared', domain: 'network', subject_id: 'agent-1', action: 'http.request', resource_value: 'internal:8080' }),
  ];

  it('authority/state/domain/搜索 AND 组合', () => {
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, authority: 'openshell' })).toHaveLength(2);
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, authority: 'openshell', state: 'declared' })).toHaveLength(1);
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, authority: 'openshell', state: 'declared', domain: 'network' })).toHaveLength(1);
    expect(
      filterPermissionFacts(rows, { authority: 'openshell', state: 'declared', domain: 'network', query: 'internal' }),
    ).toHaveLength(1);
    // 组合矛盾 → 无匹配
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, authority: 'openshell', state: 'observed' })).toHaveLength(0);
  });

  it('文本搜索覆盖主体 ID、动作、资源、来源（大小写不敏感）', () => {
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, query: 'AGENT-2' }).map((r) => r.id)).toEqual(['b']);
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, query: 'fs.write' }).map((r) => r.id)).toEqual(['b']);
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, query: 'example.com' }).map((r) => r.id)).toEqual(['a']);
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, query: 'siq-iam' }).map((r) => r.id)).toEqual(['b']);
  });

  it('空列表与无匹配项均可区分', () => {
    expect(filterPermissionFacts([], EMPTY_FILTERS)).toEqual([]);
    expect(filterPermissionFacts(rows, { ...EMPTY_FILTERS, query: '不存在' })).toEqual([]);
  });

  it('hasActiveFilters 识别清除状态；不修改输入数组与后端 state', () => {
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false);
    expect(hasActiveFilters({ ...EMPTY_FILTERS, query: '  ' })).toBe(false);
    expect(hasActiveFilters({ ...EMPTY_FILTERS, domain: 'network' })).toBe(true);
    const before = rows.map((r) => ({ ...r }));
    const out = filterPermissionFacts(rows, { ...EMPTY_FILTERS, state: 'declared' });
    expect(out).not.toBe(rows);
    expect(rows).toEqual(before);
    expect(rows.every((r, i) => r.state === before[i].state)).toBe(true);
  });

  it('listAuthorities/listDomains 只枚举已加载记录', () => {
    expect(listAuthorities(rows)).toEqual(['openshell', 'siq-iam']);
    expect(listDomains(rows)).toEqual(['filesystem', 'network']);
  });
});

describe('有效期判定', () => {
  it('时间边界相等：now == valid_from 视为已生效；now == valid_until 视为已过期', () => {
    const row = fact({ valid_from: '2026-09-25T12:00:00Z', valid_until: '2026-09-26T12:00:00Z' });
    expect(assessValidity(row, NOW).kind).toBe('within');
    const atUntil = fact({ valid_from: '2026-09-24T00:00:00Z', valid_until: '2026-09-25T12:00:00Z' });
    expect(assessValidity(atUntil, NOW).kind).toBe('expired');
  });

  it('未来生效与已过期', () => {
    expect(assessValidity(fact({ valid_from: '2026-09-26T00:00:00Z' }), NOW).kind).toBe('pending');
    const expired = assessValidity(fact({ valid_until: '2026-09-25T11:59:59Z' }), NOW);
    expect(expired.kind).toBe('expired');
    expect(expired.message).toContain('按当前设备时间判断');
  });

  it('带时区偏移的日期按时间戳比较', () => {
    // 2026-09-25T14:00:00+02:00 == 2026-09-25T12:00:00Z
    const row = fact({ valid_from: '2026-09-25T14:00:00+02:00', valid_until: '2026-09-25T16:00:00+02:00' });
    expect(assessValidity(row, NOW).kind).toBe('within');
    expect(assessValidity(row, Date.parse('2026-09-25T14:00:01Z')).kind).toBe('expired');
  });

  it('无效日期与起止矛盾判定为异常', () => {
    expect(assessValidity(fact({ valid_from: 'not-a-date' }), NOW).kind).toBe('invalid');
    expect(assessValidity(fact({ valid_until: '2026-13-99' }), NOW).kind).toBe('invalid');
    const reversed = assessValidity(fact({ valid_from: '2026-09-26T00:00:00Z', valid_until: '2026-09-24T00:00:00Z' }), NOW);
    expect(reversed.kind).toBe('invalid');
    expect(reversed.message).toContain('矛盾');
  });

  it('缺少边界不推断永久有效；区间内不宣称执行端已核验', () => {
    expect(assessValidity(fact({}), NOW).kind).toBe('unbounded');
    expect(assessValidity(fact({ valid_from: '2026-09-01T00:00:00Z' }), NOW).kind).toBe('unbounded');
    expect(assessValidity(fact({ valid_until: '2026-10-01T00:00:00Z' }), NOW).kind).toBe('unbounded');
    const within = assessValidity(fact({ valid_from: '2026-09-01T00:00:00Z', valid_until: '2026-10-01T00:00:00Z' }), NOW);
    expect(within.kind).toBe('within');
    expect(within.message).toContain('不代表当前执行端仍有效或已核验');
  });

  it('判定不修改输入行', () => {
    const row = fact({ valid_from: '2026-09-01T00:00:00Z' });
    const snapshot = { ...row };
    assessValidity(row, NOW);
    expect(row).toEqual(snapshot);
  });
});
