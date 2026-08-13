/**
 * 权限视图（§20.2）：按权限域展示真实 PermissionFact，权威源/状态分色。
 * - 默认展示全部；提供 authority 过滤（含 openshell 真实有效权限）；
 * - 「同步 OpenShell」按钮拉取真实网关有效策略（fail-closed：网关不可达显示错误）；
 * - 模型推断（inferred）与未知（unknown）醒目样式，绝不显示成已生效。
 */
import { useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { PermissionFactRow } from '@/api/types';

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
    render: (row) => <code className="resource-cell">{row.resource_value}</code>,
  },
  { key: 'effect', header: '效果', render: (row) => row.effect },
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
      <span className={row.authority === 'openshell' ? 'authority-openshell' : undefined}>{row.authority}</span>
    ),
  },
  { key: 'authority_revision', header: 'Revision', render: (row) => row.authority_revision ?? '—' },
  { key: 'subject_id', header: '主体', render: (row) => row.subject_id },
];

export default function PermissionsPage() {
  const { rows, status, error, refresh } = useApiList<PermissionFactRow>(
    '/permissions',
    PLACEHOLDER_PERMISSIONS,
  );
  const [authorityFilter, setAuthorityFilter] = useState<string>('');
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const authorities = Array.from(new Set(rows.map((r) => r.authority))).sort();
  const visible = authorityFilter ? rows.filter((r) => r.authority === authorityFilter) : rows;

  const onSync = async () => {
    setSyncing(true);
    setSyncError(null);
    setSyncMessage(null);
    try {
      const result = await api.syncOpenShell();
      setSyncMessage(`已同步 ${result.facts} 条有效权限（${result.targets} 个沙箱）`);
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
        description="按权限域与权威来源展示 declared / inferred / observed / effective / unknown 分层（设计文档 §12.2）"
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
          <button className="btn-sm btn-primary" onClick={onSync} disabled={syncing}>
            {syncing ? '同步中…' : '同步 OpenShell 有效策略'}
          </button>
          {syncMessage && <span className="sync-ok">{syncMessage}</span>}
          {syncError && <span className="sync-err">{syncError}</span>}
        </div>
      </div>

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
