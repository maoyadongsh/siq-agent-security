/**
 * 权限视图（§20.2）：按权限域展示真实 PermissionFact，权威源/状态分色。
 * - 默认展示全部；提供 authority 过滤（含 openshell 真实有效权限）；
 * - 「同步 OpenShell」按钮拉取真实网关有效策略（fail-closed：网关不可达显示错误）；
 * - 模型推断（inferred）与未知（unknown）醒目样式，绝不显示成已生效。
 */
import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { Environment, PermissionFactRow } from '@/api/types';

const PLACEHOLDER_PERMISSIONS: PermissionFactRow[] = [];

const DOMAIN_LABELS: Record<string, string> = {
  filesystem: '文件',
  network: '网络',
  process: '进程',
  model: '模型',
  credential: '凭据',
  data_scope: '数据范围',
  tool: '工具',
  business: '业务',
  resource: '资源',
  control_plane: '控制面',
};

const columns: TableColumn<PermissionFactRow>[] = [
  {
    key: 'domain',
    header: '权限域',
    render: (row) => DOMAIN_LABELS[row.domain] ?? row.domain,
  },
  { key: 'action', header: '动作', render: (row) => row.action },
  {
    key: 'resource_value',
    header: '资源',
    render: (row) => <code className="resource-cell" title={row.resource_value}>{row.resource_value}</code>,
  },
  { key: 'effect', header: '效果', render: (row) => <span className="cell-nowrap">{row.effect}</span> },
  {
    key: 'state',
    header: '状态',
    render: (row) => (
      <span className={`state-tag ${row.state}`}>
        {row.state === 'effective' ? '有效' : row.state === 'inferred' ? '推断' : row.state}
      </span>
    ),
  },
  {
    key: 'authority',
    header: '权威来源',
    render: (row) => (
      <span className={`cell-nowrap${row.authority === 'openshell' ? ' authority-openshell' : ''}`}>{row.authority}</span>
    ),
  },
  { key: 'authority_revision', header: 'Revision', render: (row) => row.authority_revision ?? '—' },
  {
    key: 'subject_id',
    header: '主体',
    render: (row) => (
      <span className="mono cell-ellipsis" title={row.subject_id}>{row.subject_id}</span>
    ),
  },
];

