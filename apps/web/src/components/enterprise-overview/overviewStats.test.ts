import { describe, expect, it } from 'vitest';
import type { OverviewStats } from '@/api/types';
import {
  OVERVIEW_STAT_KEYS,
  hasInvalidStat,
  isSafeCount,
  statDisplayValue,
} from './overviewStats';

function stats(overrides: Partial<OverviewStats> = {}): OverviewStats {
  return {
    agents: 0,
    candidates: 0,
    open_findings: 0,
    critical_findings: 0,
    environments: 0,
    edges_online: 0,
    policies: 0,
    ...overrides,
  };
}

describe('isSafeCount', () => {
  it('接受非负安全整数', () => {
    expect(isSafeCount(0)).toBe(true);
    expect(isSafeCount(1)).toBe(true);
    expect(isSafeCount(123456)).toBe(true);
  });

  it('拒绝负值、非整数、非数字、缺失', () => {
    expect(isSafeCount(-1)).toBe(false);
    expect(isSafeCount(1.5)).toBe(false);
    expect(isSafeCount(NaN)).toBe(false);
    expect(isSafeCount(Infinity)).toBe(false);
    expect(isSafeCount('3')).toBe(false);
    expect(isSafeCount(null)).toBe(false);
    expect(isSafeCount(undefined)).toBe(false);
  });
});

describe('statDisplayValue', () => {
  it('stats 为 null（加载中/失败）返回 undefined', () => {
    expect(statDisplayValue(null, 'agents')).toBeUndefined();
  });

  it('真实 0 返回 0（不冒充缺失）', () => {
    expect(statDisplayValue(stats(), 'agents')).toBe(0);
    expect(statDisplayValue(stats(), 'critical_findings')).toBe(0);
  });

  it('正整数原样返回', () => {
    expect(statDisplayValue(stats({ agents: 5 }), 'agents')).toBe(5);
  });

  it('缺失/负值/非数字返回 undefined（UI 显示未知/未提供，不转 0）', () => {
    const missing = stats() as OverviewStats;
    delete (missing as unknown as Record<string, unknown>).agents;
    expect(statDisplayValue(missing, 'agents')).toBeUndefined();

    expect(statDisplayValue(stats({ agents: -3 }), 'agents')).toBeUndefined();
    expect(statDisplayValue(stats({ agents: 1.5 }), 'agents')).toBeUndefined();
    expect(statDisplayValue(stats({ agents: Number.NaN }), 'agents')).toBeUndefined();
    expect(statDisplayValue(stats({ agents: '7' as unknown as number }), 'agents')).toBeUndefined();
  });
});

describe('hasInvalidStat', () => {
  it('全部有效（含真实 0）为 false', () => {
    expect(hasInvalidStat(stats())).toBe(false);
    expect(hasInvalidStat(stats({ agents: 3, open_findings: 2 }))).toBe(false);
  });

  it('存在缺失/负值/非数字为 true', () => {
    const missing = stats() as OverviewStats;
    delete (missing as unknown as Record<string, unknown>).policies;
    expect(hasInvalidStat(missing)).toBe(true);
    expect(hasInvalidStat(stats({ edges_online: -1 }))).toBe(true);
    expect(hasInvalidStat(stats({ environments: 2.5 }))).toBe(true);
  });

  it('stats 为 null 为 false（无响应可判）', () => {
    expect(hasInvalidStat(null)).toBe(false);
  });
});

describe('统计键完整性', () => {
  it('保留既有七项统计', () => {
    expect(OVERVIEW_STAT_KEYS).toEqual([
      'agents',
      'candidates',
      'open_findings',
      'critical_findings',
      'environments',
      'edges_online',
      'policies',
    ]);
  });
});
