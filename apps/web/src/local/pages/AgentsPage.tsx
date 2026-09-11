import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { LocalApiError, localApi } from '../api';
import type { LedgerAsset } from '../types';
import { useLocalSession } from '../session';
import DiscoveryPanel from '../components/DiscoveryPanel';
import {
  assetStatusLabel,
  assetSourceLabel,
  assetStatusTag,
  grantStatusLabel,
  grantTag,
  platformLabel,
  verdictLabel,
  verdictTag,
} from '../format';

export default function AgentsPage() {
  const navigate = useNavigate();
  const { reload: reloadStatus } = useLocalSession();
  const [rows, setRows] = useState<LedgerAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [framework, setFramework] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [admitPath, setAdmitPath] = useState('');
  const [admitResult, setAdmitResult] = useState<{ name: string; verdict: string } | null>(null);
  const [admitErr, setAdmitErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    localApi
      .assets()
      .then((data) => {
        setRows(data.assets ?? []);
        setLoading(false);
        reloadStatus();
      })
      .catch((err: unknown) => {
        setRows([]);
        setError(err instanceof Error ? err.message : '盘点失败');
        setLoading(false);
      });
  }, [reloadStatus]);

  useEffect(() => {
    load();
  }, [load]);

  const runAdmit = (path: string) => {
    setAdmitResult(null);
    setAdmitErr(null);
    localApi
      .admit(path)
      .then((res) => {
        setAdmitResult({ name: res.admission.skill_name, verdict: res.admission.verdict });
        load();
      })
      .catch((err: unknown) => {
        setAdmitErr(err instanceof LocalApiError ? err.message : '准入失败');
      });
  };

  const frameworks = useMemo(
    () => Array.from(new Set(rows.map((r) => r.framework).filter(Boolean))).sort(),
    [rows],
  );
  const statuses = useMemo(
    () => Array.from(new Set(rows.map((r) => r.status).filter(Boolean))).sort(),
    [rows],
  );
  const visible = rows.filter((r) => {
    if (framework && r.framework !== framework) return false;
    if (statusFilter && r.status !== statusFilter) return false;
    return true;
  });

  const emptyText = loading
    ? '盘点中…'
    : error
      ? '暂时无法读取资产，请检查本地服务后重试。'
      : rows.length > 0
        ? '当前筛选无匹配资产，可放宽平台 / 状态条件。'
        : '未发现资产。确认本机装有 Agent 平台，或在下方粘贴 Skill 目录做准入。';

  const columns: TableColumn<LedgerAsset>[] = [
    {
      key: 'name',
      header: '名称',
      render: (r) => <span title={r.source_locator}>{r.name || r.id}<br />
        <small className="muted-text">{r.source_locator.replace(/^.*:\/\/skills\//, '')}</small>
      </span>,
    },
    {
      key: 'fw',
      header: '平台',
      render: (r) => <span className="cell-nowrap">{platformLabel(r.framework)}</span>,
    },
    { key: 'type', header: '来源', render: (r) => <span className="cell-nowrap">{assetSourceLabel(r.source_type)}</span> },
    { key: 'relationships', header: '发现的关联', render: (r) => {
      const linked = new Set((r.relationships ?? []).map((relation) => r.source_type === 'skill_dir' ? relation.source_id : relation.skill_id));
      return linked.size ? `${linked.size} ${r.source_type === 'skill_dir' ? '个可能使用者' : '个 Skill'}` : '尚未确认';
    } },
    {
      key: 'status',
      header: '状态',
      render: (r) => <span className={assetStatusTag(r.status)}>{assetStatusLabel(r.status)}</span>,
    },
    {
      key: 'verdict',
      header: '准入',
      render: (r) =>
        r.admission_verdict ? (
          <span className={verdictTag(r.admission_verdict)} title={r.admission_verdict}>
            {verdictLabel(r.admission_verdict)}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'grant',
      header: '签发',
      render: (r) =>
        r.grant_status ? (
          <span className={grantTag(r.grant_status)} title={r.grant_status}>
            {grantStatusLabel(r.grant_status)}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'tools',
      header: '声明工具',
      render: (r) =>
        r.declared_tools && r.declared_tools.length > 0 ? (
          <span className="muted-text">{r.declared_tools.join(', ')}</span>
        ) : (
          '—'
        ),
    },
    {
      key: 'act',
      header: '',
      render: (r) =>
        r.admit_path ? (
          <button
            type="button"
            className="btn btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              runAdmit(r.admit_path as string);
            }}
          >
            准入
          </button>
        ) : null,
    },
  ];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="agents"
        title="智能体资产"
        description="查看本机平台实例、Skill 安装位置、内容版本与配置关联。发现后由你选择保护范围。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
        actions={<>
          <Link className="btn btn-sm btn-primary" to="/skill-imports">导入 Skill</Link>
          <button type="button" className="btn btn-sm" onClick={load}>
            <Icon name="refresh" size={14} /> 刷新列表
          </button>
        </>}
      />
      <DiscoveryPanel onCompleted={load} />
      <div className="toolbar">
        <div className="field field-flush">
          <label htmlFor="fw-filter">平台</label>
          <select id="fw-filter" value={framework} onChange={(e) => setFramework(e.target.value)}>
            <option value="">全部</option>
            {frameworks.map((f) => (
              <option key={f} value={f}>
                {platformLabel(f)}
              </option>
            ))}
          </select>
        </div>
        <div className="field field-flush">
          <label htmlFor="st-filter">状态</label>
          <select
            id="st-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">全部</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {assetStatusLabel(s)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {error ? (
        <div className="notice" role="status">
          <p className="notice-title">盘点失败</p>
          <p className="notice-detail">{error}。确认已运行 siq-agent-security serve 后点「重新盘点」。</p>
        </div>
      ) : null}
      <div className="card">
        <h2>资产（{visible.length}）</h2>
        <SimpleTable
          columns={columns}
          rows={visible}
          rowKey={(r) => r.id}
          emptyText={emptyText}
          onRowClick={(r) => navigate(`/agents/${encodeURIComponent(r.id)}`)}
        />
      </div>
      <div className="card">
        <h2>按路径准入</h2>
        <p className="page-desc">
          列表「准入」使用本机目录（admit_path）。平台 locator 不是文件系统路径，请用绝对路径或 ~/…
        </p>
        <div className="toolbar toolbar-end">
          <div className="field field-flush field-grow">
            <label htmlFor="admit-path">Skill 目录</label>
            <input
              id="admit-path"
              value={admitPath}
              onChange={(e) => setAdmitPath(e.target.value)}
              placeholder="/path/to/skill"
            />
          </div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!admitPath.trim()}
            onClick={() => runAdmit(admitPath.trim())}
          >
            运行 admit
          </button>
        </div>
        {admitResult ? (
          <p className="page-desc">
            {admitResult.name}{' '}
            <span className={verdictTag(admitResult.verdict)} title={admitResult.verdict}>
              {verdictLabel(admitResult.verdict)}
            </span>
          </p>
        ) : null}
        {admitErr ? (
          <p className="action-error" role="alert">
            {admitErr}
          </p>
        ) : null}
      </div>
    </section>
  );
}
