/**
 * 总览（§20.1）：真实 /overview 统计 + 快速入口。
 * 断连保持空态降级，不阻塞其余页面。
 */
import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import { api, ApiError } from '@/api/client';
import type { OverviewStats } from '@/api/types';

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
  const cards = [
    { key: 'agents', label: '纳管智能体资产', value: stats?.agents },
    { key: 'candidates', label: '待评审候选', value: stats?.candidates },
    { key: 'open_findings', label: '未处置风险', value: stats?.open_findings },
    { key: 'critical_findings', label: '高危风险', value: stats?.critical_findings },
    { key: 'environments', label: '环境', value: stats?.environments },
    { key: 'edges_online', label: '在线 Edge', value: stats?.edges_online },
    { key: 'policies', label: '策略', value: stats?.policies },
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
              <div className="stat-value">{loading ? '…' : String(c.value ?? 0)}</div>
              <div className="stat-label">{c.label}</div>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h2>快捷路径</h2>
        <p className="page-desc">
          <a href="/agents">智能体资产</a> · <a href="/permissions">权限视图</a>（同步 OpenShell 有效策略）·{' '}
          <a href="/findings">风险中心</a> · <a href="/policies">策略中心</a> ·{' '}
          <a href="/changes">变更中心</a>（审批→部署到 OpenShell）· <a href="/audit">审计</a>
        </p>
      </div>
    </section>
  );
}
