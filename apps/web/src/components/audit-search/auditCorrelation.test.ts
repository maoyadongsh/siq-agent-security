/**
 * CL-06-AUDIT-CORRELATION-UI：关联操作纯函数定向测试。
 * 覆盖：准确参数、清空其余条件、特殊字符原值、缺失/超长/异常值无动作。
 */
import { expect, it } from 'vitest';
import type { AuditEvent } from '@/api/types';
import { EMPTY_AUDIT_FILTERS, auditFiltersEqual } from './auditSearch';
import { auditCorrelationActions, auditCorrelationFilters } from './auditCorrelation';

function event(overrides: Partial<AuditEvent>): AuditEvent {
  return {
    id: 'aud-1',
    actor_type: 'user',
    actor_id: 'u-1',
    action: 'agent.confirm',
    resource_type: 'agent_asset',
    resource_id: 'agt-1',
    decision: 'allow',
    request_id: 'req-1',
    summary: {},
    created_at: '2026-09-26T00:00:00Z',
    ...overrides,
  };
}

it('查询同请求：只保留该行 request_id，其余六字段为空，原值逐字保留', () => {
  const e = event({ request_id: '  Req-8F2A & + # "引号" 中文 ' });
  const filters = auditCorrelationFilters(e, 'request');
  expect(filters).not.toBeNull();
  expect(filters!.request_id).toBe('  Req-8F2A & + # "引号" 中文 ');
  const others = ['resource_id', 'actor_id', 'actor_type', 'action', 'resource_type', 'decision'] as const;
  for (const key of others) expect(filters![key]).toBe('');
  expect(auditFiltersEqual(filters!, { ...EMPTY_AUDIT_FILTERS, request_id: e.request_id! })).toBe(true);
});

it('查询同对象：resource_type + resource_id 一起查询，其余五字段为空', () => {
  const e = event({ resource_type: 'environment', resource_id: 'env-dev-docker' });
  const filters = auditCorrelationFilters(e, 'resource');
  expect(filters).not.toBeNull();
  expect(filters!.resource_type).toBe('environment');
  expect(filters!.resource_id).toBe('env-dev-docker');
  const others = ['request_id', 'actor_id', 'actor_type', 'action', 'decision'] as const;
  for (const key of others) expect(filters![key]).toBe('');
});

it('缺失/空值/异常类型/超长值不生成可操作按钮', () => {
  // request_id 缺失
  expect(auditCorrelationFilters(event({ request_id: null }), 'request')).toBeNull();
  // request_id 空串
  expect(auditCorrelationFilters(event({ request_id: '' }), 'request')).toBeNull();
  // 异常类型（数字）
  expect(auditCorrelationFilters(event({ request_id: 42 as unknown as string }), 'request')).toBeNull();
  // 超长（65 码点 > 64）
  expect(auditCorrelationFilters(event({ request_id: 'r'.repeat(65) }), 'request')).toBeNull();
  // resource_id 缺失 → 同对象不可用
  expect(auditCorrelationFilters(event({ resource_id: null }), 'resource')).toBeNull();
  // resource_type 空串 → 同对象不可用（对象类型必须一起查询）
  expect(auditCorrelationFilters(event({ resource_type: '' }), 'resource')).toBeNull();
  // resource_id 超长
  expect(auditCorrelationFilters(event({ resource_id: 'r'.repeat(65) }), 'resource')).toBeNull();
  // resource_type 超长（33 码点 > 32）
  expect(auditCorrelationFilters(event({ resource_type: 't'.repeat(33) }), 'resource')).toBeNull();
  // 全部不可用 → 空列表
  expect(auditCorrelationActions(event({ request_id: null, resource_id: null }))).toEqual([]);
});

it('边界长度（恰好 64/32 码点）可用；含 emoji 按码点计长', () => {
  const e = event({ request_id: 'r'.repeat(64), resource_type: 't'.repeat(32), resource_id: 'i'.repeat(64) });
  expect(auditCorrelationFilters(e, 'request')).not.toBeNull();
  expect(auditCorrelationFilters(e, 'resource')).not.toBeNull();
  // emoji 占 2 码点：63 个 r + 1 个 emoji = 64 码点，仍可用
  const emoji = event({ request_id: 'r'.repeat(63) + '😀' });
  expect(auditCorrelationFilters(emoji, 'request')).not.toBeNull();
  const over = event({ request_id: 'r'.repeat(64) + '😀' });
  expect(auditCorrelationFilters(over, 'request')).toBeNull();
});

it('可访问名称包含行标识，能区分操作及所选行', () => {
  const e = event({ request_id: 'req-8f2a', resource_type: 'agent_asset', resource_id: 'agt-1' });
  const actions = auditCorrelationActions(e);
  expect(actions.map((a) => a.accessibleName)).toEqual([
    '查询同请求：req-8f2a',
    '查询同对象：agent_asset:agt-1',
  ]);
});
