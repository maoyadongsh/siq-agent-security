import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon, type IconName } from '@/components/icons';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import {
  adapterLabel,
  adapterTag,
  hasOpenShellL3,
  platformLabel,
  platformTierText,
  shortHash,
} from '../format';
import type { LedgerOverview, PlatformInfo } from '../types';

/** 指标卡色调与企业台一致：neutral 常规；风险类指标为 0 时保持安静，>0 才 warn/err。 */
type StatTone = 'neutral' | 'primary' | 'ok' | 'warn' | 'err';

interface StatCardDef {
  key: string;
  label: string;
  icon: IconName;
  value: string;
  tone: StatTone;
}

const TILES: { to: string; title: string; desc: string; icon: IconName }[] = [
  { to: '/agents', title: '智能体资产', desc: '盘点本机平台与 Skill，点进详情看证据', icon: 'agents' },
  { to: '/permissions', title: '权限视图', desc: '五态对照：声明 ≠ 观测 ≠ 有效', icon: 'permissions' },
  { to: '/findings', title: '风险中心', desc: '准入与漂移 finding，可接受并设到期', icon: 'findings' },
  { to: '/grants', title: '签发', desc: '人工批准最小权限，重叠须确认', icon: 'policies' },
  { to: '/receipts', title: '回执', desc: '工具调用哈希链，deny 高亮可验签', icon: 'audit' },
  { to: '/bindings', title: '运行时绑定', desc: '适配器钩子与 OpenShell 探针', icon: 'bindings' },
];

const MODE_LABELS: Record<string, string> = {
  block: '阻断',
  warn: '告警',
  audit_only: '仅审计',
};

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

  const num = (v: number | undefined): string =>
    overview ? String(v ?? 0) : connected ? '…' : '—';

  const unadmitted = overview?.unadmitted_skills ?? 0;
  const openFindings = overview?.open_findings ?? 0;
  const recentDenies = overview?.recent_denies ?? 0;
  const platformsFound = status?.platforms.filter((p) => p.detected).length ?? 0;

  const cards: StatCardDef[] = [
    { key: 'assets', label: '本机资产', icon: 'agents', value: num(overview?.assets), tone: 'primary' },
    {
      key: 'unadmitted',
      label: '未准入 Skill',
      icon: 'shield-alert',
      value: num(overview?.unadmitted_skills),
      tone: unadmitted > 0 ? 'warn' : 'neutral',
    },
    {
      key: 'findings',
      label: '开放 finding',
      icon: 'findings',
      value: num(overview?.open_findings),
      tone: openFindings > 0 ? 'warn' : 'neutral',
    },
    {
      key: 'denies',
      label: '回执 deny',
      icon: 'activity',
      value: num(overview?.recent_denies),
      tone: recentDenies > 0 ? 'err' : 'neutral',
    },
    {
      key: 'mode',
      label: '执行模式',
      icon: 'shield',
      value: status ? (MODE_LABELS[status.enforcement_mode] ?? status.enforcement_mode) : '—',
      tone: 'primary',
    },
    {
      key: 'chain',
      label: '回执链头 seq',
      icon: 'audit',
      value: status && status.chain.head_seq >= 0 ? String(status.chain.head_seq) : '—',
      tone: 'neutral',
    },
    {
      key: 'platforms',
      label: '已发现平台',
      icon: 'bindings',
      value: status ? String(platformsFound) : '—',
      tone: platformsFound > 0 ? 'ok' : 'neutral',
    },
    {
      key: 'grants',
      label: '已部署签发',
      icon: 'policies',
      value: num(overview?.grants_deployed),
      tone: 'neutral',
    },
  ];

  const openShellL3 = hasOpenShellL3(status?.platforms);
  const platformCols: TableColumn<PlatformInfo>[] = [
    {
      key: 'name',
      header: '平台',
      render: (p) => <span className="cell-nowrap">{platformLabel(p.name)}</span>,
    },
    {
      key: 'tier',
      header: '档位',
      render: (p) => <span className="cell-nowrap">{platformTierText(p, openShellL3)}</span>,
    },
    {
      key: 'adapter',
      header: '适配器',
      render: (p) => <span className={adapterTag(p.adapter)}>{adapterLabel(p.adapter)}</span>,
    },
    { key: 'note', header: '说明', render: (p) => p.note || '—' },
  ];

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
          <p className="notice-detail">
            {error}。确认已运行 <span className="mono">agentshield serve</span>，且本页来自
            127.0.0.1。
          </p>
        </div>
      ) : null}

      <div className="stats-grid">
        {cards.map((c) => (
          <div className="stat-card" key={c.key}>
            <div className="stat-head">
              <span className={`stat-icon tone-${c.tone}`}>
                <Icon name={c.icon} size={16} />
              </span>
              <span className="stat-label" title={c.key === 'grants' ? '已部署但未经读回，不等于有效' : c.label}>
                {c.label}
              </span>
            </div>
            <div className={`stat-value tone-${c.tone}`}>{c.value}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <h2>平台档位</h2>
        <p className="page-desc">
          管控默认是 L0–L2（准入、授权、工具调用回执）。OpenShell 是可选 L3：probe
          成功后才显示。无 L3 时顶栏写「仅工具层拦截」。Trae 没有工具钩子，只能审计。filesystem /
          process 永远不会标有效。
        </p>
        <SimpleTable
          columns={platformCols}
          rows={status?.platforms ?? []}
          rowKey={(p) => p.name}
          emptyText={
            connected
              ? '平台清单未返回。'
              : '决策 API 不可达，无法读取平台档位；请先启动 agentshield serve。'
          }
        />
        {status?.chain.head_hash ? (
          <p className="mono page-desc block-gap">链头 {shortHash(status.chain.head_hash, 16)}</p>
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
                <span className="quick-tile-desc" title={tile.desc}>
                  {tile.desc}
                </span>
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
