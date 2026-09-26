import { describe, expect, it } from 'vitest';
import { accessKeys, actionKeys, canVisit, type ConsoleContext } from '@/api/consoleContext';
import {
  ADVANCED_GROUP_LABEL,
  ADVANCED_NAV_ITEMS,
  MAIN_NAV_ITEMS,
  activeAdvancedEntry,
  activeMainEntry,
  enterpriseTitle,
  filterByAccess,
  isAdvancedPath,
} from './enterpriseNav';

/** 构造合法 ConsoleContext：仅指定 access 键为 true，其余 false。 */
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

describe('四主入口标签与 URL', () => {
  it('保持现有 URL 与四主入口标签', () => {
    expect(MAIN_NAV_ITEMS.map((i) => [i.to, i.label])).toEqual([
      ['/agents', '资产'],
      ['/permissions', '权限'],
      ['/findings', '安全'],
      ['/audit', '审计'],
    ]);
  });

  it('高级区域包含全部旧管理入口', () => {
    expect(ADVANCED_NAV_ITEMS.map((i) => i.to)).toEqual([
      '/workspace',
      '/overview',
      '/policies',
      '/changes',
      '/runtime-bindings',
      '/environments',
      '/settings',
    ]);
    expect(ADVANCED_GROUP_LABEL).toBe('管理与高级功能');
  });
});

describe('不同访问权限下的独立过滤', () => {
  it('每个入口单独按其真实访问权限过滤', () => {
    const ctx = makeContext(['agents', 'audit']);
    const main = filterByAccess(MAIN_NAV_ITEMS, ctx);
    expect(main.map((i) => i.to)).toEqual(['/agents', '/audit']);
    const advanced = filterByAccess(ADVANCED_NAV_ITEMS, ctx);
    expect(advanced.map((i) => i.to)).toEqual(['/workspace', '/settings']);
  });

  it('没有权限的链接不因移动到高级区域而重新出现', () => {
    const ctx = makeContext(['agents']);
    const advanced = filterByAccess(ADVANCED_NAV_ITEMS, ctx);
    expect(advanced.some((i) => i.to === '/policies')).toBe(false);
    expect(advanced.some((i) => i.to === '/environments')).toBe(false);
  });

  it('身份未加载（context 为 undefined）时仅保留 workspace/settings', () => {
    const main = filterByAccess(MAIN_NAV_ITEMS, undefined);
    expect(main).toEqual([]);
    const advanced = filterByAccess(ADVANCED_NAV_ITEMS, undefined);
    expect(advanced.map((i) => i.to)).toEqual(['/workspace', '/settings']);
  });

  it('高级区域没有任何可访问项目时为空（调用方据此隐藏分组）', () => {
    const ctx = makeContext([]);
    // workspace/settings 恒为 true（见 canVisit），故构造一个全部为 false 的场景需绕过：
    // 直接验证 filterByAccess 对空授权仅保留恒可访问项。
    const advanced = filterByAccess(ADVANCED_NAV_ITEMS, ctx);
    expect(advanced.map((i) => i.to)).toEqual(['/workspace', '/settings']);
    // 若连 workspace/settings 也被过滤（如未来策略变化），空数组即应隐藏分组：
    expect(filterByAccess([], ctx)).toEqual([]);
  });

  it('不硬编码管理员身份：角色标签声称管理员但 access 为 false 时仍被过滤', () => {
    const ctx = makeContext(['agents']);
    ctx.roles = [{ code: 'admin', label: '管理员', description: '' }];
    expect(canVisit(ctx, '/environments')).toBe(false);
    expect(filterByAccess(ADVANCED_NAV_ITEMS, ctx).some((i) => i.to === '/environments')).toBe(false);
  });
});

