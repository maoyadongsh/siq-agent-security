import { useState } from 'react';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import { api, ApiError } from '@/api/client';
import type { Finding, FindingSeverity, FindingStatus } from '@/api/types';

/** placeholder 数据（Phase 1；联调后由 /findings 返回） */
const PLACEHOLDER_FINDINGS: Finding[] = [
  {
    id: 'fnd-0001',
    rule_id: 'R-AGENT-001',
    rule_version: 1,
    severity: 'high',
    domain: 'tool',
    asset_id: 'agt-03q4z9p6c2',
    evidence_ids: ['ev-0004', 'ev-0005'],
    impact: '未纳管智能体持有凭据类工具权限',
    remediation: '确认并纳管资产，收敛工具权限',
    status: 'open',
    owner_user_id: null,
    due_at: null,
    risk_acceptance: null,
    first_seen_at: '2026-08-11T06:20:00Z',
    last_seen_at: '2026-08-12T09:30:00Z',
  },
  {
    id: 'fnd-0002',
    rule_id: 'R-AGENT-004',
    rule_version: 2,
    severity: 'critical',
    domain: 'credential',
    asset_id: 'agt-02k8w1b3m7',
    evidence_ids: ['ev-0012'],
    impact: '委托 token 刷新链路异常',
    remediation: '修复 SIQ IAM delegated-token 链路',
    status: 'acknowledged',
    owner_user_id: 'u-admin',
    due_at: null,
    risk_acceptance: null,
    first_seen_at: '2026-08-12T14:12:00Z',
    last_seen_at: '2026-08-12T14:12:00Z',
  },
  {
    id: 'fnd-0003',
    rule_id: 'R-CONN-007',
    rule_version: 1,
    severity: 'low',
    domain: 'control_plane',
    asset_id: null,
    evidence_ids: ['ev-0009'],
    impact: 'Connector 版本落后，缺补丁',
    remediation: '升级 Connector 至最低安全版本',
    status: 'open',
    owner_user_id: null,
    due_at: null,
    risk_acceptance: null,
    first_seen_at: '2026-08-07T03:41:00Z',
    last_seen_at: '2026-08-10T10:00:00Z',
  },
];

const sevTag: Record<FindingSeverity, string> = {
  critical: 'tag-err',
  high: 'tag-err',
  medium: 'tag-warn',
  low: 'tag-info',
  info: '',
};

const statusTag: Record<FindingStatus, string> = {
  open: 'tag-err',
  acknowledged: 'tag-warn',
  resolved: 'tag-ok',
  risk_accepted: 'tag-info',
};

/** 已终态（不可再 acknowledge/resolve） */
const isFinal = (f: Finding) =>
  f.status === 'resolved' || f.status === 'risk_accepted';

export default function FindingsPage() {
  const findings = useApiList<Finding>('/findings', PLACEHOLDER_FINDINGS);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  /** 执行写操作；成功后重新拉取列表与后端同步 */
  const runAction = async (fn: () => Promise<unknown>): Promise<boolean> => {
    setActionError(null);
    try {
      await fn();
      findings.refresh();
      return true;
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '操作失败');
      return false;
    }
  };

  const handleAcknowledge = async (f: Finding) => {
    setBusyId(f.id);
    await runAction(() => api.acknowledgeFinding(f.id));
    setBusyId(null);
  };

  /** 解决不可逆（无 reopen 路径），点击前二次确认 */
  const handleResolve = async (f: Finding) => {
    const evidenceRef = window.prompt('请输入修复证据或工单引用（例如 repair-ticket:SEC-123）');
    if (!evidenceRef) {
      return;
    }
    if (!window.confirm(`解决风险「${f.rule_id}」（${f.impact ?? ''}）？\n解决后不可撤销。`)) {
      return;
    }
    setBusyId(f.id);
    await runAction(() => api.resolveFinding(f.id, evidenceRef));
    setBusyId(null);
  };

  const columns: TableColumn<Finding>[] = [
    {
      key: 'severity',
      header: '级别',
      render: (f) => <span className={`tag ${sevTag[f.severity]}`}>{f.severity}</span>,
    },
    {
      key: 'rule_id',
      header: '规则',
      render: (f) => (
        <span className="mono" title={`v${f.rule_version}`}>
          {f.rule_id}
        </span>
      ),
    },
    { key: 'asset_id', header: '关联资产', render: (f) => f.asset_id ?? '—' },
    { key: 'impact', header: '风险', render: (f) => f.impact ?? '—' },
    {
      key: 'status',
      header: '状态',
      render: (f) => (
        <span className={`tag ${statusTag[f.status]}`}>
          {f.status}
          {f.owner_user_id ? ` · ${f.owner_user_id}` : ''}
        </span>
      ),
    },
    { key: 'first_seen_at', header: '首次发现', render: (f) => f.first_seen_at },
    {
      key: 'actions',
      header: '操作',
      render: (f) => (
        <span className="row-actions">
          {f.status === 'open' ? (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={busyId === f.id}
              onClick={() => void handleAcknowledge(f)}
            >
              确认
            </button>
          ) : null}
          {!isFinal(f) ? (
            <button
              type="button"
              className="btn btn-sm"
              disabled={busyId === f.id}
              onClick={() => void handleResolve(f)}
            >
              解决
            </button>
          ) : null}
          {isFinal(f) ? <span className="muted-text">已终态</span> : null}
        </span>
      ),
    },
  ];

  return (
    <section>
      <PageHeader
        title="风险中心"
        description="汇总规则引擎识别的风险级别、关联资产与处置状态，并支持就地确认和解决。"
        connection={findings.status}
        connectionError={findings.error}
      />
      {actionError ? (
        <p className="action-error" role="alert">
          操作失败：{actionError}
        </p>
      ) : null}
      {findings.status === 'disconnected' ? (
        <DisconnectedNotice error={findings.error} onRetry={findings.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={findings.rows}
        rowKey={(f) => f.id}
      />
    </section>
  );
}
