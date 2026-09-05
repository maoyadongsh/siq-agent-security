import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import { Icon, type IconName } from '@/components/icons';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import { platformTierText, hasOpenShellL3, shortHash } from '../format';
import type { LedgerOverview } from '../types';

const TILES: { to: string; title: string; desc: string; icon: IconName }[] = [
  { to: '/agents', title: '智能体资产', desc: '本机平台与 Skill，点进详情看证据', icon: 'agents' },
  { to: '/permissions', title: '权限视图', desc: '五态对照：声明 ≠ 观测 ≠ 有效', icon: 'permissions' },
  { to: '/findings', title: '风险中心', desc: '准入与漂移 finding，可接受覆盖', icon: 'findings' },
  { to: '/grants', title: '签发', desc: '人工批准最小权限，重叠需确认', icon: 'policies' },
  { to: '/receipts', title: '回执', desc: '工具调用链、deny 高亮、验签', icon: 'audit' },
  { to: '/bindings', title: '运行时绑定', desc: '适配器钩子与 OpenShell 探针', icon: 'bindings' },
];

export default function OverviewPage() {
  const { status, error, reload } = useLocalSession();
  const [overview, setOverview] = useState<LedgerOverview | null>(null);
  const connected = status !== null;

  useEffect(() => {
    if (!connected) return;
    localApi
      .assets()
      .then((data) => setOverview(data.overview))
      .catch(() => setOverview(null));
  }, [connected, status?.chain.head_seq, status?.enforcement_mode]);

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="overview"
        title="智能体总览"
        description="本地单用户门禁官：看得见本机 Skill，对照权限五态，查得到被拒的调用。不登录、不依赖企业控制面。"
        connection={connected ? 'connected' : error ? 'disconnected' : 'loading'}
        connectionError={error}
        actions={
          <button type="button" className="btn btn-sm" onClick={reload}>
            <Icon name="refresh" size={14} /> 刷新
          </button>
        }
      />
      {error && !connected ? (
        <div className="notice" role="status">
          <p className="notice-title">决策 API 暂不可达</p>
          <p className="notice-detail">{error}。确认已运行 `agentshield serve`，且本页来自 127.0.0.1。</p>
        </div>
      ) : null}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-head">
            <span className="stat-icon tone-primary">
              <Icon name="agents" size={16} />
            </span>
            <span className="stat-label">本机资产</span>
          </div>
          <div className="stat-value">{overview ? String(overview.assets) : '—'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-head">
            <span className="stat-icon tone-warn">
              <Icon name="shield-alert" size={16} />
            </span>
            <span className="stat-label">未准入 Skill</span>
          </div>
          <div className="stat-value">{overview ? String(overview.unadmitted_skills) : '—'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-head">
            <span className="stat-icon tone-warn">
              <Icon name="findings" size={16} />
            </span>
            <span className="stat-label">开放 finding</span>
          </div>
          <div className="stat-value">{overview ? String(overview.open_findings) : '—'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-head">
            <span className="stat-icon">
              <Icon name="activity" size={16} />
            </span>
            <span className="stat-label">回执 deny</span>
          </div>
          <div className="stat-value">{overview ? String(overview.recent_denies) : '—'}</div>
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-head">
            <span className="stat-icon tone-primary">
              <Icon name="shield" size={16} />
            </span>
            <span className="stat-label">执行模式</span>
          </div>
          <div className="stat-value">{status?.enforcement_mode ?? '—'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-head">
            <span className="stat-icon tone-ok">
              <Icon name="activity" size={16} />
            </span>
            <span className="stat-label">回执链头 seq</span>
          </div>
          <div className="stat-value">
            {status && status.chain.head_seq >= 0 ? String(status.chain.head_seq) : '—'}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-head">
            <span className="stat-icon">
              <Icon name="agents" size={16} />
            </span>
            <span className="stat-label">已发现平台</span>
          </div>
          <div className="stat-value">
            {status ? String(status.platforms.filter((p) => p.detected).length) : '—'}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-head">
            <span className="stat-icon tone-ok">
              <Icon name="policies" size={16} />
            </span>
            <span className="stat-label">已部署签发</span>
          </div>
          <div className="stat-value">{overview ? String(overview.grants_deployed) : '—'}</div>
        </div>
      </div>

      <div className="card">
        <h2>平台档位</h2>
        <p className="page-desc">
          管控默认是 L0–L2（准入、授权、工具调用回执）。OpenShell 是可选 L3：probe
          成功后才显示。无 L3 时顶栏写「仅工具层拦截」。Trae 没有工具钩子，只能审计。filesystem /
          process 永远不会标有效。
        </p>
        <ul className="page-desc">
          {(status?.platforms ?? []).map((p) => (
            <li key={p.name}>
              <strong>{platformTierText(p, hasOpenShellL3(status?.platforms))}</strong> · {p.adapter}
              {p.note ? ` — ${p.note}` : ''}
            </li>
          ))}
        </ul>
        {status?.chain.head_hash ? (
          <p className="mono page-desc">链头 {shortHash(status.chain.head_hash, 16)}</p>
        ) : null}
      </div>

      <div className="card">
        <h2>快速入口</h2>
        <div className="quick-grid">
          {TILES.map((tile) => (
            <Link key={tile.to} to={tile.to} className="quick-tile">
              <span className="quick-tile-icon">
                <Icon name={tile.icon} size={18} />
              </span>
              <span className="quick-tile-text">
                <span className="quick-tile-title">{tile.title}</span>
                <span className="quick-tile-desc">{tile.desc}</span>
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
