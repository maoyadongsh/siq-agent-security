/** 企业总览快捷入口定义与纯函数（ENT-018-OVERVIEW）。
 * 四主入口（资产/权限/安全/审计）顺序固定、保持原 URL；
 * 策略中心/变更中心收进次级"管理与高级功能"。
 * 每个链接独立按 canVisit(context, 实际路径) 过滤；不依靠角色名称、不硬编码管理员。 */
import type { IconName } from '@/components/icons';
import { canVisit, type ConsoleContext } from '@/api/consoleContext';

export interface OverviewEntry {
  to: string;
  title: string;
  desc: string;
  icon: IconName;
}

/** 四主入口：顺序固定，说明文字符合实际能力，不含无证据的承诺。
 * "安全"仅为功能入口名称，不表示当前系统已受保护。 */
export const MAIN_ENTRIES: readonly OverviewEntry[] = [
  { to: '/agents', title: '资产', desc: '查看发现候选与已纳管资产', icon: 'agents' },
  { to: '/permissions', title: '权限', desc: '查看权限事实与来源', icon: 'permissions' },
  { to: '/findings', title: '安全', desc: '查看风险与处置记录', icon: 'findings' },
  { to: '/audit', title: '审计', desc: '查看事件与溯源记录', icon: 'audit' },
] as const;

/** 次级管理入口（默认折叠在"管理与高级功能"内）。 */
export const SECONDARY_ENTRIES: readonly OverviewEntry[] = [
  { to: '/policies', title: '策略中心', desc: '期望策略管理', icon: 'policies' },
  { to: '/changes', title: '变更中心', desc: '审批与变更状态', icon: 'changes' },
] as const;

export const SECONDARY_GROUP_LABEL = '管理与高级功能';

/** 每个链接独立按其真实访问权限过滤（复用 canVisit / routeAccessKey）。 */
export function filterEntries(
  entries: readonly OverviewEntry[],
  context: ConsoleContext | undefined,
): OverviewEntry[] {
  return entries.filter((entry) => canVisit(context, entry.to));
}
