import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { LocalApiError, localApi } from '../api';
import type { LedgerAsset } from '../types';
import { useLocalSession } from '../session';
import DiscoveryPanel from '../components/DiscoveryPanel';
import { assetKind, assetKinds, frameworkGroups, type FrameworkGroup } from '../assetKinds';
import { assetRelationships } from '../assetRelationships';
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
  const [params, setParams] = useSearchParams();
  const selectedKind = assetKinds.find((item) => item.key === params.get('kind')) ?? assetKinds[0];
  const { reload: reloadStatus } = useLocalSession();
  const [rows, setRows] = useState<LedgerAsset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const framework = params.get('framework') ?? '';
  const sourceId = params.get('source') ?? '';
  const onlyUnlinked = params.get('unlinked') === '1';
  const relationships = useMemo(() => assetRelationships(rows), [rows]);
  const setFramework = (value: string) => setParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set('framework', value); else next.delete('framework');
    return next;
  });
  const [statusFilter, setStatusFilter] = useState('');
  const [admitPath, setAdmitPath] = useState('');
  const [admitResult, setAdmitResult] = useState<{ name: string; verdict: string } | null>(null);
  const [admitErr, setAdmitErr] = useState<string | null>(null);
  const [checkingPath, setCheckingPath] = useState('');
  const checking = useRef(false);

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
    if (checking.current) return;
    checking.current = true;
    setCheckingPath(path);
    setAdmitResult(null);
    setAdmitErr(null);
    localApi
      .admit(path)
      .then((res) => {
        setAdmitResult({ name: res.admission.skill_name, verdict: res.admission.verdict });
        load();
      })
      .catch((err: unknown) => {
        setAdmitErr(err instanceof LocalApiError ? err.message : '检查失败，请重试');
      })
      .finally(() => { checking.current = false; setCheckingPath(''); });
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
    if (assetKind(r.source_type) !== selectedKind.key) return false;
    if (framework && r.framework !== framework) return false;
    if (statusFilter && r.status !== statusFilter) return false;
    if (selectedKind.key === 'skills' && sourceId && !relationships.skillsBySource.get(sourceId)?.has(r.id)) return false;
    if (selectedKind.key === 'skills' && onlyUnlinked && relationships.sourcesBySkill.has(r.id)) return false;
    return true;
  });
  const groups = frameworkGroups(rows);
  const visibleGroups = groups.filter((group) => !framework || group.framework === framework);
  const groupColumns: TableColumn<FrameworkGroup>[] = [
    { key: 'framework', header: '框架', render: (group) => platformLabel(group.framework) },
    { key: 'records', header: '配置记录', render: (group) => group.configurationRecords },
    { key: 'roles', header: '已发现角色', render: (group) => group.roleCount },
    { key: 'action', header: '操作', render: (group) => <button className="btn btn-sm" type="button" onClick={() => {
      setStatusFilter(''); setParams({ kind: 'roles', framework: group.framework });
    }}>查看角色</button> },
  ];

  const emptyText = loading
    ? '盘点中…'
    : error
      ? '暂时无法读取资产，请检查本地服务后重试。'
      : rows.length > 0
        ? '当前筛选无匹配资产，可放宽平台 / 状态条件。'
        : '尚未发现此类记录。可重新发现本机环境，或展开高级选项补充 Skill 目录。';

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
      header: '所属框架',
      render: (r) => <span className="cell-nowrap">{platformLabel(r.framework)}</span>,
    },
    { key: 'type', header: '来源', render: (r) => <span className="cell-nowrap">{assetSourceLabel(r.source_type)}</span> },
    { key: 'relationships', header: '配置关联', render: (r) => {
      const linked = (r.source_type === 'skill_dir' ? relationships.sourcesBySkill : relationships.skillsBySource).get(r.id);
      if (!linked?.size) return '未发现明确关联';
      if (r.source_type === 'skill_dir') return <span>{linked.size > 1 ? '共享：' : ''}{linked.size} 个配置来源（未核验调用）</span>;
      return <button className="btn btn-sm" onClick={(event) => { event.stopPropagation(); setStatusFilter(''); setParams({ kind: 'skills', source: r.id }); }}>查看 {linked.size} 个关联 Skill</button>;
    } },
    {
      key: 'status',
      header: '状态',
      render: (r) => <span className={assetStatusTag(r.status)}>{assetStatusLabel(r.status)}</span>,
    },
    {
      key: 'verdict',
      header: '安全检查',
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
      header: '授权状态',
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
        <div className="toolbar">{r.admit_path ? (
          <button
            type="button"
            className="btn btn-sm"
            disabled={!!checkingPath}
            onClick={(e) => {
              e.stopPropagation();
              runAdmit(r.admit_path as string);
            }}
          >
            {checkingPath === r.admit_path ? '检查中…' : '安全检查'}
          </button>
        ) : null}<Link to={`/agents/${encodeURIComponent(r.id)}`} onClick={(event) => event.stopPropagation()}>查看详情</Link></div>,
    },
  ];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="agents"
        title="我的智能体"
        description="先选择框架，再查看角色及其关联 Skill。管理的是服务所在设备；浏览器可能运行在另一台设备上。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
        actions={<>
          <Link className="btn btn-sm btn-primary" to="/skill-imports">导入 Skill</Link>
          <Link className="btn btn-sm" to="/installed-skills">安装与更新</Link>
          <Link className="btn btn-sm" to="/permission-center">批量管理权限</Link>
          <button type="button" className="btn btn-sm" onClick={load}>
            <Icon name="refresh" size={14} /> 刷新列表
          </button>
        </>}
      />
      <DiscoveryPanel compact onCompleted={load} />
      <div className="toolbar" role="group" aria-label="发现对象分类">
        {assetKinds.map((item) => <button type="button" key={item.key}
          className={selectedKind.key === item.key ? 'btn btn-primary' : 'btn'}
          aria-pressed={selectedKind.key === item.key} onClick={() => setParams((current) => {
            const next = new URLSearchParams(current); next.set('kind', item.key); next.delete('source'); next.delete('unlinked'); return next;
          })}>
          {item.label}（{item.key === 'frameworks' ? groups.length : rows.filter((row) => assetKind(row.source_type) === item.key).length}）
        </button>)}
      </div>
      <p className="page-desc">{selectedKind.description}</p>
      {selectedKind.key === 'skills' ? <div className="toolbar">
        {sourceId ? <span>当前来源：{rows.find((r) => r.id === sourceId)?.name ?? sourceId}。这是配置关联，不是已验证的执行归属。</span> : null}
        <button className="btn" aria-pressed={!sourceId && !onlyUnlinked} onClick={() => { setStatusFilter(''); setParams({ kind: 'skills' }); }}>全部 Skill</button>
        <button className="btn" aria-pressed={onlyUnlinked} onClick={() => { setStatusFilter(''); setParams({ kind: 'skills', unlinked: '1' }); }}>未关联 Skill</button>
      </div> : null}
      <div className="toolbar">
        <div className="field field-flush">
          <label htmlFor="fw-filter">所属框架</label>
          <select id="fw-filter" value={framework} onChange={(e) => setFramework(e.target.value)}>
            <option value="">全部</option>
            {frameworks.map((f) => (
              <option key={f} value={f}>
                {platformLabel(f)}
              </option>
            ))}
          </select>
        </div>
        {selectedKind.key !== 'frameworks' ? <div className="field field-flush">
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
        </div> : null}
      </div>
      {error ? (
        <div className="notice" role="status">
          <p className="notice-title">盘点失败</p>
          <p className="notice-detail">{error}。确认已运行 siq-agent-security serve 后点「重新盘点」。</p>
        </div>
      ) : null}
      <div className="card">
        <h2>{selectedKind.label}（{selectedKind.key === 'frameworks' ? visibleGroups.length : visible.length}）</h2>
        {selectedKind.key === 'frameworks' ? <SimpleTable columns={groupColumns} rows={visibleGroups} rowKey={(group) => group.framework} emptyText={emptyText} /> : <SimpleTable
          columns={selectedKind.key === 'skills' ? columns : columns.filter((column) => !['verdict', 'grant', 'tools'].includes(column.key))}
          rows={visible}
          rowKey={(r) => r.id}
          emptyText={emptyText}
          onRowClick={(r) => navigate(`/agents/${encodeURIComponent(r.id)}`)}
        />}
      </div>
      {admitResult ? <p role="status">{admitResult.name}：<span className={verdictTag(admitResult.verdict)}>{verdictLabel(admitResult.verdict)}</span>。检查结果已保存，可查看详情。</p> : null}
      {admitErr ? <p className="action-error" role="alert">{admitErr}</p> : null}
      <details className="card">
        <summary>高级操作：检查指定 Skill 目录</summary>
        <p className="page-desc">
          默认从上方发现结果选择 Skill；自定义目录可在这里填写绝对路径或 ~/…。
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
            disabled={!admitPath.trim() || !!checkingPath}
            onClick={() => runAdmit(admitPath.trim())}
          >
            检查此 Skill
          </button>
        </div>
      </details>
    </section>
  );
}
