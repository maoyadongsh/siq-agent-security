import { useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { AgentAsset } from '@/api/types';

/** 控制面不可达时的安全示例数据；已连接时由 GET /agents 覆盖 */
const PLACEHOLDER_AGENTS: AgentAsset[] = [
  {
    id: 'agt-01h2kd93nf',
    name: 'siq_legal_advisor',
    role: 'contract-review',
    framework: 'hermes',
    status: 'managed',
    system_id: null,
    owner_user_id: 'u-admin',
    source_type: 'hermes_profile',
    source_locator: 'hermes://legal@v1',
    updated_at: '2026-08-12T09:30:00Z',
  },
  {
    id: 'agt-02k8w1b3m7',
    name: 'ops_incident_responder',
    role: 'incident-response',
    framework: 'openclaw',
    status: 'confirmed',
    system_id: null,
    owner_user_id: null,
    source_type: 'process_list',
    source_locator: 'proc://incident@v1',
    updated_at: '2026-08-08T11:02:00Z',
  },
  {
    id: 'agt-04r7t2y8j5',
    name: 'finance_reporting_bot',
    role: 'reporting',
    framework: 'hermes',
    status: 'managed',
    system_id: null,
    owner_user_id: 'u-admin',
    source_type: 'docker',
    source_locator: 'docker://finance-reporting:1.2.0',
    updated_at: '2026-06-18T08:05:00Z',
  },
];

/** placeholder 候选（联调后由 /candidates 返回：status ∈ candidate|needs_review） */
const PLACEHOLDER_CANDIDATES: AgentAsset[] = [
  {
    id: 'agt-03q4z9p6c2',
    name: 'data_analyst_ghost',
    role: null,
    framework: 'unknown',
    status: 'needs_review',
    system_id: null,
    owner_user_id: null,
    source_type: 'process_list',
    source_locator: 'proc://analyst@v2',
    updated_at: '2026-08-10T23:47:00Z',
  },
  {
    id: 'agt-05m2n8v4d1',
    name: 'code_review_bot',
    role: null,
    framework: 'openclaw',
    status: 'candidate',
    system_id: null,
    owner_user_id: null,
    source_type: 'docker',
    source_locator: 'docker://code-review:latest',
    updated_at: '2026-08-13T02:18:00Z',
  },
];

const statusTag: Record<string, string> = {
  managed: 'tag-ok',
  confirmed: 'tag-ok',
  stale: 'tag-warn',
  candidate: 'tag-warn',
  needs_review: 'tag-warn',
  dismissed: 'tag-err',
  retired: '',
};

const agentColumns: TableColumn<AgentAsset>[] = [
  {
    key: 'name',
    header: '名称',
    render: (a) => <Link to={`/agents/${a.id}`}>{a.name}</Link>,
  },
  { key: 'role', header: '角色', render: (a) => a.role ?? '—' },
  {
    key: 'status',
    header: '状态',
    render: (a) => (
      <span className={`tag ${statusTag[a.status] ?? ''}`}>{a.status}</span>
    ),
  },
  { key: 'framework', header: '框架', render: (a) => a.framework },
  { key: 'updated_at', header: '更新时间', render: (a) => a.updated_at },
];

type TabKey = 'agents' | 'candidates';

export default function AgentsPage() {
  const [tab, setTab] = useState<TabKey>('agents');
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);

  const agents = useApiList<AgentAsset>('/agents', PLACEHOLDER_AGENTS);

  /** 智能扫描：标准安全范围一次下发（hermes profiles / OpenClaw 配置 / docker 标签）。 */
  const runSmartScan = async () => {
    setScanning(true);
    setScanError(null);
    setScanMessage(null);
    try {
      const envs = await api.listEnvironments();
      const envId = envs[0]?.id;
      if (!envId) {
        setScanError('没有可用环境，无法下发扫描');
        return;
      }
      const result = await api.smartScan(envId);
      const names = result.tasks.map((t) => t.connector).join('、');
      setScanMessage(`已下发 ${result.tasks.length} 个扫描任务（${names}）；本机 Edge 执行后候选将自动更新`);
      if (result.note) setScanError(result.note);
      // 给 Edge 一点执行时间后刷新候选
      setTimeout(() => {
        agents.refresh();
        candidates.refresh();
      }, 2500);
    } catch (err) {
      setScanError(err instanceof ApiError ? err.message : '扫描失败');
    } finally {
      setScanning(false);
    }
  };

  const candidates = useApiList<AgentAsset>('/candidates', PLACEHOLDER_CANDIDATES);

  const active = tab === 'agents' ? agents : candidates;

  /** 执行写操作；成功返回 true，失败时记录 actionError 并返回 false */
  const runAction = async (fn: () => Promise<unknown>): Promise<boolean> => {
    setActionError(null);
    try {
      await fn();
      return true;
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '操作失败');
      return false;
    }
  };

  /** 确认候选：prompt 输入 role / owner（均可选，回车跳过）；成功后候选移入资产列表 */
  const handleConfirm = async (c: AgentAsset) => {
    const role = window.prompt(
      `确认候选「${c.name}」为纳管资产\n输入业务角色（可选，直接回车跳过）：`,
    );
    if (role === null) return; // 取消
    const owner = window.prompt('输入负责人 user id（可选，直接回车跳过）：');
    if (owner === null) return; // 取消

    setBusyId(c.id);
    const ok = await runAction(() =>
      api.confirmCandidate(c.id, {
        role: role.trim() || undefined,
        owner_user_id: owner.trim() || undefined,
      }),
    );
    setBusyId(null);

    if (ok) {
      candidates.mutate((rows) => rows.filter((r) => r.id !== c.id));
      agents.refresh();
    }
  };

  /** 驳回候选：prompt 输入原因（必填） */
  const handleDismiss = async (c: AgentAsset) => {
    const reason = window.prompt(`驳回候选「${c.name}」\n输入驳回原因（必填）：`);
    if (reason === null || reason.trim() === '') return;

    setBusyId(c.id);
    const ok = await runAction(() => api.dismissCandidate(c.id, { reason: reason.trim() }));
    setBusyId(null);

    if (ok) {
      candidates.mutate((rows) => rows.filter((r) => r.id !== c.id));
    }
  };

  const candidateColumns: TableColumn<AgentAsset>[] = [
    {
      key: 'name',
      header: '名称',
      render: (c) => <Link to={`/agents/${c.id}`}>{c.name}</Link>,
    },
    { key: 'role', header: '角色', render: (c) => c.role ?? '—' },
    { key: 'framework', header: '框架', render: (c) => c.framework },
    {
      key: 'source',
      header: '来源',
      render: (c) => (
        <span title={c.source_locator ?? undefined}>
          {c.source_type ?? '—'}
        </span>
      ),
    },
    {
      key: 'status',
      header: '状态',
      render: (c) => (
        <span className={`tag ${statusTag[c.status] ?? ''}`}>{c.status}</span>
      ),
    },
    { key: 'updated_at', header: '发现时间', render: (c) => c.updated_at },
    {
      key: 'actions',
      header: '操作',
      render: (c) => (
        <span className="row-actions">
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            disabled={busyId === c.id}
            onClick={() => void handleConfirm(c)}
          >
            确认
          </button>
          <button
            type="button"
            className="btn btn-sm btn-danger"
            disabled={busyId === c.id}
            onClick={() => void handleDismiss(c)}
          >
            驳回
          </button>
        </span>
      ),
    },
  ];

  return (
    <section>
      <PageHeader
        icon="agents"
        title="智能体资产"
        description="集中管理已发现与已纳管的智能体资产，并在候选视图中完成确认或驳回。"
        connection={active.status}
        connectionError={active.error}
        actions={
          <div className="scan-actions">
            <button className="btn-scan" onClick={runSmartScan} disabled={scanning}>
              <span className="scan-icon">
                <Icon name={scanning ? 'loading' : 'scan'} size={15} className={scanning ? 'icon-spin' : undefined} />
              </span>
              {scanning ? '扫描下发中…' : '智能扫描'}
            </button>
            <button className="btn-scan btn-scan-ghost" onClick={() => { agents.refresh(); candidates.refresh(); }} title="重新拉取资产与候选">
              <span className="scan-icon">
                <Icon name="refresh" size={14} />
              </span>
              刷新
            </button>
          </div>
        }
      />

      {(scanMessage || scanError) && (
        <div className="scan-result">
          {scanMessage && <p className="sync-ok">{scanMessage}</p>}
          {scanError && <p className="sync-err">{scanError}</p>}
        </div>
      )}
      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'agents'}
          className={`tab-btn${tab === 'agents' ? ' active' : ''}`}
          onClick={() => setTab('agents')}
        >
          已纳管（{agents.rows.length}）
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'candidates'}
          className={`tab-btn${tab === 'candidates' ? ' active' : ''}`}
          onClick={() => setTab('candidates')}
        >
          发现候选（{candidates.rows.length}）
        </button>
      </div>
      {actionError ? (
        <p className="action-error" role="alert">
          操作失败：{actionError}
        </p>
      ) : null}
      {active.status === 'disconnected' ? (
        <DisconnectedNotice error={active.error} onRetry={active.reload} />
      ) : null}
      {tab === 'agents' ? (
        <SimpleTable
          columns={agentColumns}
          rows={agents.rows}
          rowKey={(a) => a.id}
        />
      ) : (
        <SimpleTable
          columns={candidateColumns}
          rows={candidates.rows}
          rowKey={(c) => c.id}
          emptyText="暂无待评审候选"
        />
      )}
    </section>
  );
}