export default function PermissionsPage() {
  const { rows, status, error, refresh } = useApiList<PermissionFactRow>(
    '/permissions',
    PLACEHOLDER_PERMISSIONS,
  );
  const environments = useApiList<Environment>('/environments', []);
  const [environmentId, setEnvironmentId] = useState('');
  const [authorityFilter, setAuthorityFilter] = useState<string>('');
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [driftChecking, setDriftChecking] = useState(false);
  const [driftMessage, setDriftMessage] = useState<string | null>(null);
  const [diffChecking, setDiffChecking] = useState(false);
  const [diffMessage, setDiffMessage] = useState<string | null>(null);
  const [diffDetail, setDiffDetail] = useState<Awaited<ReturnType<typeof api.permissionsDiff>> | null>(null);

  useEffect(() => {
    if (!environmentId && environments.rows.length > 0) {
      setEnvironmentId(environments.rows[0].id);
    }
  }, [environmentId, environments.rows]);

  const authorities = Array.from(new Set(rows.map((r) => r.authority))).sort();
  const visible = authorityFilter ? rows.filter((r) => r.authority === authorityFilter) : rows;

  const onDrift = async () => {
    setDriftChecking(true);
    setDriftMessage(null);
    try {
      const result = await api.checkDrift();
      if (result.drift_results.length === 0) {
        setDriftMessage('漂移检测：无漂移（期望状态与执行端一致）');
      } else {
        setDriftMessage(`漂移检测：${result.drift_results.length} 项漂移已生成 Finding（新增 ${result.created}）`);
      }
      refresh();
    } catch (err) {
      setSyncError(err instanceof ApiError ? err.message : '漂移检测失败');
    } finally {
      setDriftChecking(false);
    }
  };

  const onDiff = async () => {
    setDiffChecking(true);
    setDiffMessage(null);
    setDiffDetail(null);
    try {
      // 对 openshell 主体（若存在）比对 declared vs effective
      const subjects = Array.from(new Set(rows.filter((r) => r.authority === 'openshell').map((r) => r.subject_id)));
      if (subjects.length === 0) {
        setDiffMessage('当前没有 openshell 主体可比对（先执行同步）');
        return;
      }
      const detail = await api.permissionsDiff(subjects[0]);
      setDiffDetail(detail);
      setDiffMessage(`主体 ${detail.subject_id}：声明 ${detail.declared_count} / 有效 ${detail.effective_count} / 一致 ${detail.consistent.length}`);
    } catch (err) {
      setSyncError(err instanceof ApiError ? err.message : 'Diff 失败');
    } finally {
      setDiffChecking(false);
    }
  };

  const onSync = async () => {
    setSyncing(true);
    setSyncError(null);
    setSyncMessage(null);
    try {
      const result = await api.syncOpenShell(environmentId);
      setSyncMessage(
        `已同步 ${result.facts} 条有效权限（${result.targets} 个已绑定沙箱，忽略 ${result.ignored_unbound_targets} 个未绑定目标）`,
      );
      refresh();
    } catch (err) {
      setSyncError(err instanceof ApiError ? err.message : '同步失败');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="权限视图"
        description="按权限域与权威来源区分声明、推断、观测、生效与未知状态。"
        connection={status}
        connectionError={error}
      />

      <div className="permissions-toolbar">
        <div className="filter-group">
          <button className={`btn-sm ${authorityFilter === '' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setAuthorityFilter('')}>
            全部（{rows.length}）
          </button>
          {authorities.map((a) => (
            <button
              key={a}
              className={`btn-sm ${authorityFilter === a ? 'btn-active' : 'btn-ghost'}`}
              onClick={() => setAuthorityFilter(a)}
            >
              {a}（{rows.filter((r) => r.authority === a).length}）
            </button>
          ))}
        </div>
        <div className="sync-group">
          <select
            aria-label="OpenShell 同步环境"
            value={environmentId}
            onChange={(event) => setEnvironmentId(event.target.value)}
          >
            <option value="">选择环境</option>
            {environments.rows.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.name}
              </option>
            ))}
          </select>
          <button className="btn-sm btn-primary" onClick={onSync} disabled={syncing || !environmentId}>
            {syncing ? '同步中…' : '同步 OpenShell 有效策略'}
          </button>
          <button className="btn-sm" onClick={onDrift} disabled={driftChecking}>
            {driftChecking ? '检测中…' : '检查漂移'}
          </button>
          <button className="btn-sm" onClick={onDiff} disabled={diffChecking}>
            {diffChecking ? '比对中…' : '声明 vs 有效 Diff'}
          </button>
          {syncMessage && <span className="sync-ok">{syncMessage}</span>}
          {syncError && <span className="sync-err">{syncError}</span>}
        </div>
      </div>

      {(driftMessage || diffMessage) && (
        <div className="card">
          {driftMessage && <p className="sync-ok">{driftMessage}</p>}
          {diffMessage && (
            <p className="page-desc">
              {diffMessage}——声明了但无有效 {diffDetail?.declared_not_effective.length ?? 0} 项、
              生效但未声明 {diffDetail?.effective_not_declared.length ?? 0} 项
            </p>
          )}
        </div>
      )}

      {status === 'disconnected' ? (
        <DisconnectedNotice error={error} onRetry={refresh} />
      ) : (
        <>
          <SimpleTable columns={columns} rows={visible} rowKey={(row) => row.id} />
          {status === 'connected' && visible.length === 0 && (
            <p className="muted-text">
              暂无权限事实。点击「同步 OpenShell 有效策略」从真实网关拉取（网关不可达时 fail-closed，不会显示空权限冒充安全状态）。
            </p>
          )}
        </>
      )}
    </div>
  );
}
