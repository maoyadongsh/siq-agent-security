import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { localApi } from '../api';
import type { PermissionFact } from '../types';
import { domainLabel, factStateLabel, factStateTag, hasOpenShellL3 } from '../format';
import { useLocalSession } from '../session';

const STATE_ORDER = ['effective', 'observed', 'inferred', 'declared', 'unknown'];

export default function PermissionsPage() {
  const { status } = useLocalSession();
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<PermissionFact[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [driftMsg, setDriftMsg] = useState<string | null>(null);
  const [subject, setSubject] = useState(params.get('subject_id') ?? '');
  const [domain, setDomain] = useState('');
  const [stateFilter, setStateFilter] = useState('');

  const load = (subjectId?: string) => {
    setLoading(true);
    localApi
      .permissions(subjectId?.trim() || undefined)
      .then((data) => {
        setRows(data.facts ?? []);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setRows([]);
        setError(err instanceof Error ? err.message : '加载失败');
        setLoading(false);
      });
  };

  const subjectFromUrl = params.get('subject_id') ?? '';
  useEffect(() => {
    setSubject(subjectFromUrl);
    load(subjectFromUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subjectFromUrl]);

  const l3 = hasOpenShellL3(status?.platforms);
  const runDrift = () => {
    setDriftMsg(null);
    localApi
      .openshellDriftCheck()
      .then((res) => {
        const n = res.findings_written?.length ?? 0;
        setDriftMsg(n > 0 ? `已写入 ${n} 条漂移 finding` : '读回完成，未发现网络段差异');
        load(subject);
      })
      .catch((err: unknown) => setDriftMsg(err instanceof Error ? err.message : '漂移检测失败'));
  };

  const applySubject = () => {
    const next = subject.trim();
    if (next) setParams({ subject_id: next });
    else setParams({});
    load(next);
  };

  const domains = useMemo(() => Array.from(new Set(rows.map((r) => r.domain))).sort(), [rows]);
  const states = useMemo(
    () =>
      Array.from(new Set(rows.map((r) => r.state))).sort(
        (a, b) => STATE_ORDER.indexOf(a) - STATE_ORDER.indexOf(b),
      ),
    [rows],
  );
  const visible = rows.filter((r) => {
    if (domain && r.domain !== domain) return false;
    if (stateFilter && r.state !== stateFilter) return false;
    return true;
  });
  const effectiveCount = rows.filter((r) => r.state === 'effective').length;

  const columns: TableColumn<PermissionFact>[] = [
    { key: 'domain', header: '权限域', render: (r) => domainLabel(r.domain) },
    { key: 'action', header: '动作', render: (r) => r.action },
    {
      key: 'resource',
      header: '资源',
      render: (r) => (
        <code className="resource-cell" title={r.resource_value}>
          {r.resource_value}
        </code>
      ),
    },
    { key: 'effect', header: '效果', render: (r) => r.effect },
    {
      key: 'state',
      header: '状态',
      render: (r) => <span className={factStateTag(r.state)}>{factStateLabel(r.state)}</span>,
    },
    {
      key: 'authority',
      header: '权威来源',
      render: (r) =>
        r.authority === 'openshell' ? (
          <span className="authority-openshell cell-nowrap">{r.authority}</span>
        ) : (
          <span className="cell-nowrap">{r.authority}</span>
        ),
    },
    { key: 'source', header: '投影源', render: (r) => r.source },
    {
      key: 'subject',
      header: '主体',
      render: (r) => (
        <span className="mono cell-ellipsis" title={r.subject_id}>
          {r.subject_id}
        </span>
      ),
    },
  ];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="permissions"
        title="权限视图"
        description="五态对照：声明 ≠ 签发 ≠ 拦截观测 ≠ 沙箱读回。filesystem / process 永不标有效；deployed grant 仍是声明态。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
        actions={
          <button type="button" className="btn btn-sm" onClick={() => load(subject)}>
            <Icon name="refresh" size={14} /> 刷新
          </button>
        }
      />
      <div className="permissions-toolbar">
        <div className="filter-group">
          <button
            type="button"
            className={`btn-sm ${stateFilter === '' ? 'btn-active' : 'btn-ghost'}`}
            onClick={() => setStateFilter('')}
          >
            全部（{rows.length}）
          </button>
          {states.map((s) => (
            <button
              key={s}
              type="button"
              className={`btn-sm ${stateFilter === s ? 'btn-active' : 'btn-ghost'}`}
              onClick={() => setStateFilter(s)}
            >
              {factStateLabel(s)}（{rows.filter((r) => r.state === s).length}）
            </button>
          ))}
        </div>
        <div className="filter-group">
          <button
            type="button"
            className="btn btn-sm"
            disabled={!l3}
            title={l3 ? '对 OpenShell 做读回比对' : '无 L3：须已验明 OpenShell 才能漂移检测'}
            onClick={runDrift}
          >
            漂移检测
          </button>
          {!l3 ? (
            <span className="muted-text">
              无 L3：按钮已禁用。须已验明 OpenShell，失败不得写成「无漂移」。
            </span>
          ) : null}
        </div>
      </div>
      {driftMsg ? <p className="sync-ok">{driftMsg}</p> : null}
      <div className="toolbar">
        <div className="field field-flush">
          <label htmlFor="perm-sub">主体 ID</label>
          <input
            id="perm-sub"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="可选过滤"
          />
        </div>
        <button type="button" className="btn btn-sm" onClick={applySubject}>
          过滤
        </button>
        <div className="field field-flush">
          <label htmlFor="perm-dom">权限域</label>
          <select id="perm-dom" value={domain} onChange={(e) => setDomain(e.target.value)}>
            <option value="">全部</option>
            {domains.map((d) => (
              <option key={d} value={d}>
                {domainLabel(d)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="page-desc">
        当前投影 {rows.length} 条 · 标为有效 {effectiveCount} 条
        {effectiveCount === 0 ? '（无 OpenShell 读回时这是预期）' : ''}。
      </p>
      {error ? (
        <div className="notice" role="status">
          <p className="notice-title">加载失败</p>
          <p className="notice-detail">{error}</p>
        </div>
      ) : null}
      <div className="card">
        <SimpleTable
          columns={columns}
          rows={visible}
          rowKey={(r) => r.fact_id}
          emptyText={
            loading
              ? '加载中…'
              : error
                ? '决策 API 不可达，暂时无法读取权限事实。'
                : rows.length > 0
                  ? '当前筛选无匹配事实。'
                  : '暂无权限事实。准入或签发后会出现声明态。'
          }
        />
      </div>
    </section>
  );
}
