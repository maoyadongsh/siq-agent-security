import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { LocalApiError, localApi } from '../api';
import type { LedgerAsset } from '../types';
import { useLocalSession } from '../session';
import { assetStatusLabel, assetStatusTag, grantTag, platformLabel, verdictTag } from '../format';

export default function AgentsPage() {
  const navigate = useNavigate();
  const { reload: reloadStatus } = useLocalSession();
  const [rows, setRows] = useState<LedgerAsset[]>([]);
  const [cwd, setCwd] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [framework, setFramework] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [admitPath, setAdmitPath] = useState('');
  const [admitMsg, setAdmitMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    localApi
      .assets(cwd.trim() || undefined)
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
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runAdmit = (path: string) => {
    setAdmitMsg(null);
    localApi
      .admit(path)
      .then((res) => {
        setAdmitMsg(`${res.admission.skill_name}: ${res.admission.verdict}`);
        load();
      })
      .catch((err: unknown) => {
        setAdmitMsg(err instanceof LocalApiError ? err.message : '准入失败');
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

  const columns: TableColumn<LedgerAsset>[] = [
    { key: 'name', header: '名称', render: (r) => r.name || r.id },
    {
      key: 'fw',
      header: '平台',
      render: (r) => platformLabel(r.framework),
    },
    { key: 'type', header: '来源', render: (r) => r.source_type },
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
          <span className={verdictTag(r.admission_verdict)}>{r.admission_verdict}</span>
        ) : (
          '—'
        ),
    },
    {
      key: 'grant',
      header: '签发',
      render: (r) =>
        r.grant_status ? <span className={grantTag(r.grant_status)}>{r.grant_status}</span> : '—',
    },
    {
      key: 'tools',
      header: '声明工具',
      render: (r) => (r.declared_tools && r.declared_tools.length > 0 ? r.declared_tools.join(', ') : '—'),
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
        description="本机盘点投影：平台配置与 Skill 目录。点进详情看证据与声明工具。不启动 MCP、不读取凭据文件。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
        actions={
          <button type="button" className="btn btn-sm" onClick={load}>
            <Icon name="refresh" size={14} /> 重新盘点
          </button>
        }
      />
      <div className="toolbar">
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="inv-cwd">额外扫描目录（可选）</label>
          <input
            id="inv-cwd"
            value={cwd}
            onChange={(e) => setCwd(e.target.value)}
            placeholder="项目根，例如 ~/src/app"
          />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
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
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="st-filter">状态</label>
          <select id="st-filter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
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
          <p className="notice-detail">{error}</p>
        </div>
      ) : null}
      <div className="card">
        <h2>资产（{visible.length}）</h2>
        <SimpleTable
          columns={columns}
          rows={visible}
          rowKey={(r) => r.id}
          emptyText={loading ? '盘点中…' : '未发现资产。可在下方粘贴 Skill 目录做准入。'}
          onRowClick={(r) => navigate(`/agents/${encodeURIComponent(r.id)}`)}
        />
      </div>
      <div className="card">
        <h2>按路径准入</h2>
        <p className="page-desc">
          列表「准入」使用本机目录（admit_path）。平台 locator 不是文件系统路径，请用绝对路径或 ~/…
        </p>
        <div className="toolbar">
          <div className="field" style={{ marginBottom: 0, flex: 1 }}>
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
        {admitMsg ? <p className="page-desc">{admitMsg}</p> : null}
      </div>
    </section>
  );
}
