/**
 * 总览（§20.1）：真实 /overview 统计 + 快速入口。
 * 断连保持空态降级，不阻塞其余页面。
 * 布局：核心指标卡片（图标徽章 + 语义色调）+ 快捷路径磁贴网格。
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import { Icon, type IconName } from '@/components/icons';
import { api, ApiError } from '@/api/client';
import type { OverviewStats } from '@/api/types';

/** 指标卡色调：neutral 常规；ok/warn/err 语义强调（风险类指标为 0 时保持安静的中性色） */
type StatTone = 'neutral' | 'primary' | 'ok' | 'warn' | 'err';

interface StatCardDef {
  key: string;
  label: string;
  icon: IconName;
  value: number | undefined;
  tone: StatTone;
}

interface QuickTile {
  to: string;
  title: string;
  desc: string;
  icon: IconName;
}

const QUICK_TILES: QuickTile[] = [
  { to: '/agents', title: '智能体资产', desc: '候选确认 · 资产纳管', icon: 'agents' },
  { to: '/permissions', title: '权限视图', desc: '同步 OpenShell 有效策略', icon: 'permissions' },
  { to: '/findings', title: '风险中心', desc: '风险确认与处置', icon: 'findings' },
  { to: '/policies', title: '策略中心', desc: '期望策略管理', icon: 'policies' },
  { to: '/changes', title: '变更中心', desc: '审批 → 部署 OpenShell', icon: 'changes' },
  { to: '/audit', title: '审计', desc: '事件只读溯源', icon: 'audit' },
];

export default function OverviewPage() {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .overview()
      .then((data) => {
        setStats(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setStats(null);
        setError(err instanceof ApiError ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
  }, []);

  const connected = stats !== null;
  const cards: StatCardDef[] = [
    { key: 'agents', label: '纳管资产', icon: 'agents', value: stats?.agents, tone: 'primary' },
    { key: 'candidates', label: '待评审候选', icon: 'scan', value: stats?.candidates, tone: (stats?.candidates ?? 0) > 0 ? 'warn' : 'neutral' },
    { key: 'open_findings', label: '未处置风险', icon: 'findings', value: stats?.open_findings, tone: (stats?.open_findings ?? 0) > 0 ? 'warn' : 'neutral' },
    { key: 'critical_findings', label: '高危风险', icon: 'shield-alert', value: stats?.critical_findings, tone: (stats?.critical_findings ?? 0) > 0 ? 'err' : 'neutral' },
    { key: 'environments', label: '环境', icon: 'environments', value: stats?.environments, tone: 'neutral' },
    { key: 'edges_online', label: '在线 Edge', icon: 'activity', value: stats?.edges_online, tone: (stats?.edges_online ?? 0) > 0 ? 'ok' : 'neutral' },
    { key: 'policies', label: '策略', icon: 'policies', value: stats?.policies, tone: 'neutral' },
  ];

  return (
    <section>
      <PageHeader
        title="总览"
        description="智能体安全管控平台控制台：资产、权限、风险、策略、变更与审计的统一入口（设计文档 §20.1）。"
        connection={loading ? 'loading' : connected ? 'connected' : 'disconnected'}
        connectionError={error}
      />

      {!connected && !loading ? (
        <DisconnectedNotice error={error} onRetry={load} />
      ) : (
        <div className="stats-grid">
          {cards.map((c) => (
            <div className="stat-card" key={c.key}>
              <div className="stat-head">
                <span className={`stat-icon tone-${c.tone}`}>
                  <Icon name={c.icon} size={16} />
                </span>
                <span className="stat-label">{c.label}</span>
              </div>
              <div className={`stat-value tone-${c.tone}`}>
                {loading ? '…' : String(c.value ?? 0)}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h2>快速入口</h2>
        <div className="quick-grid">
          {QUICK_TILES.map((tile) => (
            <Link key={tile.to} to={tile.to} className="quick-tile">
              <span className="quick-tile-icon">
                <Icon name={tile.icon} size={18} />
              </span>
              <span className="quick-tile-text">
                <span className="quick-tile-title">{tile.title}</span>
                <span className="quick-tile-desc" title={tile.desc}>{tile.desc}</span>
              </span>
              <span className="quick-tile-arrow">
                <Icon name="chevron-right" size={16} />
              </span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
