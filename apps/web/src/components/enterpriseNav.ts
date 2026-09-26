/** 企业端导航定义与纯函数（ENT-018 导航简化子任务）。
 * 四主入口 + 次级"管理与高级功能"分组；标题/归属/权限过滤均为纯函数，可独立测试。
 * 不修改业务权限、安全判断或后端接口；权限过滤复用 canVisit / routeAccessKey。 */
import type { IconName } from '@/components/icons';
import { canVisit, type ConsoleContext } from '@/api/consoleContext';

export interface EnterpriseNavItem {
  to: string;
  label: string;
  icon: IconName;
}

/** 四主入口（保持现有 URL 与权限键）。 */
export const MAIN_NAV_ITEMS: readonly EnterpriseNavItem[] = [
  { to: '/agents', label: '资产', icon: 'agents' },
  { to: '/permissions', label: '权限', icon: 'permissions' },
  { to: '/findings', label: '安全', icon: 'findings' },
  { to: '/audit', label: '审计', icon: 'audit' },
] as const;

/** 次级"管理与高级功能"（默认折叠；折叠不是删除功能）。 */
export const ADVANCED_NAV_ITEMS: readonly EnterpriseNavItem[] = [
  { to: '/workspace', label: '工作台', icon: 'overview' },
  { to: '/overview', label: '总览', icon: 'overview' },
  { to: '/policies', label: '策略中心', icon: 'policies' },
  { to: '/changes', label: '变更中心', icon: 'changes' },
  { to: '/runtime-bindings', label: '运行时绑定', icon: 'bindings' },
  { to: '/environments', label: '环境与设备', icon: 'environments' },
  { to: '/settings', label: '设置', icon: 'settings' },
] as const;

export const ADVANCED_GROUP_LABEL = '管理与高级功能';

/** 每个入口单独按其真实访问权限过滤（复用 canVisit / routeAccessKey）。 */
export function filterByAccess(
  items: readonly EnterpriseNavItem[],
  context: ConsoleContext | undefined,
): EnterpriseNavItem[] {
  return items.filter((item) => canVisit(context, item.to));
}

/** 当前路径是否属于高级区域（用于自动展开，不改变浏览器 URL）。 */
export function isAdvancedPath(pathname: string): boolean {
  const clean = pathname.split('?')[0].replace(/\/+$/, '') || '/';
  return ADVANCED_NAV_ITEMS.some((item) => item.to === clean);
}

/** 资产子页面归属资产；其余入口精确匹配，避免相似前缀误判。 */
export function activeMainEntry(pathname: string): EnterpriseNavItem | undefined {
  const clean = pathname.split('?')[0].replace(/\/+$/, '');
  return MAIN_NAV_ITEMS.find((item) => item.to === clean ||
    (item.to === '/agents' && clean.startsWith('/agents/')));
}

/** 当前路径归属的高级入口（精确匹配）。 */
export function activeAdvancedEntry(pathname: string): EnterpriseNavItem | undefined {
  const clean = pathname.split('?')[0];
  return ADVANCED_NAV_ITEMS.find((item) => item.to === clean);
}

/** 顶栏标题：区分技能清单与资产详情，旧管理页面回落到所属列表页。
 * /agents/skills → 技能清单；/agents/:id → 资产详情；其余详情页回落到所属主/高级入口。 */
export function enterpriseTitle(pathname: string): string {
  const clean = pathname.split('?')[0].replace(/\/+$/, '');
  if (clean === '/agents/skills') return '技能清单';
  if (clean.startsWith('/agents/')) return '资产详情';
  const main = activeMainEntry(clean);
  if (main) return main.label;
  const advanced = activeAdvancedEntry(clean);
  if (advanced) return advanced.label;
  return '总览';
}
