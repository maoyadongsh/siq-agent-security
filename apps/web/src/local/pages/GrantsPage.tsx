import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { localApi } from '../api';
import type { Grant } from '../types';
import { useLocalSession } from '../session';
import { grantTag } from '../format';

export default function GrantsPage() {
  const { actorId, setActorId } = useLocalSession();
  const [rows, setRows] = useState<Grant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Grant | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    localApi
      .grants()
      .then((data) => {
        setRows(data.grants ?? []);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
  }, []);

  const act = (id: string, action: string, extra: Record<string, unknown> = {}) => {
    setMsg(null);
    localApi
      .grantAction(id, action, { actor_id: actorId, channel: 'console', ...extra })
      .then((res) => {
        setSelected(res.grant);
        setMsg(`${res.grant.grant_id} → ${res.grant.status}`);
        load();
      })
      .catch((err: unknown) => setMsg(err instanceof Error ? err.message : '操作失败'));
  };

  const columns: TableColumn<Grant>[] = [
    { key: 'id', header: 'Grant', render: (r) => <span className="mono">{r.grant_id}</span> },
    { key: 'plat', header: '平台', render: (r) => r.platform },
    {
      key: 'st',
      header: '状态',
      render: (r) => <span className={grantTag(r.status)}>{r.status}</span>,
    },
    { key: 'sub', header: '主体', render: (r) => r.subject?.id },
  ];

  const unresolved = (selected?.overlap_conflicts ?? []).filter((o) => o.resolution === 'unresolved');
  const staticUnavailable = selected?.desired_policy_ref?.static_domains_unavailable ?? [];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="permissions"
        title="签发"
        description="只有人工批准能让 grant 生效路径往前走。filesystem/process 永不标 effective。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
      />
      <div className="card">
        <div className="field">
          <label htmlFor="actor">批准人（人工 actor_id）</label>
          <input id="actor" value={actorId} onChange={(e) => setActorId(e.target.value)} />
        </div>
        <SimpleTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.grant_id}
          emptyText="还没有 grant。从智能体详情对非隔离 Skill 起草签发。"
          onRowClick={setSelected}
        />
      </div>
      {selected ? (
        <div className="card">
          <h2>
            {selected.grant_id} <span className={grantTag(selected.status)}>{selected.status}</span>
          </h2>
          <p className="page-desc">
            {selected.platform} · {selected.subject?.type}:{selected.subject?.id}
          </p>
          {unresolved.length > 0 ? (
            <div className="notice" role="status">
              <p className="notice-title">未解决的权限重叠，批准前必须人工确认</p>
              {(selected.overlap_conflicts ?? []).map((o, i) =>
                o.resolution === 'unresolved' ? (
                  <p key={`${o.domain}-${i}`} className="notice-detail">
                    {o.domain}: {o.fact_ids.join(', ')}{' '}
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => act(selected.grant_id, 'resolve-overlap', { index: i })}
                    >
                      确认为人工决议
                    </button>
                  </p>
                ) : null,
              )}
            </div>
          ) : null}
          {staticUnavailable.length > 0 ? (
            <p className="page-desc">
              静态域不可 effective：{staticUnavailable.join(', ')}（不调用 OpenShell create_generation）。
            </p>
          ) : null}
          <div className="toolbar">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => act(selected.grant_id, 'approve')}
              disabled={selected.status !== 'pending_approval'}
            >
              批准
            </button>
            <button type="button" className="btn" onClick={() => act(selected.grant_id, 'deploy')}>
              标记已部署
            </button>
            <button type="button" className="btn" onClick={() => act(selected.grant_id, 'reject')}>
              拒绝
            </button>
            <button type="button" className="btn" onClick={() => act(selected.grant_id, 'revoke')}>
              吊销
            </button>
          </div>
          {msg ? <p className="page-desc">{msg}</p> : null}
          <h3>事实</h3>
          <ul className="page-desc">
            {(selected.facts ?? []).map((f) => (
              <li key={f.fact_id}>
                {f.domain}:{f.action} {f.resource?.value} · {f.state}/{f.effect}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
