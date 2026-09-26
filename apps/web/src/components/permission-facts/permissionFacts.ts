/**
 * ENT-014-UI：权限事实展示的纯函数层。
 * 语义边界（不得在此之外解读）：
 * - declared 只是声明允许，不代表实际使用；
 * - effective 是后端记录的事实层级，不代表已通过行为阻断验证；
 * - authority（如 openshell）与 state 互不推导；
 * - 统计只覆盖「已加载记录」，不是组织全量；
 * - 有效期判定以显式 now 参数（调用方传入当前设备时间）比较时间戳，
 *   不等于服务端核验，缺少边界不推断永久有效。
 */

import type { PermissionFactRow } from '@/api/types';

export const PERMISSION_FACT_STATES = ['declared', 'inferred', 'observed', 'effective', 'unknown'] as const;

/** 五类事实状态的中文解释（展示层补充，不改变后端 state）。 */
export const PERMISSION_STATE_EXPLANATIONS: Record<string, string> = {
  declared: '仅声明或配置允许，不代表实际使用，也不代表运行时已被执行端强制',
  inferred: '由系统根据其他事实推断，未经直接声明或运行观察确认',
  observed: '运行时被观察到使用，但不等于被策略允许或已完成阻断验证',
  effective: '后端记录为有效权限；不表示已通过行为阻断验证，仍需核对有效期与来源',
  unknown: '状态未知、缺少足够信息，不得视为已生效',
};

export function permissionStateExplanation(state: string): string {
  return Object.hasOwn(PERMISSION_STATE_EXPLANATIONS, state)
    ? PERMISSION_STATE_EXPLANATIONS[state] : '未识别的事实状态，不得视为已生效';
}

/** 五态计数（仅针对传入的已加载记录；不修改输入）。五个键始终存在。 */
export function countByState(rows: readonly PermissionFactRow[]): Record<string, number> {
  const counts: Record<string, number> = { declared: 0, inferred: 0, observed: 0, effective: 0, unknown: 0 };
  for (const row of rows) {
    if (Object.hasOwn(counts, row.state)) {
      counts[row.state] += 1;
    } else {
      counts.unknown += 1;
    }
  }
  return counts;
}

function distinctSorted(values: Iterable<string>): string[] {
  return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b));
}

/** 已加载记录中出现的权威来源（供筛选；不推导 state）。 */
export function listAuthorities(rows: readonly PermissionFactRow[]): string[] {
  return distinctSorted(rows.map((row) => row.authority));
}

/** 已加载记录中出现的权限域（原始值，展示层再映射中文名）。 */
export function listDomains(rows: readonly PermissionFactRow[]): string[] {
  return distinctSorted(rows.map((row) => row.domain));
}

export interface PermissionFactFilters {
  /** 空串表示不筛选 */
  authority: string;
  state: string;
  domain: string;
  /** 文本搜索：已加载记录的主体 ID、动作、资源（类型/值）、来源 */
  query: string;
}

export const EMPTY_FILTERS: PermissionFactFilters = { authority: '', state: '', domain: '', query: '' };

export function hasActiveFilters(filters: PermissionFactFilters): boolean {
  return Boolean(filters.authority || filters.state || filters.domain || filters.query.trim());
}

function matchesQuery(row: PermissionFactRow, query: string): boolean {
  const haystack = [row.subject_id, row.action, row.resource_type, row.resource_value, row.authority]
    .join('\n')
    .toLowerCase();
  return haystack.includes(query);
}

/**
 * AND 组合筛选（authority/state/domain/query 同时满足）。
 * 只覆盖传入的已加载记录；返回新数组，不修改输入，不改动任何后端字段。
 */
export function filterPermissionFacts(
  rows: readonly PermissionFactRow[],
  filters: PermissionFactFilters,
): PermissionFactRow[] {
  const query = filters.query.trim().toLowerCase();
  return rows.filter((row) => {
    if (filters.authority && row.authority !== filters.authority) return false;
    if (filters.state && row.state !== filters.state) return false;
    if (filters.domain && row.domain !== filters.domain) return false;
    if (query && !matchesQuery(row, query)) return false;
    return true;
  });
}

export type ValidityKind = 'pending' | 'expired' | 'invalid' | 'unbounded' | 'within';

export interface ValidityAssessment {
  kind: ValidityKind;
  /** 用户可见文案（含「按当前设备时间判断」边界说明） */
  message: string;
  tone: 'warn' | 'err' | 'neutral';
}

function parseBoundary(value: string | null): number | null | 'invalid' {
  if (value == null || value.trim() === '') return null;
  const ts = Date.parse(value);
  return Number.isNaN(ts) ? 'invalid' : ts;
}

const DEVICE_TIME_NOTE = '（按当前设备时间判断，未经服务端核验）';

/**
 * 有效期展示判定。now 为显式传入的当前设备时间戳（毫秒），便于确定性测试。
 * 只产生展示提示，不修改后端 state；在区间内不代表执行端仍有效或已核验。
 */
export function assessValidity(row: PermissionFactRow, now: number): ValidityAssessment {
  const from = parseBoundary(row.valid_from);
  const until = parseBoundary(row.valid_until);

  if (from === 'invalid' || until === 'invalid') {
    return { kind: 'invalid', message: '有效期信息异常：日期格式无效', tone: 'err' };
  }
  if (from != null && until != null && from > until) {
    return { kind: 'invalid', message: '有效期信息异常：起止时间矛盾（生效时间晚于失效时间）', tone: 'err' };
  }
  if (from != null && now < from) {
    return { kind: 'pending', message: `尚未到生效时间${DEVICE_TIME_NOTE}`, tone: 'warn' };
  }
  if (until != null && now >= until) {
    return { kind: 'expired', message: `已过期${DEVICE_TIME_NOTE}`, tone: 'err' };
  }
  if (from == null || until == null) {
    const missing =
      from == null && until == null
        ? '生效与失效时间均未提供'
        : from == null
          ? '生效起始时间未提供'
          : '失效时间未提供';
    return { kind: 'unbounded', message: `${missing}，不推断为永久有效`, tone: 'warn' };
  }
  return {
    kind: 'within',
    message: `在声明的时间区间内${DEVICE_TIME_NOTE}；仅表示时间范围，不代表当前执行端仍有效或已核验`,
    tone: 'neutral',
  };
}
