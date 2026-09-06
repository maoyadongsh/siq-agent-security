import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { localApi } from '../api';
import type { Grant, GrantFact } from '../types';
import { useLocalSession } from '../session';
import {
  domainLabel,
  factStateLabel,
  factStateTag,
  grantStatusLabel,
  grantTag,
  platformLabel,
} from '../format';

export default function GrantsPage() {
  const { actorId, setActorId } = useLocalSession();
  const [rows, setRows] = useState<Grant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Grant | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgErr, setMsgErr] = useState(false);

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
    setMsgErr(false);
    const current = selected?.grant_id === id ? selected : rows.find((g) => g.grant_id === id);
    if (current?.state_revision === undefined) {
      setMsg('缺少 state_revision，请刷新后重试');
      setMsgErr(true);
      return;
    }
    const rev = current.state_revision;
    const run = (payload: Record<string, unknown>) =>
      localApi
        .grantAction(id, action, {
          actor_id: actorId,
          channel: 'console',
          expected_revision: rev,
          ...extra,
          ...payload,
        })
        .then((res) => {
          setSelected({ ...res.grant!, state_revision: res.state_revision ?? res.grant!.state_revision });
          setMsg(`${res.grant!.grant_id} → ${grantStatusLabel(res.grant!.status)}`);
          load();
        })
        .catch((err: unknown) => {
          setMsg(err instanceof Error ? err.message : '操作失败');
          setMsgErr(true);
        });

    if (action === 'approve') {
      localApi
        .grantAction(id, 'challenge', { expected_revision: rev })
        .then((res) => {
          const ch = res.challenge;
          if (!ch?.challenge_id || !ch?.nonce) {
            throw new Error('未返回批准挑战');
          }
          return run({ challenge_id: ch.challenge_id, nonce: ch.nonce });
        })
        .catch((err: unknown) => {
          setMsg(err instanceof Error ? err.message : '挑战签发失败');
          setMsgErr(true);
        });
      return;
    }
    run({});
  };

  const columns: TableColumn<Grant>[] = [
    { key: 'id', header: 'Grant', render: (r) => <span className="mono">{r.grant_id}</span> },
    { key: 'plat', header: '平台', render: (r) => platformLabel(r.platform) },
    {
      key: 'st',
      header: '状态',
      render: (r) => (
        <span className={grantTag(r.status)} title={r.status}>
          {grantStatusLabel(r.status)}
        </span>
      ),
    },
    { key: 'sub', header: '主体', render: (r) => r.subject?.id },
  ];

  const factCols: TableColumn<GrantFact>[] = [
    { key: 'dom', header: '权限域', render: (f) => domainLabel(f.domain) },
    { key: 'act', header: '动作', render: (f) => f.action },
    {
      key: 'res',
      header: '资源',
      render: (f) => (
        <code className="resource-cell" title={f.resource?.value}>
          {f.resource?.value}
        </code>
      ),
    },
    {
      key: 'state',
      header: '状态',
      render: (f) => <span className={factStateTag(f.state)}>{factStateLabel(f.state)}</span>,
    },
    { key: 'effect', header: '效果', render: (f) => f.effect },
  ];

  const unresolved = (selected?.overlap_conflicts ?? []).filter(
    (o) => o.resolution === 'unresolved',
  );
  const staticUnavailable = selected?.desired_policy_ref?.static_domains_unavailable ?? [];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="permissions"
        title="签发"
        description="只有人工批准能让 grant 生效路径往前走。filesystem/process 永不标有效。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
        actions={
          <button type="button" className="btn btn-sm" onClick={load}>
            刷新
          </button>
        }
      />
      {error ? (
        <div className="notice" role="status">
          <p className="notice-title">加载失败</p>
          <p className="notice-detail">{error}</p>
        </div>
      ) : null}
      <div className="card">
        <div className="field">
          <label htmlFor="actor">批准人（人工 actor_id）</label>
          <input id="actor" value={actorId} onChange={(e) => setActorId(e.target.value)} />
        </div>
        <SimpleTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.grant_id}
          emptyText={
            loading
              ? '加载中…'
              : error
                ? '决策 API 不可达，暂时无法读取签发。'
                : '还没有 grant。从智能体详情对非隔离 Skill 起草签发。'
          }
          onRowClick={setSelected}
        />
      </div>
      {selected ? (
        <div className="card">
          <h2>
            {selected.grant_id}{' '}
            <span className={grantTag(selected.status)} title={selected.status}>
              {grantStatusLabel(selected.status)}
            </span>
          </h2>
          <p className="page-desc">
            {platformLabel(selected.platform)} · {selected.subject?.type}:{selected.subject?.id}
          </p>
          {unresolved.length > 0 ? (
            <div className="notice" role="status">
              <p className="notice-title">未解决的权限重叠，批准前必须人工确认</p>
              {(selected.overlap_conflicts ?? []).map((o, i) =>
                o.resolution === 'unresolved' ? (
                  <p key={`${o.domain}-${i}`} className="notice-detail">
                    {domainLabel(o.domain)}: {o.fact_ids.join(', ')}{' '}
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
              静态域不可有效：{staticUnavailable.map(domainLabel).join('、')}
              （不调用 OpenShell create_generation）。
            </p>
          ) : null}
          <div className="toolbar toolbar-end">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => act(selected.grant_id, 'approve')}
              disabled={selected.status !== 'pending_approval'}
              title={
                selected.status !== 'pending_approval'
                  ? '只有待批准（pending_approval）的 grant 能批准'
                  : '人工批准后进入已批准'
              }
            >
              批准
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => act(selected.grant_id, 'deploy')}
              title="标记已下发到适配器；不等于沙箱读回有效"
            >
              标记已部署
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => act(selected.grant_id, 'reject')}
            >
              拒绝
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => act(selected.grant_id, 'revoke')}
            >
              吊销
            </button>
          </div>
          {msg ? (
            msgErr ? (
              <p className="action-error" role="alert">
                {msg}
              </p>
            ) : (
              <p className="sync-ok">{msg}</p>
            )
          ) : null}
          <h3 className="block-gap">事实</h3>
          <SimpleTable
            columns={factCols}
            rows={selected.facts ?? []}
            rowKey={(f) => f.fact_id}
            emptyText="该 grant 未携带事实明细。"
          />
        </div>
      ) : null}
    </section>
  );
}
