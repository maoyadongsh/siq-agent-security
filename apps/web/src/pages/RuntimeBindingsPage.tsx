/**
 * 运行时绑定管理（R-6，对齐 apps/control-api/app/routers/bindings.py）：
 * 绑定登记 = 声明"该租户的某 agent 实例在某环境下对应某后端运行时目标"，
 * 部署只接受 active 绑定并据此解析目标——没有这一页，变更中心部署时只能
 * 依赖后端已有数据，运维无法自助登记/吊销，是策略落地链路上的断点。
 *
 * backend_target_id 登记后不可变：变更目标 = 吊销旧绑定 + 登记新绑定（全量审计）。
 *
 * ENT-018-BINDINGS-UI：
 * - 列表支持 AND 组合筛选（状态/后端/环境/文本搜索），仅作用于已加载记录；
 * - 区分 首次加载/成功空/筛选无匹配/首次失败/加载更多失败；
 * - 每条绑定原生 details/summary 展开详情；attestation 不展开、不渲染 tenant_id；
 * - 登记表单按需加载环境/资产/实例，逐项表达 未加载/加载中/成功空/成功有数据/失败；
 * - 切换资产用请求序号（seq）忽略旧实例响应，避免旧实例被误选；
 * - 登记前校验选项已成功加载且当前选择属于本次成功结果（前端仅避免误操作）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import ConfirmDialog from '@/components/ConfirmDialog';
import RuntimeBindingFilters from '@/components/runtime-binding-explorer/RuntimeBindingFilters';
import RuntimeBindingList from '@/components/runtime-binding-explorer/RuntimeBindingList';
import {
  EMPTY_BINDING_FILTERS,
  IDLE_INSTANCE_STATE,
  IDLE_OPTION,
  beginInstanceRequest,
  filterBindings,
  instanceBelongsToCurrentAgent,
  invalidateInstanceRequest,
  optionHasId,
  applyInstanceResponse,
  type BindingFilters,
  type InstanceRequestState,
  type OptionState,
} from '@/components/runtime-binding-explorer/runtimeBindingExplorer';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError, describeApiError } from '@/api/client';
import type { AgentAsset, AgentInstance, Environment, RuntimeBindingRow } from '@/api/types';

const PLACEHOLDER_BINDINGS: RuntimeBindingRow[] = [];

/** 只有已纳管资产才可能有可绑定的运行时实例（candidate/needs_review/dismissed 排除） */
const BINDABLE_ASSET_STATUS = new Set(['confirmed', 'managed', 'stale']);

const DEFAULT_BACKEND = 'openshell-cli';

