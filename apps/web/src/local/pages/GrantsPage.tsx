import { skillImportErrorText } from "../skillImports";
import SkillInstallationResult from "../components/SkillInstallationResult";
import ImportGrantSource from "../components/ImportGrantSource";
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { localApi } from '../api';
import type { Grant, GrantFact } from '../types';
import { useLocalSession } from '../session';
import GrantResourceDialog from '../components/GrantResourceDialog';
import {
  domainLabel,
  factStateLabel,
  factStateTag,
  grantStatusLabel,
  grantTag,
  platformLabel,
} from '../format';

export default function GrantsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [installSubmitting, setInstallSubmitting] = useState(false);
  const [installEpoch, setInstallEpoch] = useState(0);
  const [installMessage, setInstallMessage] = useState<string | undefined>();
  const onOperation = useCallback((message?: string, pending = false) => { setInstallSubmitting(pending); setInstallMessage(message); setInstallEpoch((value) => value + 1); }, []);
  const requestedGrant = searchParams.get('grant');
  const { actorId, setActorId } = useLocalSession();
  const [rows, setRows] = useState<Grant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Grant | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgErr, setMsgErr] = useState(false);
  const [busy, setBusy] = useState(false);
  const [duration, setDuration] = useState('600');
  const [editingId, setEditingId] = useState<string | null>(null);
  const closeEditor = useCallback(() => setEditingId(null), []);

  const saveExpiry = async () => {
    if (!selected || selected.state_revision === undefined || busy) return;
    setBusy(true);
    setMsg(null);
    setMsgErr(false);
    try {
      const res = await localApi.setGrantExpiry(selected.grant_id, selected.state_revision,
        actorId, duration === 'unlimited' ? null : Number(duration));
      setSelected({ ...res.grant, state_revision: res.state_revision });
      setMsg('授权期限已保存，请检查权限后人工批准。');
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '期限保存失败');
      setMsgErr(true);
    } finally {
      setBusy(false);
    }
  };

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

  useEffect(() => {
    if (!requestedGrant) return;
    let cancelled = false;
    localApi.grant(requestedGrant).then(({ grant }) => {
      if (!cancelled) setSelected(grant);
    }).catch((err: unknown) => {
      if (!cancelled) setError(err instanceof Error ? err.message : '无法读取指定授权');
    });
    return () => { cancelled = true; };
  }, [requestedGrant]);

  const act = (id: string, action: string, extra: Record<string, unknown> = {}) => {
    if (busy) return;
    setMsg(null);
    setMsgErr(false);
    const current = selected?.grant_id === id ? selected : rows.find((g) => g.grant_id === id);
    if (current?.state_revision === undefined) {
      setMsg('缺少 state_revision，请刷新后重试');
      setMsgErr(true);
      return;
    }
    const rev = current.state_revision;
    setBusy(true);
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
          setMsg(grantErrorText(err, '操作失败'));
          setMsgErr(true);
        })
        .finally(() => setBusy(false));

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
          setMsg(grantErrorText(err, '挑战签发失败'));
          setMsgErr(true);
          setBusy(false);
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
    { key: 'expiry', header: '到期时间', render: (r) => expiryLabel(r.expires_at) },
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
    <section className="local-grants-page">
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
          onRowClick={(row) => { if (!busy) { setSelected(row); setSearchParams({ grant: row.grant_id }); setDuration('600'); setMsg(null); } }}
        />
      </div>
      <SkillInstallationResult key={searchParams.get('install_id') ?? 'none'} epoch={installEpoch} submissionMessage={installMessage} processing={installSubmitting} />
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
          {selected.admission_id.startsWith('adm-si-') ? <ImportGrantSource key={selected.admission_id} grant={selected} onOperation={onOperation} /> : null}
          <p>到期时间：<time dateTime={selected.expires_at ?? undefined}>{expiryLabel(selected.expires_at)}</time></p>
          {selected.status === 'pending_approval' ? (
            <div className="toolbar">
              <div className="field field-flush">
                <label htmlFor="grant-duration">授权期限（从保存时开始）</label>
                <select id="grant-duration" value={duration} onChange={(e) => setDuration(e.target.value)} disabled={busy}>
                  <option value="600">10 分钟</option>
                  <option value="3600">1 小时</option>
                  <option value="86400">1 天</option>
                  <option value="604800">7 天</option>
                  <option value="2592000">30 天</option>
                  <option value="unlimited">不设期限</option>
                </select>
              </div>
              <button type="button" className="btn" onClick={saveExpiry} disabled={busy || !actorId.trim()}>
                保存期限
              </button>
              <p className="page-desc">保存后需要重新批准。阻断模式到期后拒绝新的操作，监测模式记录拒绝建议。</p>
            </div>
          ) : <p className="page-desc">已批准的授权不能直接延长期限；需要时请重新起草并批准。</p>}
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
                      disabled={busy}
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
            <button type="button" className="btn" disabled={busy || selected.status !== 'pending_approval'}
              onClick={() => setEditingId(selected.grant_id)}>编辑权限范围</button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => act(selected.grant_id, 'approve')}
              disabled={busy || selected.status !== 'pending_approval' || !actorId.trim()}
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
              disabled={busy || selected.status !== 'approved' || selected.admission_id.startsWith('adm-si-')}
              title="标记已下发到适配器；不等于沙箱读回有效"
            >
              标记已部署
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => act(selected.grant_id, 'reject')}
              disabled={busy}
            >
              拒绝
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => act(selected.grant_id, 'revoke')}
              disabled={busy}
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
      {editingId ? <GrantResourceDialog grantId={editingId} onClose={closeEditor} onSaved={(updated) => {
        setSelected(updated); setEditingId(null); setMsgErr(false); setMsg('权限范围已保存，请检查后重新批准。'); load();
      }} /> : null}
    </section>
  );
}

function expiryLabel(value?: string | null): string {
  if (value == null) return '不设期限';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '期限无效，请重新起草' : date.toLocaleString();
}

function grantErrorText(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback;
  if (error.message.startsWith('skill_import_')) return skillImportErrorText(error);
  if (error.message === 'grant_import_installation_required') return '此候选尚未完成安装和内容读回，不能激活运行权限。';
  return error.message;
}
