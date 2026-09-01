/**
 * 策略中心（§20.1）：真实 /policies 列表 + 最小创建表单（selector/网络端点/执行档位）。
 * 创建 → 变更单 → 审批 → 部署 的闭环入口在「变更中心」。
 */
import { useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { PolicyRow } from '@/api/types';

const PLACEHOLDER_POLICIES: PolicyRow[] = [];

const MODE_LABELS: Record<string, string> = {
  audit_only: '仅审计',
  warn: '告警',
  block: '阻断',
};

const columns: TableColumn<PolicyRow>[] = [
  { key: 'name', header: '名称', render: (p) => p.name },
  { key: 'version', header: '版本', render: (p) => `v${p.version}` },
  {
    key: 'enforcement_mode',
    header: '执行档位',
    render: (p) => <span className={`state-tag ${p.enforcement_mode === 'block' ? 'effective' : ''}`}>{MODE_LABELS[p.enforcement_mode] ?? p.enforcement_mode}</span>,
  },
  { key: 'status', header: '状态', render: (p) => p.status },
  {
    key: 'unsupported_by_backend',
    header: '未覆盖项（显式）',
    render: (p) => (p.unsupported_by_backend.length ? p.unsupported_by_backend.join('；') : '—'),
  },
  { key: 'selector', header: '选择器', render: (p) => JSON.stringify(p.selector.agent_ids) },
  { key: 'updated_at', header: '更新时间', render: (p) => p.updated_at },
];

export default function PoliciesPage() {
  const { rows, status, error, refresh } = useApiList<PolicyRow>('/policies', PLACEHOLDER_POLICIES);
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

  return (
    <div>
      <PageHeader
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
      ) : (
        <SimpleTable columns={columns} rows={rows} rowKey={(p) => p.id} />
      )}
    </div>
  );
}
