import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { localApi } from '../api';
import type { LedgerFinding } from '../types';
import { useLocalSession } from '../session';
import {
  dispositionLabel,
  findingStatusLabel,
  findingStatusTag,
  severityLabel,
  severityTag,
} from '../format';

type StatusFilter = 'open' | 'accepted' | 'all';

const TABS: { id: StatusFilter; label: string }[] = [
  { id: 'open', label: '待处理' },
  { id: 'accepted', label: '已接受' },
  { id: 'all', label: '全部' },
];

export default function FindingsPage() {
  const { actorId } = useLocalSession();
  const [rows, setRows] = useState<LedgerFinding[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reason, setReason] = useState('');
  const [until, setUntil] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [msgErr, setMsgErr] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('open');

  const load = () => {
    setLoading(true);
    localApi
      .findings()
      .then((data) => {
        setRows(data.findings ?? []);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setRows([]);
        setError(err instanceof Error ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
  }, []);

  const accept = (findingId: string) => {
    if (!reason.trim() || !until.trim()) {
      setMsg('接受需要原因和到期（RFC3339）');
      setMsgErr(true);
      return;
    }
    localApi
      .acceptFinding(findingId, { actor_id: actorId, reason: reason.trim(), until: until.trim() })
      .then(() => {
        setMsg('已接受');
        setMsgErr(false);
        load();
      })
      .catch((err: unknown) => {
        setMsg(err instanceof Error ? err.message : '接受失败');
        setMsgErr(true);
      });
  };

  const visible =
    statusFilter === 'all' ? rows : rows.filter((r) => (r.status || 'open') === statusFilter);
  const openCount = rows.filter((r) => (r.status || 'open') === 'open').length;
  const acceptedCount = rows.length - openCount;
  const tabCount = (id: StatusFilter) =>
    id === 'open' ? openCount : id === 'accepted' ? acceptedCount : rows.length;

  const columns: TableColumn<LedgerFinding>[] = [
    {
      key: 'sev',
      header: '严重度',
      render: (r) => (
        <span className={severityTag(r.severity)} title={r.severity}>
          {severityLabel(r.severity)}
        </span>
      ),
    },
    { key: 'rule', header: '规则', render: (r) => r.rule_id },
    { key: 'skill', header: 'Skill', render: (r) => r.skill_name || '—' },
    {
      key: 'disp',
      header: '处置',
      render: (r) => <span title={r.disposition}>{dispositionLabel(r.disposition)}</span>,
    },
    {
      key: 'path',
      header: '位置',
      render: (r) =>
        r.path ? (
          <span className="mono cell-ellipsis" title={r.path}>
            {r.path}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'st',
      header: '状态',
      render: (r) => (
        <span className={findingStatusTag(r.status)}>{findingStatusLabel(r.status)}</span>
      ),
    },
    { key: 'src', header: '来源', render: (r) => <span className="cell-nowrap">{r.source || 'admission'}</span> },
    {
      key: 'adm',
      header: '准入 ID',
      render: (r) => (
        <span className="mono cell-ellipsis" title={r.admission_id || r.subject_ref || ''}>
          {r.admission_id || r.subject_ref || '—'}
        </span>
      ),
    },
    {
      key: 'act',
      header: '',
      render: (r) =>
        r.status === 'accepted' ? (
          '已接受'
        ) : (
          <button type="button" className="btn btn-sm" onClick={() => accept(r.finding_id)}>
            接受
          </button>
        ),
    },
  ];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="findings"
        title="风险中心"
        description="准入扫描与漂移 finding。接受须填写原因和到期；到期后下次刷新视为 open。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
        actions={
          <button type="button" className="btn btn-sm" onClick={load}>
            <Icon name="refresh" size={14} /> 刷新
          </button>
        }
      />
      {error ? (
        <div className="notice" role="status">
          <p className="notice-title">加载失败</p>
          <p className="notice-detail">{error}</p>
        </div>
      ) : null}
      <div className="tabs" role="tablist" aria-label="finding 状态筛选">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={statusFilter === tab.id}
            className={`tab-btn${statusFilter === tab.id ? ' active' : ''}`}
            onClick={() => setStatusFilter(tab.id)}
          >
            {tab.label}（{tabCount(tab.id)}）
          </button>
        ))}
      </div>
      {statusFilter === 'open' ? (
        <div className="toolbar">
          <div className="field field-flush">
            <label htmlFor="acc-reason">接受原因</label>
            <input id="acc-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="field field-flush">
            <label htmlFor="acc-until">到期（RFC3339）</label>
            <input
              id="acc-until"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              placeholder="2026-12-31T00:00:00Z"
            />
          </div>
        </div>
      ) : null}
      {msg ? (
        msgErr ? (
          <p className="action-error" role="alert">
            {msg}
          </p>
        ) : (
          <p className="sync-ok">{msg}</p>
        )
      ) : null}
      <div className="card">
        <SimpleTable
          columns={columns}
          rows={visible}
          rowKey={(r) => r.finding_id}
          emptyText={
            loading
              ? '加载中…'
              : error
                ? '决策 API 不可达，暂时无法读取 finding。'
                : statusFilter === 'accepted'
                  ? '暂无已接受的 finding。'
                  : statusFilter === 'open'
                    ? '暂无待处理 finding。准入扫描或漂移检测后会出现。'
                    : '暂无 finding。准入扫描或漂移检测后会出现。'
          }
        />
      </div>
    </section>
  );
}
