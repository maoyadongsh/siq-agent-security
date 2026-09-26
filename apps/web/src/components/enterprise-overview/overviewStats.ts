/** 企业总览统计校验纯函数（ENT-018-OVERVIEW）。
 * 区分：加载中 / 真实 0 / 请求失败 / 缺失或异常数值。
 * 缺失、负值、非数字等异常值不得静默转成 0（不得用 ?? 0 冒充真实零值）。 */
import type { OverviewStats } from '@/api/types';

export const OVERVIEW_STAT_KEYS = [
  'agents',
  'candidates',
  'open_findings',
  'critical_findings',
  'environments',
  'edges_online',
  'policies',
] as const;

export type OverviewStatKey = (typeof OVERVIEW_STAT_KEYS)[number];

/** 有效计数：非负安全整数。 */
export function isSafeCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

/** 单项统计展示值：有效计数原样返回；缺失/负值/非数字返回 undefined（UI 显示"未知/未提供"）。 */
export function statDisplayValue(stats: OverviewStats | null, key: OverviewStatKey): number | undefined {
  if (!stats) return undefined;
  const value = stats[key];
  return isSafeCount(value) ? value : undefined;
}

/** 响应整体是否异常（存在缺失或非法字段）：用于"响应异常"提示，不冒充空清单。 */
export function hasInvalidStat(stats: OverviewStats | null): boolean {
  if (!stats) return false;
  return OVERVIEW_STAT_KEYS.some((key) => !isSafeCount(stats[key]));
}

/** 统计请求状态：加载中 / 成功（含真实 0）/ 失败。 */
export type StatsPhase = 'loading' | 'ready' | 'error';

/** 心跳正常不等于已完成盘点或运行时防护已核验（边界说明文案）。 */
export const HEARTBEAT_BOUNDARY_NOTE = '设备心跳正常不等于已完成盘点或运行时防护已核验。';

/** 风险零值语义：真实 0 只表示当前计数为 0，不解释为"没有风险"或"已安全"。 */
export const ZERO_COUNT_NOTE = '计数为 0 仅表示当前统计值为零，不代表系统已处于受保护状态。';
