/**
 * 运行时绑定管理（R-6，对齐 apps/control-api/app/routers/bindings.py）：
 * 绑定登记 = 声明"该租户的某 agent 实例在某环境下对应某后端运行时目标"，
 * 部署只接受 active 绑定并据此解析目标——没有这一页，变更中心部署时只能
 * 依赖后端已有数据，运维无法自助登记/吊销，是策略落地链路上的断点。
 *
 * backend_target_id 登记后不可变：变更目标 = 吊销旧绑定 + 登记新绑定（全量审计）。
 */
import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { AgentAsset, AgentInstance, Environment, RuntimeBindingRow } from '@/api/types';

const PLACEHOLDER_BINDINGS: RuntimeBindingRow[] = [];

/** 只有已纳管资产才可能有可绑定的运行时实例（candidate/needs_review/dismissed 排除） */
const BINDABLE_ASSET_STATUS = new Set(['confirmed', 'managed', 'stale']);

const statusTag: Record<RuntimeBindingRow['status'], string> = {
  active: 'tag-ok',
  revoked: 'tag-err',
};

export default function RuntimeBindingsPage() {
  const bindings = useApiList<RuntimeBindingRow>('/runtime-bindings', PLACEHOLDER_BINDINGS);

  const [showForm, setShowForm] = useState(false);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [agents, setAgents] = useState<AgentAsset[]>([]);
  const [instances, setInstances] = useState<AgentInstance[]>([]);
  const [instancesLoading, setInstancesLoading] = useState(false);

  const [environmentId, setEnvironmentId] = useState('');
  const [agentId, setAgentId] = useState('');
  const [instanceId, setInstanceId] = useState('');
  const [backend, setBackend] = useState('openshell-cli');
  const [backendTargetId, setBackendTargetId] = useState('');
  const [backendVersion, setBackendVersion] = useState('');
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // 展开表单时才拉取环境/资产下拉数据，避免页面首次加载即多打三个请求
  useEffect(() => {
    if (!showForm) return;
    api.listEnvironments().then(setEnvironments).catch(() => setEnvironments([]));
    api.listAgents().then(setAgents).catch(() => setAgents([]));
  }, [showForm]);

  // 资产 → 实例级联：切换资产后重置已选实例，避免提交上一个资产的实例 ID
  useEffect(() => {
    setInstanceId('');
    if (!agentId) {
      setInstances([]);
      return;
    }
    setInstancesLoading(true);
    api
      .getAgentInstances(agentId)
      .then(setInstances)
      .catch(() => setInstances([]))
      .finally(() => setInstancesLoading(false));
  }, [agentId]);

  const resetForm = () => {
    setEnvironmentId('');
    setAgentId('');
    setInstanceId('');
    setBackend('openshell-cli');
    setBackendTargetId('');
    setBackendVersion('');
    setFormError(null);
  };

  const onCreate = async () => {
    setCreating(true);
    setFormError(null);
    try {
      await api.createRuntimeBinding({
        environment_id: environmentId,
        agent_instance_id: instanceId,
        backend,
        backend_target_id: backendTargetId,
        ...(backendVersion.trim() ? { attestation: { backend_version: backendVersion.trim() } } : {}),
      });
      resetForm();
      setShowForm(false);
      bindings.refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : '登记失败');
    } finally {
      setCreating(false);
    }
  };

  const onRevoke = async (b: RuntimeBindingRow) => {
    if (
      !window.confirm(
        `吊销运行时绑定「${b.backend}:${b.backend_target_id}」？\n` +
          '吊销后不可恢复（需重新登记新绑定），且依赖该绑定的部署会被拦截。',
      )
    ) {
      return;
    }
    setBusyId(b.id);
    setActionError(null);
    try {
      await api.revokeRuntimeBinding(b.id, 'web-console-manual-revoke');
      bindings.refresh();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '吊销失败');
    } finally {
      setBusyId(null);
    }
  };

  const bindableAgents = agents.filter((a) => BINDABLE_ASSET_STATUS.has(a.status));

  const columns: TableColumn<RuntimeBindingRow>[] = [
    { key: 'id', header: '绑定 ID', render: (b) => <span className="mono">{b.id}</span> },
    { key: 'asset_id', header: '资产', render: (b) => <span className="mono">{b.asset_id}</span> },
    {
      key: 'agent_instance_id',
      header: '实例',
      render: (b) => <span className="mono">{b.agent_instance_id}</span>,
    },
    { key: 'environment_id', header: '环境', render: (b) => <span className="mono">{b.environment_id}</span> },
    { key: 'backend', header: '后端', render: (b) => b.backend },
    {
      key: 'backend_target_id',
      header: '运行时目标',
      render: (b) => <span className="mono">{b.backend_target_id}</span>,
    },
    {
      key: 'status',
      header: '状态',
      render: (b) => <span className={`tag ${statusTag[b.status]}`}>{b.status}</span>,
    },
    {
      key: 'created_at',
      header: '登记 / 吊销时间',
      render: (b) => (
        <span title={b.revoked_at ?? undefined}>
          {b.created_at}
          {b.revoked_at ? ` → ${b.revoked_at}` : ''}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '操作',
      render: (b) =>
        b.status === 'active' ? (
          <span className="row-actions">
            <button
              type="button"
              className="btn btn-sm btn-danger"
              disabled={busyId === b.id}
              onClick={() => void onRevoke(b)}
            >
              吊销
            </button>
          </span>
        ) : (
          <span className="muted-text">已终态</span>
        ),
    },
  ];

  return (
    <section>
      <PageHeader
        icon="bindings"
        title="运行时绑定"
        description='声明"某 agent 实例在某环境下对应某后端运行时目标"：部署只接受 active 绑定并据此解析目标；backend_target_id 登记后不可变，变更目标须吊销旧绑定并登记新绑定（全量审计）。'
        connection={bindings.status}
        connectionError={bindings.error}
      />

      <div className="permissions-toolbar">
        <button className="btn-sm btn-primary" onClick={() => setShowForm((v) => !v)}>
          {showForm ? '收起' : '登记绑定'}
        </button>
      </div>

      {showForm && (
        <div className="form-box">
          <label>
            环境
            <select value={environmentId} onChange={(e) => setEnvironmentId(e.target.value)}>
              <option value="">请选择环境</option>
              {environments.map((env) => (
                <option key={env.id} value={env.id}>
                  {env.name}（{env.id}）
                </option>
              ))}
            </select>
          </label>
          <label>
            智能体资产（仅显示已纳管资产）
            <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
              <option value="">请选择资产</option>
              {bindableAgents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}（{a.id}）
                </option>
              ))}
            </select>
          </label>
          <label>
            运行时实例
            <select
              value={instanceId}
              onChange={(e) => setInstanceId(e.target.value)}
              disabled={!agentId || instancesLoading}
            >
              <option value="">
                {!agentId ? '先选择资产' : instancesLoading ? '加载中…' : '请选择实例'}
              </option>
              {instances.map((inst) => (
                <option key={inst.id} value={inst.id}>
                  {inst.id}（{inst.runtime} · {inst.status}）
                </option>
              ))}
            </select>
            {agentId && !instancesLoading && instances.length === 0 ? (
              <span className="sync-err">该资产暂无已发现的运行时实例，无法登记绑定</span>
            ) : null}
          </label>
          <label>
            后端类型
            <input value={backend} onChange={(e) => setBackend(e.target.value)} placeholder="openshell-cli" />
          </label>
          <label>
            运行时目标 ID（登记后不可变）
            <input
              value={backendTargetId}
              onChange={(e) => setBackendTargetId(e.target.value)}
              placeholder="sandbox-finance-01"
            />
          </label>
          <label>
            后端版本（attestation，可选）
            <input
              value={backendVersion}
              onChange={(e) => setBackendVersion(e.target.value)}
              placeholder="v0.0.83"
            />
          </label>
          <button
            className="btn-sm btn-primary"
            onClick={onCreate}
            disabled={creating || !environmentId || !instanceId || !backend.trim() || !backendTargetId.trim()}
          >
            {creating ? '登记中…' : '登记'}
          </button>
          {formError && <span className="sync-err">{formError}</span>}
        </div>
      )}

      {actionError ? (
        <p className="action-error" role="alert">
          操作失败：{actionError}
        </p>
      ) : null}

      {bindings.status === 'disconnected' ? (
        <DisconnectedNotice error={bindings.error} onRetry={bindings.reload} />
      ) : (
        <SimpleTable columns={columns} rows={bindings.rows} rowKey={(b) => b.id} emptyText="暂无运行时绑定" />
      )}
    </section>
  );
}
