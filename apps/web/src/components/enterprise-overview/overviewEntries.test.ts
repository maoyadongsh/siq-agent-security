import { describe, expect, it } from 'vitest';
import { accessKeys, actionKeys, canVisit, type ConsoleContext } from '@/api/consoleContext';
import {
  MAIN_ENTRIES,
  SECONDARY_ENTRIES,
  SECONDARY_GROUP_LABEL,
  filterEntries,
} from './overviewEntries';

function makeContext(granted: string[]): ConsoleContext {
  return {
    schema_version: 'console-context/v1',
    evaluated_at: '2026-09-25T01:00:00Z',
    tenant: { id: 't1', name: '组织一' },
    actor: { id: 'u1', type: 'user' },
    authentication: 'verified_token',
    roles: [{ code: 'viewer', label: '只读查看者', description: '只读' }],
    custom_role_count: 0,
    access: Object.fromEntries(accessKeys.map((k) => [k, granted.includes(k)])) as ConsoleContext['access'],
    actions: Object.fromEntries(actionKeys.map((k) => [k, false])) as ConsoleContext['actions'],
  };
}

describe('四主入口标签、URL 与顺序', () => {
  it('顺序固定且保持原 URL', () => {
    expect(MAIN_ENTRIES.map((e) => [e.to, e.title])).toEqual([
      ['/agents', '资产'],
      ['/permissions', '权限'],
      ['/findings', '安全'],
      ['/audit', '审计'],
    ]);
  });

  it('说明文字不含无证据的承诺', () => {
    for (const entry of MAIN_ENTRIES) {
      expect(entry.desc).not.toMatch(/已全面保护|自动完成隔离|已受保护/);
    }
  });
});

describe('次级入口保留', () => {
  it('策略中心与变更中心保留在次级区域', () => {
    expect(SECONDARY_ENTRIES.map((e) => [e.to, e.title])).toEqual([
      ['/policies', '策略中心'],
      ['/changes', '变更中心'],
    ]);
    expect(SECONDARY_GROUP_LABEL).toBe('管理与高级功能');
  });
});

describe('逐项权限过滤与空分组隐藏', () => {
  it('每个链接独立按其真实访问权限过滤', () => {
    const ctx = makeContext(['agents', 'audit', 'policies']);
    expect(filterEntries(MAIN_ENTRIES, ctx).map((e) => e.to)).toEqual(['/agents', '/audit']);
    expect(filterEntries(SECONDARY_ENTRIES, ctx).map((e) => e.to)).toEqual(['/policies']);
  });

  it('无权限入口被过滤，不因移动到次级区域而重新出现', () => {
    const ctx = makeContext(['agents']);
    expect(filterEntries(SECONDARY_ENTRIES, ctx).some((e) => e.to === '/changes')).toBe(false);
  });

  it('身份未加载（context 为 undefined）时不假设权限通过', () => {
    expect(filterEntries(MAIN_ENTRIES, undefined)).toEqual([]);
    // workspace/settings 恒可访问，但主/次级入口均不含它们，故全空
    expect(filterEntries(SECONDARY_ENTRIES, undefined)).toEqual([]);
  });

  it('没有任何可访问项目时返回空数组（调用方据此隐藏分组）', () => {
    const ctx = makeContext([]);
    expect(filterEntries(MAIN_ENTRIES, ctx)).toEqual([]);
    expect(filterEntries(SECONDARY_ENTRIES, ctx)).toEqual([]);
  });
});

describe('管理员角色名称不覆盖实际权限', () => {
  it('角色标签声称管理员但 access 为 false 时仍被过滤', () => {
    const ctx = makeContext(['agents']);
    ctx.roles = [{ code: 'admin', label: '管理员', description: '' }];
    expect(canVisit(ctx, '/findings')).toBe(false);
    expect(filterEntries(MAIN_ENTRIES, ctx).some((e) => e.to === '/findings')).toBe(false);
    expect(filterEntries(SECONDARY_ENTRIES, ctx).some((e) => e.to === '/policies')).toBe(false);
  });
});