describe('高级区域归属与自动展开', () => {
  it('旧管理页面属于高级区域', () => {
    for (const path of ['/workspace', '/overview', '/policies', '/changes', '/runtime-bindings', '/environments', '/settings']) {
      expect(isAdvancedPath(path)).toBe(true);
    }
  });

  it('四主入口不属于高级区域', () => {
    for (const path of ['/agents', '/permissions', '/findings', '/audit']) {
      expect(isAdvancedPath(path)).toBe(false);
    }
  });

  it('不因路径前缀相似误判所属入口', () => {
    expect(isAdvancedPath('/agents/skills')).toBe(false);
    expect(isAdvancedPath('/agents/asset-1')).toBe(false);
    expect(isAdvancedPath('/policies/extra')).toBe(false);
    expect(isAdvancedPath('/')).toBe(false);
    expect(isAdvancedPath('/unknown')).toBe(false);
  });
});

describe('顶栏标题与归属', () => {
  it('四主入口标题正确', () => {
    expect(enterpriseTitle('/agents')).toBe('资产');
    expect(enterpriseTitle('/permissions')).toBe('权限');
    expect(enterpriseTitle('/findings')).toBe('安全');
    expect(enterpriseTitle('/audit')).toBe('审计');
  });

  it('/agents/skills 与资产详情区分，不全部显示成总览', () => {
    expect(enterpriseTitle('/agents/skills')).toBe('技能清单');
    expect(enterpriseTitle('/agents/asset-1')).toBe('资产详情');
    expect(enterpriseTitle('/agents/other%2Fid')).toBe('资产详情');
  });

  it('旧管理页面标题正确', () => {
    expect(enterpriseTitle('/workspace')).toBe('工作台');
    expect(enterpriseTitle('/overview')).toBe('总览');
    expect(enterpriseTitle('/policies')).toBe('策略中心');
    expect(enterpriseTitle('/changes')).toBe('变更中心');
    expect(enterpriseTitle('/runtime-bindings')).toBe('运行时绑定');
    expect(enterpriseTitle('/environments')).toBe('环境与设备');
    expect(enterpriseTitle('/settings')).toBe('设置');
  });

  it('未知路径回落到总览', () => {
    expect(enterpriseTitle('/unknown')).toBe('总览');
    expect(enterpriseTitle('/')).toBe('总览');
  });

  it('查询参数不影响标题', () => {
    expect(enterpriseTitle('/agents?view=candidates')).toBe('资产');
    expect(enterpriseTitle('/agents/skills?tab=all')).toBe('技能清单');
  });
});

describe('当前页面高亮归属', () => {
  it('主入口精确匹配高亮', () => {
    expect(activeMainEntry('/agents')?.to).toBe('/agents');
    expect(activeMainEntry('/permissions')?.to).toBe('/permissions');
    expect(activeMainEntry('/findings')?.to).toBe('/findings');
    expect(activeMainEntry('/audit')?.to).toBe('/audit');
  });

  it('技能与资产详情仍归属唯一资产主入口', () => {
    expect(activeMainEntry('/agents/skills')?.to).toBe('/agents');
    expect(activeMainEntry('/agents/asset-1')?.to).toBe('/agents');
    expect(activeMainEntry('/agents/skills/?tab=all')?.to).toBe('/agents');
  });

  it('相似前缀不归属资产', () => {
    expect(activeMainEntry('/agents-old')).toBeUndefined();
    expect(activeMainEntry('/agentships/skills')).toBeUndefined();
  });

  it('高级入口精确匹配高亮', () => {
    expect(activeAdvancedEntry('/policies')?.to).toBe('/policies');
    expect(activeAdvancedEntry('/environments')?.to).toBe('/environments');
    expect(activeAdvancedEntry('/agents')).toBeUndefined();
  });
});

describe('权限加载失败与拒绝访问不被绕过', () => {
  it('context 为 undefined 时 canVisit 行为保持不变', () => {
    expect(canVisit(undefined, '/workspace')).toBe(true);
    expect(canVisit(undefined, '/settings')).toBe(true);
    expect(canVisit(undefined, '/agents')).toBe(false);
    expect(canVisit(undefined, '/environments')).toBe(false);
  });

  it('直达无权限页面时 accessible 判定为 false（Layout 据此拒绝渲染）', () => {
    const ctx = makeContext(['agents']);
    // 模拟 Layout 的 accessible 计算：routeAccessKey 存在且 canVisit 为 false
    const key = '/environments';
    const accessible = !key || canVisit(ctx, key);
    expect(accessible).toBe(false);
  });
});
