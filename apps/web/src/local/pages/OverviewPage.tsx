import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import { Icon, type IconName } from '@/components/icons';
import { useLocalSession } from '../session';
import { platformLabel, shortHash } from '../format';

const TILES: { to: string; title: string; desc: string; icon: IconName }[] = [
  { to: '/inventory', title: '盘点', desc: '发现本机平台与 Skill 目录', icon: 'scan' },
  { to: '/admissions', title: '准入', desc: '审查未知 Skill 并看 Skill Card', icon: 'findings' },
  { to: '/grants', title: '签发', desc: '人工批准最小权限，重叠需确认', icon: 'permissions' },
  { to: '/receipts', title: '回执', desc: '工具调用链、deny 高亮、验签', icon: 'audit' },
  { to: '/settings', title: '设置', desc: 'enforcement_mode 与适配器安装', icon: 'settings' },
];

export default function OverviewPage() {
  const { status, error, reload } = useLocalSession();
  const connected = status !== null;

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="overview"
        title="总览"
        description="本地单用户门禁官：盘点资产、准入未知 Skill、签发最小权限、给每次工具调用开签名回执。"
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
            <span className="stat-icon tone-warn">
              <Icon name="bindings" size={16} />
            </span>
            <span className="stat-label">已装适配器</span>
          </div>
          <div className="stat-value">
            {status ? String(status.platforms.filter((p) => p.adapter === 'installed').length) : '—'}
          </div>
        </div>
      </div>

      <div className="card">
        <h2>平台档位</h2>
        <p className="page-desc">
          Linux 可达 L3（OpenShell probe 成功后）。Trae 没有工具钩子，只能审计。filesystem / process 永远不会标 effective。
        </p>
        <ul className="page-desc">
          {(status?.platforms ?? []).map((p) => (
            <li key={p.name}>
              <strong>{platformLabel(p.name)}</strong> · {p.tier} · {p.adapter}
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
