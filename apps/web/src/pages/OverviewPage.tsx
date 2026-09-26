/**
 * 总览（§20.1）：真实 /overview 统计 + 快速入口。
 * ENT-018-OVERVIEW：四主入口（资产/权限/安全/审计）顺序固定；策略/变更收进
 * 默认折叠的"管理与高级功能"；统计区分 加载中/真实 0/失败/缺失异常值，
 * 缺失或异常数值不冒充 0。断连保持空态降级，不阻塞其余页面。
 */
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import { Icon, type IconName } from '@/components/icons';
import { api, ApiError } from '@/api/client';
import { useConsoleContext } from '@/components/ConsoleContext';
import type { OverviewStats } from '@/api/types';
import {
  HEARTBEAT_BOUNDARY_NOTE,
  OVERVIEW_STAT_KEYS,
  hasInvalidStat,
  isSafeCount,
  statDisplayValue,
  type OverviewStatKey,
} from '@/components/enterprise-overview/overviewStats';
import {
  MAIN_ENTRIES,
  SECONDARY_ENTRIES,
  SECONDARY_GROUP_LABEL,
  filterEntries,
  type OverviewEntry,
} from '@/components/enterprise-overview/overviewEntries';
import '@/components/enterprise-overview/overview.css';

/** 指标卡色调：neutral 常规；ok/warn/err 语义强调（风险类指标为 0 时保持安静的中性色） */
type StatTone = 'neutral' | 'primary' | 'ok' | 'warn' | 'err';

interface StatCardDef {
  key: OverviewStatKey;
  label: string;
  icon: IconName;
  tone: (value: number | undefined) => StatTone;
}

const STAT_CARDS: StatCardDef[] = [
  { key: 'agents', label: '已确认及纳管资产', icon: 'agents', tone: () => 'primary' },
  { key: 'candidates', label: '待评审候选', icon: 'scan', tone: (v) => (v !== undefined && v > 0 ? 'warn' : 'neutral') },
  { key: 'open_findings', label: '未处置风险', icon: 'findings', tone: (v) => (v !== undefined && v > 0 ? 'warn' : 'neutral') },
  { key: 'critical_findings', label: '高危风险', icon: 'shield-alert', tone: (v) => (v !== undefined && v > 0 ? 'err' : 'neutral') },
  { key: 'environments', label: '环境', icon: 'environments', tone: () => 'neutral' },
  { key: 'edges_online', label: '心跳正常的设备', icon: 'activity', tone: (v) => (v !== undefined && v > 0 ? 'ok' : 'neutral') },
  { key: 'policies', label: '策略', icon: 'policies', tone: () => 'neutral' },
];

function QuickTileLink({ entry }: { entry: OverviewEntry }) {
  return (
    <Link to={entry.to} className="quick-tile">
      <span className="quick-tile-icon">
        <Icon name={entry.icon} size={18} />
      </span>
      <span className="quick-tile-text">
        <span className="quick-tile-title">{entry.title}</span>
        <span className="quick-tile-desc" title={entry.desc}>{entry.desc}</span>
      </span>
      <span className="quick-tile-arrow">
        <Icon name="chevron-right" size={16} />
      </span>
    </Link>
  );
}

export default function OverviewPage() {
  const { data: context } = useConsoleContext();
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const requestSeq = useRef(0);

  const load = () => {
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    api
      .overview()
      .then((data) => {
        if (seq !== requestSeq.current) return;
        if (data === null || typeof data !== 'object' || Array.isArray(data)) {
          setStats(null);
          setError('统计响应格式异常，请重试');
          setLoading(false);
          return;
        }
        setStats(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (seq !== requestSeq.current) return;
        setStats(null);
        setError(err instanceof ApiError ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
    return () => {
      requestSeq.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const failed = error !== null;
  const invalid = hasInvalidStat(stats);
  const mainEntries = filterEntries(MAIN_ENTRIES, context);
  const secondaryEntries = filterEntries(SECONDARY_ENTRIES, context);

  return (
    <section>
      <PageHeader
        icon="overview"
        title="总览"
        description="资产、权限、安全与审计的统一入口；策略与变更在下方高级区域。"
        connection={loading ? 'loading' : failed ? 'disconnected' : 'connected'}
        connectionError={error}
      />

      {failed ? (
        <DisconnectedNotice error={error} onRetry={load} />
      ) : (
        <>
          <div className="stats-grid">
            {STAT_CARDS.map((c) => {
              const value = statDisplayValue(stats, c.key);
              return (
                <div className="stat-card" key={c.key}>
                  <div className="stat-head">
                    <span className={`stat-icon tone-${c.tone(value)}`}>
                      <Icon name={c.icon} size={16} />
                    </span>
                    <span className="stat-label">{c.label}</span>
                  </div>
                  <div className={`stat-value tone-${c.tone(value)}`}>
                    {loading ? (
                      <span className="entoverview-value-loading" role="status">加载中…</span>
                    ) : value === undefined ? (
                      <span className="entoverview-value-unknown" title="响应未提供有效数值">未知/未提供</span>
                    ) : (
                      String(value)
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {invalid ? (
            <p className="entoverview-stat-note" role="alert">
              部分统计数值缺失或异常（{OVERVIEW_STAT_KEYS.filter((k) => !isSafeCount(stats?.[k])).join('、')}），
              已显示为"未知/未提供"，不代表真实零值。
            </p>
          ) : null}
          <p className="entoverview-boundary">{HEARTBEAT_BOUNDARY_NOTE}</p>
        </>
      )}

      <div className="card">
        <h2>快速入口</h2>
        {mainEntries.length > 0 ? (
          <div className="quick-grid">
            {mainEntries.map((entry) => (
              <QuickTileLink key={entry.to} entry={entry} />
            ))}
          </div>
        ) : null}
        {secondaryEntries.length > 0 ? (
          <details className="entoverview-secondary">
            <summary>
              <span className="entoverview-secondary-chevron" aria-hidden="true">
                <Icon name="chevron-right" size={14} />
              </span>
              {SECONDARY_GROUP_LABEL}
            </summary>
            <div className="entoverview-secondary-grid">
              {secondaryEntries.map((entry) => (
                <QuickTileLink key={entry.to} entry={entry} />
              ))}
            </div>
          </details>
        ) : null}
      </div>
    </section>
  );
}
