/**
 * 权限视图（§20.2 + ENT-014-UI）：既有权限事实的只读可视化与组合筛选。
 * - 五态概览/筛选/详情/有效期提示见 components/permission-facts/；
 * - 计数只统计已加载记录，不冒充组织全量；加载与断连时不展示伪零值；
 * - effective 仅是后端事实层级，不宣称阻断已验证；
 * - 期望网络权限申请为独立管理区，按实际权限显示；申请不改变事实、不代表已撤权；
 * - 保留既有 OpenShell 同步 / 漂移检查 / 声明与有效 Diff 操作（不改其语义，本页只读流程不产生写请求）。
 */
import { useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import PermissionFactsOverview from '@/components/permission-facts/PermissionFactsOverview';
import PermissionFactsFilters from '@/components/permission-facts/PermissionFactsFilters';
import PermissionFactsList from '@/components/permission-facts/PermissionFactsList';
import NetworkPolicyGovernance from '@/components/batch-deployment/NetworkPolicyGovernance';
import {
  EMPTY_FILTERS,
  filterPermissionFacts,
  type PermissionFactFilters,
} from '@/components/permission-facts/permissionFacts';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { Environment, PermissionFactRow } from '@/api/types';

const PLACEHOLDER_PERMISSIONS: PermissionFactRow[] = [];

export default function PermissionsPage() {
  const {
    rows,
    status,
    error,
    refresh,
    coverageText,
    hasMore,
    loadingMore,
    loadMore,
  } = useApiList<PermissionFactRow>(
    '/permissions',
    PLACEHOLDER_PERMISSIONS,
  );
  const environments = useApiList<Environment>('/environments', []);
  const [environmentId, setEnvironmentId] = useState('');
  const [filters, setFilters] = useState<PermissionFactFilters>({ ...EMPTY_FILTERS });
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [driftChecking, setDriftChecking] = useState(false);
  const [driftMessage, setDriftMessage] = useState<string | null>(null);
  const [diffChecking, setDiffChecking] = useState(false);
  const [diffMessage, setDiffMessage] = useState<string | null>(null);
  const [diffDetail, setDiffDetail] = useState<Awaited<ReturnType<typeof api.permissionsDiff>> | null>(null);

  const visible = status === 'connected' ? filterPermissionFacts(rows, filters) : [];

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
        icon="permissions"
        title="权限视图"
        description="按权限域与权威来源区分声明、推断、观测、生效与未知状态。"
        connection={status}
        connectionError={error}
      />

      <div className="permissions-toolbar">
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

      <NetworkPolicyGovernance />

      {status === 'disconnected' ? (
        <DisconnectedNotice error={error} onRetry={refresh} />
      ) : status === 'loading' ? (
        <p className="muted-text" role="status">
          正在加载权限事实…加载完成前不展示计数或列表。
        </p>
      ) : (
        <>
          <PermissionFactsOverview rows={rows} />
          <PermissionFactsFilters rows={rows} filters={filters} onChange={setFilters} />
          <p className="pf-match-line" role="status">
            匹配 {visible.length} 条 / 已加载 {rows.length} 条。
            {hasMore ? '存在更多分页未加载，统计与筛选仅覆盖已加载数据。' : null}
          </p>
          {coverageText ? (
            <p className="list-coverage" role="status">
              {coverageText}
            </p>
          ) : null}
          {rows.length === 0 ? (
            <p className="muted-text">
              后端成功返回空列表：当前没有权限事实记录。可点击「同步 OpenShell
              有效策略」从真实网关拉取（网关不可达时 fail-closed，不会显示空权限冒充安全状态）。
            </p>
          ) : visible.length === 0 ? (
            <p className="muted-text" role="status">
              当前筛选条件下无匹配项（已加载 {rows.length} 条中 0 条匹配）。
              <button type="button" className="btn-sm" onClick={() => setFilters({ ...EMPTY_FILTERS })}>
                清除筛选
              </button>
            </p>
          ) : (
            <PermissionFactsList rows={visible} />
          )}
          {error ? (
            <p className="sync-err" role="alert">
              {error}（已保留此前成功加载的数据，不代表全部加载成功）
            </p>
          ) : null}
          {hasMore ? (
            <div className="list-more">
              <button
                type="button"
                className="btn-sm"
                disabled={loadingMore}
                onClick={() => loadMore()}
              >
                {loadingMore ? '加载中…' : '加载更多'}
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
