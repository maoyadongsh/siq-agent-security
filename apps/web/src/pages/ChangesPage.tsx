/**
 * 变更中心（§20.1）：真实变更单列表 + 审批（SoD）/驳回 + 部署到执行后端。
 * - 部署目标默认取环境第一个 + 手动输入沙箱名（如 siq-as-live）；
 * - 部署结果（effective/失败原因）行内展示；
 * - SIQ_AS_ENFORCEMENT_BACKEND=openshell-cli 时部署触发真实 policy set + 读回验证。
 */
import { useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { ChangeRequestRow, DeploymentRow } from '@/api/types';

const PLACEHOLDER: ChangeRequestRow[] = [];

const STATUS_LABELS: Record<string, string> = {
  proposed: '待审批',
  approved: '已批准',
  rejected: '已驳回',
  deploying: '发布中',
  effective: '已生效',
  failed: '失败',
  rolled_back: '已回滚',
};

export default function ChangesPage() {
  const { rows, status, error, refresh } = useApiList<ChangeRequestRow>('/change-requests', PLACEHOLDER);
  const { rows: deployments } = useApiList<DeploymentRow>('/deployments', []);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deployTarget, setDeployTarget] = useState('siq-as-live');
  const [deployingId, setDeployingId] = useState<string | null>(null);

  const approve = async (id: string) => {
    setActionError(null);
    try {
      await api.approveChangeRequest(id);
      refresh();
    } catch (err) {
      setActionError(err instanceof ApiError ? `${err.message}（批准需 reviewer 角色且与提出者不同）` : '操作失败');
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
    setDeployingId(cr.id);
    try {
      const envs = await api.listEnvironments();
      const envId = envs[0]?.id;
      if (!envId) {
        setActionError('没有可用环境');
        return;
      }
      let bindingId = deployTarget?.trim();
      if (!bindingId) {
        const bindings = await api.listRuntimeBindings();
        const activeBinding = bindings.find((b) => b.status === 'active' && b.environment_id === envId) || bindings.find((b) => b.status === 'active');
        if (!activeBinding) {
          setActionError('未找到可用的运行时绑定（Runtime Binding），请先登记绑定');
          return;
        }
        bindingId = activeBinding.id;
      }
      await api.createDeployment(cr.id, envId, bindingId);
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
    { key: 'status', header: '状态', render: (r) => <span className={`state-tag ${r.status === 'effective' ? 'effective' : ''}`}>{STATUS_LABELS[r.status] ?? r.status}</span> },
    { key: 'proposer_user_id', header: '提出者', render: (r) => r.proposer_user_id },
    { key: 'approver_user_id', header: '批准者', render: (r) => r.approver_user_id ?? '—' },
    {
      key: 'deployment',
      header: '部署',
      render: (r) => {
        const dep = deployments.find((d) => d.change_request_id === r.id);
        return dep ? <span className="mono">{dep.status} @ {dep.target}（{dep.verification ? '已验证' : '—'}）</span> : '—';
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
              <button className="btn-sm" onClick={() => approve(r.id)}>批准</button>
              <button className="btn-sm btn-danger" onClick={() => reject(r.id)}>驳回</button>
            </>
          )}
          {r.status === 'approved' && (
            <>
              <input
                className="deploy-target"
                value={deployTarget}
                onChange={(e) => setDeployTarget(e.target.value)}
                placeholder="绑定ID（留空自动选择）"
              />
              <button className="btn-sm btn-primary" onClick={() => deploy(r)} disabled={deployingId === r.id}>
                {deployingId === r.id ? '部署中…' : '部署'}
              </button>
            </>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="变更中心"
        description="提案 → 审批（职责分离）→ 发布 → 读回验证 → effective（§14/§19.3；部署目标默认活沙箱 siq-as-live）"
        connection={status}
        connectionError={error}
      />
      {actionError && <p className="sync-err">{actionError}</p>}
      {status === 'disconnected' ? (
        <DisconnectedNotice error={error} onRetry={refresh} />
      ) : (
        <SimpleTable columns={columns} rows={rows} rowKey={(r) => r.id} />
      )}
    </div>
  );
}
