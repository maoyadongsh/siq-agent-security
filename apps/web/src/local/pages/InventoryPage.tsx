import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { LocalApiError, localApi } from '../api';
import type { InventoryCandidate, InventoryReport } from '../types';
import { useLocalSession } from '../session';

export default function InventoryPage() {
  const { reload: reloadStatus } = useLocalSession();
  const [report, setReport] = useState<InventoryReport | null>(null);
  const [cwd, setCwd] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [admitPath, setAdmitPath] = useState('');
  const [admitMsg, setAdmitMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    localApi
      .inventory(cwd.trim() || undefined)
      .then((data) => {
        setReport(data);
        setLoading(false);
        reloadStatus();
      })
      .catch((err: unknown) => {
        setReport(null);
        setError(err instanceof Error ? err.message : '盘点失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
    // 仅首次；手动刷新走按钮
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

  const columns: TableColumn<InventoryCandidate>[] = [
    { key: 'name', header: '名称', render: (r) => r.name || r.candidate_id },
    { key: 'type', header: '类型', render: (r) => r.source_type },
    { key: 'fw', header: '平台', render: (r) => r.framework },
    {
      key: 'status',
      header: '状态',
      render: (r) => <span className={r.status === 'unadmitted' ? 'tag tag-warn' : 'tag'}>{r.status}</span>,
    },
    {
      key: 'loc',
      header: '位置',
      render: (r) => <span className="mono">{r.source_locator}</span>,
    },
    {
      key: 'act',
      header: '',
      render: (r) =>
        r.source_type === 'skill_dir' ? (
          <button
            type="button"
            className="btn btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              runAdmit(r.source_locator);
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
        icon="scan"
        title="盘点"
        description="只读发现本机 Agent 平台配置与 Skill 目录。不启动 MCP、不读取凭据文件。"
        connection={loading ? 'loading' : report ? 'connected' : 'disconnected'}
        connectionError={error}
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
        <button type="button" className="btn btn-primary" onClick={load}>
          <Icon name="refresh" size={14} /> 重新盘点
        </button>
      </div>
      {error ? (
        <div className="notice" role="status">
          <p className="notice-title">盘点失败</p>
          <p className="notice-detail">{error}</p>
        </div>
      ) : null}
      <div className="card">
        <h2>候选</h2>
        <p className="page-desc">
          平台 {report?.platforms.join(', ') || '（无）'}
          {report?.home ? ` · home ${report.home}` : ''}
        </p>
        <SimpleTable
          columns={columns}
          rows={report?.candidates ?? []}
          rowKey={(r) => r.candidate_id}
          emptyText={loading ? '盘点中…' : '未发现候选。可在下方粘贴 Skill 目录做准入。'}
        />
      </div>
      <div className="card">
        <h2>按路径准入</h2>
        <p className="page-desc">盘点里的路径可能显示为 ~；此处接受绝对路径或 ~/…（服务端展开）。</p>
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
