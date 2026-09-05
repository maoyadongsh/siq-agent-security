import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { localApi } from '../api';
import type { LedgerFinding } from '../types';
import { useLocalSession } from '../session';

function sevTag(sev: string): string {
  if (sev === 'critical' || sev === 'high') return 'tag tag-err';
  if (sev === 'medium') return 'tag tag-warn';
  if (sev === 'low') return 'tag tag-info';
  return 'tag';
}

export default function FindingsPage() {
  const { actorId } = useLocalSession();
  const [rows, setRows] = useState<LedgerFinding[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reason, setReason] = useState('');
  const [until, setUntil] = useState('');
  const [msg, setMsg] = useState<string | null>(null);

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

  const columns: TableColumn<LedgerFinding>[] = [
    {
      key: 'sev',
      header: '严重度',
      render: (r) => <span className={sevTag(r.severity)}>{r.severity}</span>,
    },
    { key: 'rule', header: '规则', render: (r) => r.rule_id },
    { key: 'skill', header: 'Skill', render: (r) => r.skill_name || '—' },
    { key: 'disp', header: '处置', render: (r) => r.disposition },
    { key: 'path', header: '位置', render: (r) => r.path || '—' },
    {
      key: 'st',
      header: '状态',
      render: (r) => r.status,
    },
    { key: 'src', header: '来源', render: (r) => r.source || 'admission' },
    {
      key: 'adm',
      header: '准入 ID',
      render: (r) => <span className="mono">{r.admission_id || r.subject_ref || '—'}</span>,
    },
    {
      key: 'act',
      header: '',
      render: (r) =>
        r.status === 'accepted' ? (
          '已接受'
        ) : (
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              if (!reason.trim() || !until.trim()) {
                setMsg('接受需要原因和到期（RFC3339）');
                return;
              }
              localApi
                .acceptFinding(r.finding_id, { actor_id: actorId, reason: reason.trim(), until: until.trim() })
                .then(() => {
                  setMsg('已接受');
                  load();
                })
                .catch((err: unknown) => setMsg(err instanceof Error ? err.message : '接受失败'));
            }}
          >
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
      {msg ? <p className="page-desc">{msg}</p> : null}
      <div className="toolbar">
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="acc-reason">接受原因</label>
          <input id="acc-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="acc-until">到期（RFC3339）</label>
          <input id="acc-until" value={until} onChange={(e) => setUntil(e.target.value)} placeholder="2026-12-31T00:00:00Z" />
        </div>
      </div>
      <div className="card">
        <SimpleTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.finding_id}
          emptyText={loading ? '加载中…' : '暂无 finding。准入扫描或漂移检测后会出现。'}
        />
      </div>
    </section>
  );
}
