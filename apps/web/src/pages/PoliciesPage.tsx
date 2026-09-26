/**
 * 策略中心（§20.1 + ENT-018-POLICIES-UI）：期望策略只读筛选/详情/分页 + 既有最小创建表单。
 * - 列表展示「期望策略」，不把 block 档位或 status 字符串解释为已生效；
 * - 筛选/详情见 components/policy-explorer/；计数只覆盖已加载记录；
 * - 创建流程（字段、默认档位、必填、载荷、重置/关闭/刷新、失败提示）保持原有语义不变；
 * - 创建 → 变更单 → 审批 → 部署 的闭环入口在「变更中心」。
 */
import { useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import PolicyExplorerFilters from '@/components/policy-explorer/PolicyExplorerFilters';
import PolicyExplorerList from '@/components/policy-explorer/PolicyExplorerList';
import {
  EMPTY_POLICY_FILTERS,
  filterPolicies,
  type PolicyFilters,
} from '@/components/policy-explorer/policyExplorer';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { PolicyRow } from '@/api/types';

const PLACEHOLDER_POLICIES: PolicyRow[] = [];

export default function PoliciesPage() {
  const {
    rows,
    status,
    error,
    refresh,
    coverageText,
    hasMore,
    loadingMore,
    loadMore,
  } = useApiList<PolicyRow>('/policies', PLACEHOLDER_POLICIES);
  const [filters, setFilters] = useState<PolicyFilters>({ ...EMPTY_POLICY_FILTERS });
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [agentId, setAgentId] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [mode, setMode] = useState<'audit_only' | 'warn' | 'block'>('block');
  const [formError, setFormError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const onCreate = async () => {
    setCreating(true);
    setFormError(null);
    try {
      const network = endpoint
        ? [{ endpoint, effect: 'allow', binary_paths: ['/usr/bin/curl'], purpose: 'web-created' }]
        : undefined;
      await api.createPolicy({
        name,
        selector: { agent_ids: [agentId] },
        network,
        enforcement_mode: mode,
      });
      setName('');
      setEndpoint('');
      setShowForm(false);
      refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : '创建失败');
    } finally {
      setCreating(false);
    }
  };

  const visible = status === 'connected' ? filterPolicies(rows, filters) : [];

  return (
    <div>
      <PageHeader
        icon="policies"
        title="策略中心"
        description="统一描述跨执行后端的期望安全状态；编译结果会明确列出后端暂不支持的控制项。"
        connection={status}
        connectionError={error}
      />

      <div className="permissions-toolbar">
        <button className="btn-sm btn-primary" onClick={() => setShowForm((v) => !v)}>
          {showForm ? '收起' : '新建策略'}
        </button>
      </div>

      {showForm && (
        <div className="form-box">
          <label>
            名称
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：财务智能体网络策略" />
          </label>
          <label>
            目标资产
            <input value={agentId} onChange={(e) => setAgentId(e.target.value)} placeholder="例如：agt-finance-01" />
          </label>
          <label>
            网络端点（host:port，留空=无网络规则）
            <input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="api.example.com:443" />
          </label>
          <label>
            执行档位
            <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
              <option value="audit_only">仅审计</option>
              <option value="warn">告警</option>
              <option value="block">阻断</option>
            </select>
          </label>
          <button className="btn-sm btn-primary" onClick={onCreate} disabled={creating || !name.trim() || !agentId.trim()}>
            {creating ? '创建中…' : '创建'}
          </button>
          {formError && <span className="sync-err">{formError}</span>}
        </div>
      )}

      {status === 'disconnected' ? (
        <DisconnectedNotice error={error} onRetry={refresh} />
      ) : status === 'loading' ? (
        <p className="muted-text" role="status">
          正在加载策略…加载完成前不展示列表或计数。
        </p>
      ) : (
        <>
          <PolicyExplorerFilters rows={rows} filters={filters} onChange={setFilters} />
          <p className="policy-explorer-match-line" role="status">
            匹配 {visible.length} 条 / 已加载 {rows.length} 条；筛选仅覆盖已加载记录，不代表组织全量。
            {hasMore ? '存在更多分页未加载。' : null}
          </p>
          {coverageText ? (
            <p className="list-coverage" role="status">
              {coverageText}
            </p>
          ) : null}
          {rows.length === 0 ? (
            <p className="muted-text">
              后端成功返回空列表：当前没有期望策略记录。可通过「新建策略」创建（仍需变更审批与部署后才可能生效）。
            </p>
          ) : visible.length === 0 ? (
            <p className="muted-text" role="status">
              当前筛选条件下无匹配项（已加载 {rows.length} 条中 0 条匹配）。
              <button type="button" className="btn-sm" onClick={() => setFilters({ ...EMPTY_POLICY_FILTERS })}>
                清除筛选
              </button>
            </p>
          ) : (
            <PolicyExplorerList rows={visible} />
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
