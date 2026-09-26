/**
 * 变更中心（§20.1 / DEV13-A）：真实变更单列表 + SoD 审批 + 显式环境/绑定部署。
 * - 禁止无解释选首个环境或首个 binding；
 * - 禁止前端合成 effective；状态来自 API。
 */
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useConsoleContext } from '@/components/ConsoleContext';
import ChangeReviewDialog from '@/components/ChangeReviewDialog';
import ChangeExecutionDialog from '@/components/ChangeExecutionDialog';
import DeploymentPreviewDialog from '@/components/DeploymentPreviewDialog';
import BatchDraftPanel from '@/components/batch-deployment/BatchDraftPanel';
import NetworkRevokeRecovery from '@/components/batch-deployment/NetworkRevokeRecovery';
import type { DeploymentSelection } from '@/api/deploymentPreview';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { ChangeRequestRow, Environment, RuntimeBindingRow } from '@/api/types';

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
  const { data: context } = useConsoleContext();
  const [query, setQuery] = useSearchParams();
  const selectedId = query.get('change');
  const [unknownChanges, setUnknownChanges] = useState<Set<string>>(() => new Set(query.get('unconfirmed') === '1' && selectedId ? [selectedId] : []));
  const [selectedBinding, setSelectedBinding] = useState<RuntimeBindingRow | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deploymentSelection, setDeploymentSelection] = useState<DeploymentSelection | null>(null);
  const allowDeployment = context?.actions.manage_policy && context.access.environments;
  const openReview = (id: string) => { const next = new URLSearchParams(query); next.set('change', id); next.delete('view'); next.delete('deployment'); next.delete('unconfirmed'); setQuery(next); };
  const closeReview = () => { const next = new URLSearchParams(query); next.delete('change'); next.delete('view'); next.delete('deployment'); next.delete('unconfirmed'); setQuery(next); };

  const openExecution = (id: string, deploymentId?: string, uncertain = unknownChanges.has(id)) => {
    const next = new URLSearchParams(query); next.set('change', id); next.set('view', 'execution');
    if (deploymentId) next.set('deployment', deploymentId); else next.delete('deployment');
    if (uncertain) next.set('unconfirmed', '1'); else next.delete('unconfirmed');
    setQuery(next);
  };

  const deploy = (cr: ChangeRequestRow) => {
    if (!allowDeployment) return;
    if (unknownChanges.has(cr.id)) { openExecution(cr.id); return; }
    setActionError(null);
    if (!selectedBinding) { setActionError('请先选择部署环境和运行时绑定。'); return; }
    setDeploymentSelection({ change_request_id: cr.id, environment_id: selectedBinding.environment_id, binding_id: selectedBinding.id });
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
    { key: 'created_at', header: '时间', render: (r) => r.created_at },
    {
      key: 'actions',
      header: '操作',
      render: (r) => (
        <div className="row-actions">
          <button type="button" className="btn-sm" onClick={() => openReview(r.id)}>{r.status === 'proposed' ? '查看并审查' : '查看处理结果'}</button>
          <button type="button" className="btn-sm" onClick={() => openExecution(r.id)}>部署与审计</button>
          {allowDeployment && canDeploy(r.status) && (
            <button
              type="button"
              className="btn-sm btn-primary"
              onClick={() => deploy(r)}
            >
              {unknownChanges.has(r.id) ? '核对部署结果' : '部署'}
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
        description="先查看适用对象、权限内容与影响，再审批。批准、部署和运行时生效分别核对。"
        connection={status}
        connectionError={error}
      />
      {allowDeployment ? <DeploymentTargets onSelect={setSelectedBinding} /> : <p className="list-coverage">当前账号可按权限查看或审批变更；部署需要策略管理及环境读取权限。</p>}
      {context?.actions.manage_policy && context.actions.propose_change && context.access.policies && query.get('revoke_policy') && query.get('revoke_request') ? <NetworkRevokeRecovery key={`${context.tenant.id}:${context.actor.type}:${context.actor.id}:${query.get('revoke_policy')}:${query.get('revoke_request')}`} policyId={query.get('revoke_policy')!} requestKey={query.get('revoke_request')!} /> : null}
      {allowDeployment && status === 'connected' ? <BatchDraftPanel key={`${context.tenant.id}:${context.actor.type}:${context.actor.id}`} changes={rows} binding={selectedBinding} /> : null}
      {deploymentSelection ? <DeploymentPreviewDialog key={`${deploymentSelection.change_request_id}:${deploymentSelection.binding_id}`} selection={deploymentSelection} onClose={() => setDeploymentSelection(null)}
        onStarting={() => openExecution(deploymentSelection.change_request_id, undefined, true)}
        onRejected={closeReview}
        onViewResults={() => { const id = deploymentSelection.change_request_id; setDeploymentSelection(null); openExecution(id); }}
        onSubmitted={deploymentId => { const id = deploymentSelection.change_request_id; setDeploymentSelection(null); refresh(); openExecution(id, deploymentId); }}
        onUncertain={() => { const id = deploymentSelection.change_request_id; setUnknownChanges(ids => new Set([...ids, id])); setDeploymentSelection(null); setActionError('暂时无法确认部署结果，请先核对部署与审计记录，避免重复提交。'); openExecution(id, undefined, true); }} /> : null}
      {selectedId && !deploymentSelection ? query.get('view') === 'execution' ? <ChangeExecutionDialog key={selectedId} id={selectedId} uncertain={query.get('unconfirmed') === '1' || unknownChanges.has(selectedId)} expectedDeploymentId={query.get('deployment') ?? undefined} onClose={closeReview} /> : <ChangeReviewDialog key={selectedId} id={selectedId} onClose={closeReview} onUpdated={refresh} /> : null}
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
          <div className="change-desktop-table"><SimpleTable columns={columns} rows={rows} rowKey={(r) => r.id} /></div>
          <div className="change-mobile-list">{rows.map(r => <article key={r.id}><h3>{STATUS_LABELS[r.status] ?? r.status}</h3><p>提出账号：{r.proposer_user_id}</p><p>变更：{r.id}</p><p>策略：{r.policy_id}</p><button type="button" className="btn" onClick={() => openReview(r.id)}>{r.status === 'proposed' ? '查看并审查' : '查看处理结果'}</button><button type="button" className="btn" onClick={() => openExecution(r.id)}>部署与审计</button>{allowDeployment && canDeploy(r.status) ? <button type="button" className="btn" onClick={() => void deploy(r)}>{unknownChanges.has(r.id) ? '核对部署结果' : '部署'}</button> : null}</article>)}</div>
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

function DeploymentTargets({ onSelect }: { onSelect: (binding: RuntimeBindingRow | null) => void }) {
  const { rows: environments, status: envStatus, refresh: reloadEnvs } = useApiList<Environment>('/environments', []);
  const { rows: bindings, status: bindingStatus, refresh: reloadBindings } = useApiList<RuntimeBindingRow>('/runtime-bindings', []);
  const [environmentId, setEnvironmentId] = useState('');
  const [bindingId, setBindingId] = useState('');
  const activeBindings = useMemo(() => bindings.filter(b => b.status === 'active' && b.environment_id === environmentId), [bindings, environmentId]);
  useEffect(() => { onSelect(envStatus === 'connected' && bindingStatus === 'connected' ? activeBindings.find(b => b.id === bindingId) ?? null : null); }, [activeBindings, bindingId, envStatus, bindingStatus, onSelect]);
  return <div className="form-row">
    <label>部署环境<select aria-label="部署环境" value={environmentId} disabled={envStatus !== 'connected'} onChange={e => { setEnvironmentId(e.target.value); setBindingId(''); }}><option value="">请选择环境</option>{environments.filter(e => e.mode === 'enforce').map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
    <label>运行时绑定<select aria-label="运行时绑定" value={bindingId} disabled={bindingStatus !== 'connected' || !environmentId} onChange={e => setBindingId(e.target.value)}><option value="">{environmentId ? '请选择绑定' : '先选择环境'}</option>{activeBindings.map(b => <option key={b.id} value={b.id}>{b.backend}：{b.backend_target_id}</option>)}</select></label>
    {envStatus === 'disconnected' || bindingStatus === 'disconnected' ? <button type="button" className="btn-sm" onClick={() => { reloadEnvs(); reloadBindings(); }}>重新读取部署目标</button> : null}
    <p className="text-muted">仅列出当前读取到的执行环境与有效绑定；缺少目标时请先完成环境和运行时接入。</p>
  </div>;
}
