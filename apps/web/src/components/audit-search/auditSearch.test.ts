/**
 * CL-06-AUDIT-CORRELATION-UI：auditFiltersKey / identityKey 无歧义编码定向测试。
 * 负例直接复现旧实现的 A/B 碰撞（值含 &/= 时跨字段歧义），证明新编码消除碰撞。
 */
import { expect, it } from 'vitest';
import {
  EMPTY_AUDIT_FILTERS,
  auditFiltersEqual,
  auditFiltersKey,
  buildAuditQuery,
  identityKey,
  type AuditSearchFilters,
} from './auditSearch';

const A: AuditSearchFilters = {
  ...EMPTY_AUDIT_FILTERS,
  request_id: 'a&resource_id=b',
  resource_id: 'c',
};
const B: AuditSearchFilters = {
  ...EMPTY_AUDIT_FILTERS,
  request_id: 'a',
  resource_id: 'b&resource_id=c',
};

it('旧实现 A/B 碰撞复现：未转义 key=value + & 拼接生成相同 key', () => {
  // 旧表达式（修复前）：AUDIT_FILTER_FIELDS.map(({key}) => `${key}=${filters[key]}`).join('&')
  const fields: (keyof AuditSearchFilters)[] = [
    'request_id', 'resource_id', 'actor_id', 'actor_type', 'action', 'resource_type', 'decision',
  ];
  const legacyKey = (f: AuditSearchFilters) => fields.map((k) => `${k}=${f[k]}`).join('&');
  expect(legacyKey(A)).toBe(legacyKey(B)); // 碰撞成立（缺陷复现）
  expect(auditFiltersEqual(A, B)).toBe(false); // 但条件本身不同
});

it('新 auditFiltersKey：A/B 不同条件生成不同 key', () => {
  expect(auditFiltersKey(A)).not.toBe(auditFiltersKey(B));
});

it('新 auditFiltersKey：相同条件生成相同 key（重复提交不重建组件）', () => {
  expect(auditFiltersKey(A)).toBe(auditFiltersKey({ ...A }));
  expect(auditFiltersKey(EMPTY_AUDIT_FILTERS)).toBe(auditFiltersKey({ ...EMPTY_AUDIT_FILTERS }));
});

it('新 auditFiltersKey：值含 =、&、#、引号、空格、中文、+ 时逐值无歧义', () => {
  const cases: AuditSearchFilters[] = [
    { ...EMPTY_AUDIT_FILTERS, request_id: 'a=b&c#d"e f+中' },
    { ...EMPTY_AUDIT_FILTERS, request_id: 'a=b&c#d"e f+中', resource_id: '' },
    { ...EMPTY_AUDIT_FILTERS, request_id: '', resource_id: 'a=b&c#d"e f+中' },
    { ...EMPTY_AUDIT_FILTERS, request_id: 'x', resource_id: 'x' },
    { ...EMPTY_AUDIT_FILTERS, request_id: 'x', resource_id: 'y' },
  ];
  const keys = cases.map(auditFiltersKey);
  // 除第 1/2 项（仅空字段位置不同但值相同 → 条件相等）外，其余必须两两不同
  expect(auditFiltersEqual(cases[0], cases[1])).toBe(true);
  expect(keys[0]).toBe(keys[1]);
  for (let i = 0; i < cases.length; i += 1) {
    for (let j = i + 1; j < cases.length; j += 1) {
      if (auditFiltersEqual(cases[i], cases[j])) {
        expect(keys[i]).toBe(keys[j]);
      } else {
        expect(keys[i]).not.toBe(keys[j]);
      }
    }
  }
});

it('identityKey：# 分隔符碰撞被消除，相同身份保持相同 key', () => {
  // 旧表达式 t#a 的碰撞对
  expect(identityKey('t#1', 'a')).not.toBe(identityKey('t', '1#a'));
  expect(identityKey('t', 'a')).toBe(identityKey('t', 'a'));
  expect(identityKey('t', 'a')).not.toBe(identityKey('t', 'b'));
  expect(identityKey('t', 'a')).not.toBe(identityKey('t2', 'a'));
  // 组合键（身份 + 查询）不再依赖分隔符拼接：身份不同 → 组合不同
  const combined = (t: string, a: string, f: AuditSearchFilters) =>
    `${identityKey(t, a)}|${auditFiltersKey(f)}`;
  expect(combined('t#1', 'a', EMPTY_AUDIT_FILTERS)).not.toBe(combined('t', '1#a', EMPTY_AUDIT_FILTERS));
});

it('buildAuditQuery 原值往返：不 trim、不改大小写、不截断，空串省略', () => {
  const filters: AuditSearchFilters = {
    ...EMPTY_AUDIT_FILTERS,
    request_id: '  Req-8F2A & + # "引号" 中文 ',
    resource_id: 'res',
  };
  const query = buildAuditQuery(filters);
  expect(query.request_id).toBe('  Req-8F2A & + # "引号" 中文 ');
  expect(query.resource_id).toBe('res');
  expect('actor_id' in query).toBe(false);
  expect('actor_type' in query).toBe(false);
  expect('action' in query).toBe(false);
  expect('resource_type' in query).toBe(false);
  expect('decision' in query).toBe(false);
});