export default function RuntimeBindingsPage() {
  const bindings = useApiList<RuntimeBindingRow>('/runtime-bindings', PLACEHOLDER_BINDINGS);

  /* ---------------- 列表筛选（仅作用于已加载记录） ---------------- */
  const [filters, setFilters] = useState<BindingFilters>({ ...EMPTY_BINDING_FILTERS });

  /* ---------------- 登记表单 ---------------- */
  const [showForm, setShowForm] = useState(false);
  const [envState, setEnvState] = useState<OptionState<Environment>>(IDLE_OPTION);
  const [agentState, setAgentState] = useState<OptionState<AgentAsset>>(IDLE_OPTION);
  const [instanceState, setInstanceState] = useState<InstanceRequestState>(IDLE_INSTANCE_STATE);

  const [environmentId, setEnvironmentId] = useState('');
  const [agentId, setAgentId] = useState('');
  const [instanceId, setInstanceId] = useState('');
  const [backend, setBackend] = useState(DEFAULT_BACKEND);
  const [backendTargetId, setBackendTargetId] = useState('');
  const [backendVersion, setBackendVersion] = useState('');
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  /** 吊销确认模态目标（替代原生 confirm） */
  const [revokeTarget, setRevokeTarget] = useState<RuntimeBindingRow | null>(null);

  /* 请求序号（ref 为权威来源）：切换/清空/关闭/卸载时递增，使旧响应失效 */
  const envGenRef = useRef(0);
  const agentGenRef = useRef(0);
  const instanceRef = useRef<InstanceRequestState>(IDLE_INSTANCE_STATE);
  /** 实例加载 nonce：针对性重试时递增以重新触发加载（agentId 不变也能重拉） */
  const [instanceNonce, setInstanceNonce] = useState(0);

  const commitInstance = useCallback((next: InstanceRequestState) => {
    instanceRef.current = next;
    setInstanceState(next);
  }, []);

  /* ---------------- 环境 / 资产：打开表单才加载（按需） ---------------- */
  const loadEnvironments = useCallback(() => {
    const gen = ++envGenRef.current;
    setEnvState({ status: 'loading', items: [], error: null });
    api
      .listEnvironments()
      .then((items) => {
        if (gen !== envGenRef.current) return;
        setEnvState({ status: 'ready', items, error: null });
      })
      .catch((err: unknown) => {
        if (gen !== envGenRef.current) return;
        setEnvState({ status: 'error', items: [], error: describeApiError(err, '环境加载失败') });
      });
  }, []);

  const loadAgents = useCallback(() => {
    const gen = ++agentGenRef.current;
    setAgentState({ status: 'loading', items: [], error: null });
    api
      .listAgents()
      .then((items) => {
        if (gen !== agentGenRef.current) return;
        setAgentState({ status: 'ready', items, error: null });
      })
      .catch((err: unknown) => {
        if (gen !== agentGenRef.current) return;
        setAgentState({ status: 'error', items: [], error: describeApiError(err, '资产加载失败') });
      });
  }, []);

  useEffect(() => {
    if (!showForm) {
      // 关闭表单：递增序号使在途响应失效，回到未加载
      envGenRef.current += 1;
      agentGenRef.current += 1;
      setEnvState(IDLE_OPTION);
      setAgentState(IDLE_OPTION);
      return;
    }
    loadEnvironments();
    loadAgents();
    return () => {
      envGenRef.current += 1;
      agentGenRef.current += 1;
    };
  }, [showForm, loadEnvironments, loadAgents]);

  /* ---------------- 资产 → 实例级联（seq 防竞态） ---------------- */
  useEffect(() => {
    let active = true;
    if (!showForm || !agentId) {
      // 清空资产 / 关闭表单：使在途实例响应失效
      commitInstance(invalidateInstanceRequest(instanceRef.current));
      return () => {
        active = false;
      };
    }
    const started = beginInstanceRequest(instanceRef.current, agentId);
    commitInstance(started);
    const seq = started.seq;
    api
      .getAgentInstances(agentId)
      .then((items: AgentInstance[]) => {
        if (!active) return;
        commitInstance(applyInstanceResponse(instanceRef.current, seq, true, items, null));
      })
      .catch((err: unknown) => {
        if (!active) return;
        commitInstance(applyInstanceResponse(instanceRef.current, seq, false, [], describeApiError(err, '实例加载失败')));
      });
    return () => {
      active = false;
    };
    // instanceNonce：针对性重试时递增以重新加载（agentId 不变也能重拉）
  }, [showForm, agentId, instanceNonce, commitInstance]);

  const resetForm = () => {
    setEnvironmentId('');
    setAgentId('');
    setInstanceId('');
    setBackend(DEFAULT_BACKEND);
    setBackendTargetId('');
    setBackendVersion('');
    setFormError(null);
  };

  const bindableAgents = agentState.items.filter((a) => BINDABLE_ASSET_STATUS.has(a.status));

  /* ---------------- 登记前校验（前端仅避免误操作，不替代后端） ---------------- */
  const optionsLoading =
    envState.status === 'loading' || agentState.status === 'loading' || instanceState.status === 'loading';

  const formValidationError = (() => {
    if (creating) return '正在登记中，请勿重复提交';
    if (envState.status !== 'ready') return '环境选项尚未成功加载';
    if (agentState.status !== 'ready') return '资产选项尚未成功加载';
    if (instanceState.status !== 'ready') return '实例选项尚未成功加载';
    if (!optionHasId(envState, environmentId)) return '所选环境不属于当前已加载选项';
    if (agentId === '' || !bindableAgents.some((a) => a.id === agentId)) return '所选资产不属于当前已加载的可绑定选项';
    if (!instanceBelongsToCurrentAgent(instanceState, agentId, instanceId)) return '所选实例不属于当前资产的本次加载结果';
    if (!backend.trim()) return '请填写后端类型';
    if (!backendTargetId.trim()) return '请填写运行时目标 ID';
    return null;
  })();

  const canCreate = !optionsLoading && formValidationError === null;

  const onCreate = async () => {
    if (!canCreate) return;
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

  const onRevoke = async () => {
    const b = revokeTarget;
    if (!b || busyId !== null) return;
    setBusyId(b.id);
    setActionError(null);
    try {
      await api.revokeRuntimeBinding(b.id, 'web-console-manual-revoke');
      setRevokeTarget(null);
      bindings.refresh();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '吊销失败');
    } finally {
      setBusyId(null);
    }
  };

  /* ---------------- 列表派生（仅已加载记录） ---------------- */
  const connected = bindings.status === 'connected';
  const visible = connected ? filterBindings(bindings.rows, filters) : [];

  const renderActions = (b: RuntimeBindingRow) =>
    b.status === 'active' ? (
      <span className="row-actions">
        <button
          type="button"
          className="btn btn-sm btn-danger"
          disabled={busyId === b.id}
          onClick={() => setRevokeTarget(b)}
        >
          吊销
        </button>
      </span>
    ) : (
      <span className="muted-text">{b.status === 'revoked' ? '已终态' : '未知状态，暂不提供操作'}</span>
    );

  return (
    <section className="rb-explorer-root">
      <PageHeader
        icon="bindings"
        title="运行时绑定"
        description='声明"某 agent 实例在某环境下对应某后端运行时目标"：部署只接受 active 绑定并据此解析目标；backend_target_id 登记后不可变，变更目标须吊销旧绑定并登记新绑定（全量审计）。'
        connection={bindings.status}
        connectionError={bindings.error}
      />

      <div className="permissions-toolbar">
        <button className="btn-sm btn-primary" disabled={creating} onClick={() => setShowForm((v) => !v)}>
          {showForm ? '收起' : '登记绑定'}
        </button>
      </div>

      {showForm ? (
        <div className="form-box">
          {/* 环境 */}
          <label>
            环境
            {envState.status === 'ready' ? (
              <select disabled={creating} value={environmentId} onChange={(e) => setEnvironmentId(e.target.value)}>
                <option value="">请选择环境</option>
                {envState.items.map((env) => (
                  <option key={env.id} value={env.id}>
                    {env.name}（{env.id}）
                  </option>
                ))}
              </select>
            ) : (
              <select value="" disabled>
                <option value="">{envState.status === 'loading' ? '加载中…' : '未加载'}</option>
              </select>
            )}
            {envState.status === 'error' ? (
              <span className="rb-explorer-form-err" role="alert">
                环境加载失败：{envState.error}
                <button type="button" className="btn-sm" onClick={() => loadEnvironments()}>
                  重试
                </button>
              </span>
            ) : null}
            {envState.status === 'ready' && envState.items.length === 0 ? (
              <span className="rb-explorer-form-note">后端成功返回空列表：当前没有可用环境。</span>
            ) : null}
          </label>

          {/* 资产 */}
          <label>
            智能体资产（仅显示已纳管资产）
            {agentState.status === 'ready' ? (
              <select
                disabled={creating}
                value={agentId}
                onChange={(e) => {
                  setAgentId(e.target.value);
                  setInstanceId('');
                }}
              >
                <option value="">请选择资产</option>
                {bindableAgents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}（{a.id}）
                  </option>
                ))}
              </select>
            ) : (
              <select value="" disabled>
                <option value="">{agentState.status === 'loading' ? '加载中…' : '未加载'}</option>
              </select>
            )}
            {agentState.status === 'error' ? (
              <span className="rb-explorer-form-err" role="alert">
                资产加载失败：{agentState.error}
                <button type="button" className="btn-sm" onClick={() => loadAgents()}>
                  重试
                </button>
              </span>
            ) : null}
            {agentState.status === 'ready' && bindableAgents.length === 0 ? (
              <span className="rb-explorer-form-note">后端成功返回空列表：当前没有可绑定的已纳管资产。</span>
            ) : null}
          </label>

          {/* 实例 */}
          <label>
            运行时实例
            {instanceState.status === 'ready' ? (
              <select disabled={creating} value={instanceId} onChange={(e) => setInstanceId(e.target.value)}>
                <option value="">请选择实例</option>
                {instanceState.items.map((inst) => (
                  <option key={inst.id} value={inst.id}>
                    {inst.id}（{inst.runtime} · {inst.status}）
                  </option>
                ))}
              </select>
            ) : (
              <select value="" disabled>
                <option value="">
                  {!agentId
                    ? '先选择资产'
                    : instanceState.status === 'loading'
                      ? '加载中…'
                      : instanceState.status === 'error'
                        ? '加载失败'
                        : '未加载'}
                </option>
              </select>
            )}
            {instanceState.status === 'error' ? (
              <span className="rb-explorer-form-err" role="alert">
                实例加载失败：{instanceState.error}
                <button
                  type="button"
                  className="btn-sm"
                  onClick={() => {
                    // 针对性重试：使旧响应失效并重新加载当前资产的实例
                    commitInstance(invalidateInstanceRequest(instanceRef.current));
                    setInstanceNonce((n) => n + 1);
                  }}
                >
                  重试
                </button>
              </span>
            ) : null}
            {instanceState.status === 'ready' && instanceState.items.length === 0 ? (
              <span className="rb-explorer-form-note">该资产暂无已发现的运行时实例，无法登记绑定。</span>
            ) : null}
          </label>

          <label>
            后端类型
            <input disabled={creating} value={backend} onChange={(e) => setBackend(e.target.value)} placeholder="openshell-cli" />
          </label>
          <label>
            运行时目标 ID（登记后不可变）
            <input
              disabled={creating}
              value={backendTargetId}
              onChange={(e) => setBackendTargetId(e.target.value)}
              placeholder="sandbox-finance-01"
            />
          </label>
          <label>
            后端版本（attestation，可选）
            <input disabled={creating} value={backendVersion} onChange={(e) => setBackendVersion(e.target.value)} placeholder="v0.0.83" />
          </label>

          {formValidationError && !optionsLoading ? (
            <span className="rb-explorer-form-note" role="status">
              {formValidationError}
            </span>
          ) : null}

          <button
            className="btn-sm btn-primary"
            onClick={() => void onCreate()}
            disabled={!canCreate}
          >
            {creating ? '登记中…' : '登记'}
          </button>
          {formError ? (
            <span className="sync-err" role="alert">
              {formError}
            </span>
          ) : null}
        </div>
      ) : null}

      {actionError ? (
        <p className="action-error" role="alert">
          操作失败：{actionError}
        </p>
      ) : null}

      {bindings.status === 'disconnected' ? (
        <DisconnectedNotice error={bindings.error} onRetry={bindings.reload} />
      ) : bindings.status === 'loading' ? (
        <p className="muted-text" role="status">
          正在加载运行时绑定…加载完成前不展示列表或计数。零条绑定不代表当前系统安全。
        </p>
      ) : (
        <>
          <RuntimeBindingFilters rows={bindings.rows} filters={filters} onChange={setFilters} />
          <p className="rb-explorer-match-line" role="status">
            匹配 {visible.length} 条 / 已加载 {bindings.rows.length} 条；筛选仅覆盖已加载记录，不代表组织全量。
            {bindings.hasMore ? '存在更多分页未加载。' : null}
          </p>
          {bindings.coverageText ? (
            <p className="list-coverage" role="status">
              {bindings.coverageText}
            </p>
          ) : null}
          {bindings.rows.length === 0 ? (
            <p className="muted-text">
              后端成功返回空列表：当前没有已登记的运行时绑定。零条绑定不等于当前系统安全。
            </p>
          ) : visible.length === 0 ? (
            <p className="muted-text" role="status">
              当前筛选条件下无匹配项（已加载 {bindings.rows.length} 条中 0 条匹配）。
              <button
                type="button"
                className="btn-sm"
                onClick={() => setFilters({ ...EMPTY_BINDING_FILTERS })}
              >
                清除筛选
              </button>
            </p>
          ) : (
            <RuntimeBindingList rows={visible} renderActions={renderActions} />
          )}
          {bindings.error ? (
            <p className="action-error" role="alert">
              {bindings.error}（已保留此前成功加载的数据，不代表全部加载成功）
            </p>
          ) : null}
          {bindings.hasMore ? (
            <div className="list-more">
              <button
                type="button"
                className="btn-sm"
                disabled={bindings.loadingMore}
                onClick={() => bindings.loadMore()}
              >
                {bindings.loadingMore ? '加载中…' : '加载更多'}
              </button>
            </div>
          ) : null}
        </>
      )}

      <ConfirmDialog
        className="rb-explorer-revoke-dialog"
        open={revokeTarget !== null}
        title={`吊销运行时绑定「${revokeTarget?.backend ?? ''}:${revokeTarget?.backend_target_id ?? ''}」`}
        description="吊销后不可恢复（需重新登记新绑定），且依赖该绑定的部署会被拦截。"
        confirmLabel="确认吊销"
        danger
        busy={busyId !== null}
        onConfirm={() => void onRevoke()}
        onClose={() => { if (busyId === null) setRevokeTarget(null); }}
      />
    </section>
  );
}
