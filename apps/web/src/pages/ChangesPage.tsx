/**
 * 变更中心（§20.1 / DEV13-A）：真实变更单列表 + SoD 审批 + 显式环境/绑定部署。
 * - 禁止无解释选首个环境或首个 binding；
 * - 禁止前端合成 effective；状态来自 API。
 */
import { useEffect, useMemo, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { ChangeRequestRow, DeploymentRow, Environment, RuntimeBindingRow } from '@/api/types';
import { classifyDeploymentVerification } from '@/ui/verification';

const PLACEHOLDER: ChangeRequestRow[] = [];

const STATUS_LABELS: Record<string, string> = {
  proposed: '待审批',
  approved: '已批准',
  rejected: '已驳回',
  deploying: '发布中',
  effective: '已生效',
  failed: '失败',
  rolled_back: '已回滚',
  emergency_applied: '紧急已批准',
  post_review_due: '遗留复核标记',
};

const REVIEW_LABELS: Record<string, string> = {
  none: '—',
  pending: '复核待到期',
  due: '待事后复核',
  completed: '复核完成',
};

function canDeploy(status: string): boolean {
  return status === 'approved' || status === 'emergency_applied';
}

export default function ChangesPage() {
  const { rows, status, error, refresh, coverageText, hasMore, loadMore, loadingMore } =
    useApiList<ChangeRequestRow>('/change-requests', PLACEHOLDER);
  const { rows: deployments } = useApiList<DeploymentRow>('/deployments', []);
  const { rows: environments, status: envStatus } = useApiList<Environment>('/environments', []);
  const { rows: bindings, status: bindingStatus } = useApiList<RuntimeBindingRow>('/runtime-bindings', []);
  const [actionError, setActionError] = useState<string | null>(null);
  const [environmentId, setEnvironmentId] = useState('');
  const [bindingId, setBindingId] = useState('');
  const [deployingId, setDeployingId] = useState<string | null>(null);

  const activeBindings = useMemo(
    () =>
      bindings.filter(
        (b) => b.status === 'active' && (!environmentId || b.environment_id === environmentId),
      ),
    [bindings, environmentId],
  );

  useEffect(() => {
    // 环境切换后若当前绑定不属于该环境则清空（不自动顶替）
    if (bindingId && environmentId) {
      const ok = bindings.some(
        (b) => b.id === bindingId && b.status === 'active' && b.environment_id === environmentId,
      );
      if (!ok) setBindingId('');
    }
  }, [environmentId, bindingId, bindings]);

  const approve = async (id: string) => {
    setActionError(null);
    try {
      await api.approveChangeRequest(id);
      refresh();
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? `${err.message}（批准需 reviewer 角色且与提出者不同）`
          : '操作失败',
      );
    }
  };

  const reject = async (id: string) => {
    setActionError(null);
    try {
      await api.rejectChangeRequest(id);
      refresh();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '操作失败');
    }
  };

  const deploy = async (cr: ChangeRequestRow) => {
    setActionError(null);
    if (!environmentId) {
      setActionError('请先选择环境（禁止自动选首个）');
      return;
    }
    if (!bindingId) {
      setActionError('请先选择运行时绑定（禁止自动选首个）');
      return;
    }
    const binding = bindings.find((b) => b.id === bindingId);
    if (!binding || binding.status !== 'active') {
      setActionError('所选绑定不可用或已吊销');
      return;
    }
    if (binding.environment_id !== environmentId) {
      setActionError('绑定与环境不匹配');
      return;
    }
    setDeployingId(cr.id);
    try {
      await api.createDeployment(cr.id, environmentId, bindingId);
      refresh();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '部署失败');
    } finally {
      setDeployingId(null);
    }
  };

  const columns: TableColumn<ChangeRequestRow>[] = [
    { key: 'id', header: '变更单', render: (r) => <span className="mono">{r.id}</span> },
    { key: 'policy_id', header: '策略', render: (r) => <span className="mono">{r.policy_id}</span> },
    {
      key: 'status',
      header: '状态',
      render: (r) => (
        <span className={`state-tag ${r.status === 'effective' ? 'effective' : ''}`}>
          {STATUS_LABELS[r.status] ?? r.status}
        </span>
      ),
    },
    {
      key: 'review_status',
      header: '复核',
      render: (r) => REVIEW_LABELS[r.review_status ?? 'none'] ?? r.review_status ?? '—',
    },
    { key: 'proposer_user_id', header: '提出者', render: (r) => r.proposer_user_id },
    { key: 'approver_user_id', header: '批准者', render: (r) => r.approver_user_id ?? '—' },
    {
      key: 'deployment',
      header: '部署 / 验证',
      render: (r) => {
        const dep = deployments.find((d) => d.change_request_id === r.id);
        if (!dep) return '—';
        const view = classifyDeploymentVerification(dep.status, dep.verification);
        const binding = dep.runtime_binding_id
          ? `绑定 ${dep.runtime_binding_id}`
          : '无绑定';
        return (
          <span className={`verification-cell tone-${view.tone}`} title={view.detail || undefined}>
            <span className="mono">
              {dep.status} @ {dep.target}
            </span>
            <span className={`verification-badge tone-${view.tone}`}>{view.label}</span>
            <span className="verification-meta">
              {binding}
              {dep.to_revision ? ` · rev ${dep.to_revision}` : ''}
              {view.detail ? ` · ${view.detail}` : ''}
            </span>
          </span>
        );
      },
    },
    { key: 'created_at', header: '时间', render: (r) => r.created_at },
    {
      key: 'actions',
      header: '操作',
      render: (r) => (
        <div className="row-actions">
          {r.status === 'proposed' && (
            <>
              <button type="button" className="btn-sm" onClick={() => approve(r.id)}>
                批准
              </button>
              <button type="button" className="btn-sm btn-danger" onClick={() => reject(r.id)}>
                驳回
              </button>
            </>
          )}
          {canDeploy(r.status) && (
            <button
              type="button"
              className="btn-sm btn-primary"
              onClick={() => deploy(r)}
              disabled={deployingId === r.id}
            >
              {deployingId === r.id ? '部署中…' : '部署'}
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        icon="changes"
        title="变更中心"
        description="提案 → 职责分离审批 → 显式选择环境与运行时绑定后部署；读回验证与业务生效分开展示。"
        connection={status}
        connectionError={error}
      />
      <div className="form-row" style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
        <label>
          部署环境
          <select
            value={environmentId}
            onChange={(e) => setEnvironmentId(e.target.value)}
            disabled={envStatus !== 'connected'}
          >
            <option value="">请选择…</option>
            {environments.map((env) => (
              <option key={env.id} value={env.id}>
                {env.name} ({env.id}) · {env.mode}
              </option>
            ))}
          </select>
        </label>
        <label>
          运行时绑定
          <select
            value={bindingId}
            onChange={(e) => setBindingId(e.target.value)}
            disabled={bindingStatus !== 'connected' || !environmentId}
          >
            <option value="">{environmentId ? '请选择…' : '先选环境'}</option>
            {activeBindings.map((b) => (
              <option key={b.id} value={b.id}>
                {b.backend}:{b.backend_target_id} ({b.id})
              </option>
            ))}
          </select>
        </label>
      </div>
      {actionError && <p className="sync-err">{actionError}</p>}
      {coverageText ? (
        <p className="list-coverage" role="status">
          {coverageText}
        </p>
      ) : null}
      {status === 'disconnected' ? (
        <DisconnectedNotice error={error} onRetry={refresh} />
      ) : (
        <>
          <SimpleTable columns={columns} rows={rows} rowKey={(r) => r.id} />
          {hasMore ? (
            <div className="list-more">
              <button type="button" className="btn-sm" disabled={loadingMore} onClick={() => loadMore()}>
                {loadingMore ? '加载中…' : '加载更多'}
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
