import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { LocalApiError } from '../api';
import { platformLabel } from '../format';
import { useLocalSession } from '../session';
import { useConfirmations } from '../confirmations';
import { NotificationPreferences } from '../components/ConfirmationNotifications';
import type { Confirmation } from '../types';

const statusText: Record<Confirmation['status'], string> = {
  pending: '等待确认', approved: '已批准', denied: '已拒绝', expired: '已过期',
  consumed: '已记录执行结果', unavailable: '权限已失效或不可核实',
};
const grantLink = (id: string) => `/grants?grant=${encodeURIComponent(id)}`;

export default function ConfirmationsPage() {
  const { actorId, setActorId } = useLocalSession();
  const [params, setParams] = useSearchParams();
  const requested = params.get('request');
  const { items, grants, error, loading, refresh: load, resolve } = useConfirmations();
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [history, setHistory] = useState(false);
  const [now, setNow] = useState(Date.now);
  const alive = useRef(false);
  const working = useRef(false);
  const selected = items.find((item) => item.action_id === requested || item.decision_receipt_id === requested);

  useEffect(() => {
    alive.current = true;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { alive.current = false; window.clearInterval(tick); };
  }, []);
  useEffect(() => { setReviewed(false); setMessage(null); }, [requested, selected?.decision_hash]);

  const act = async (approve: boolean) => {
    if (!selected || working.current || error || (approve && !reviewed)) return;
    working.current = true;
    setBusy(true);
    setMessage(null);
    try {
      const result = await resolve(selected, approve, actorId.trim());
      if (alive.current) setMessage(`${approve ? '已批准本次请求' : '已拒绝本次请求'}。确认记录：${result.receipt_id}`);
    } catch (err) {
      if (alive.current) setMessage(err instanceof LocalApiError && err.status === 409
        ? '请求已处理、过期或发生变化，请查看最新状态。没有重复批准。'
        : err instanceof Error ? err.message : '处理失败，请刷新查看结果后重试');
    } finally {
      working.current = false;
      if (alive.current) { setBusy(false); setReviewed(false); }
    }
  };
  const pending = items.filter((item) => item.status === 'pending' && item.expires_at && Date.parse(item.expires_at) > now);
  const pendingGrants = grants.filter((grant) => grant.status === 'pending_approval');
  const actionable = selected?.status === 'pending' && !!selected.expires_at && Date.parse(selected.expires_at) > now && !error && !loading;
  const columns: TableColumn<Confirmation>[] = [
    { key: 'tool', header: '操作', render: (item) => <Link to={`?request=${encodeURIComponent(item.action_id)}`}>{item.tool}</Link> },
    { key: 'platform', header: '平台', render: (item) => platformLabel(item.platform) },
    { key: 'state', header: '状态', render: (item) => item.status === 'pending' && item.expires_at && Date.parse(item.expires_at) <= now ? '已过期' : statusText[item.status] },
    { key: 'expiry', header: '确认截止时间', render: (item) => item.expires_at ? new Date(item.expires_at).toLocaleString() : '无法核实' },
  ];
  return <section>
    <PageHeader kicker="个人管理" icon="shield" title="确认待办"
      description="先查看具体操作，再决定是否批准。打开待办不会授予权限。"
      connection={loading ? 'loading' : error ? 'disconnected' : 'connected'} connectionError={error}
      actions={<button type="button" className="btn" disabled={busy} onClick={() => void load()}>刷新待办</button>} />
    <NotificationPreferences />
    {error && <p className="action-error" role="alert">{error}。连接恢复前暂停确认。</p>}
    <div className="card">
      <h2>运行操作 · {pending.length} 项待确认</h2>
      <label><input type="checkbox" checked={history} onChange={(event) => setHistory(event.target.checked)} /> 同时显示近期已处理和过期请求</label>
      <SimpleTable columns={columns} rows={history ? items : pending} rowKey={(item) => item.action_id}
        emptyText={loading ? '正在读取待办…' : error ? '暂时无法读取待办。' : '目前没有待确认的运行操作。'} />
      <p className="page-desc">此处显示最近 24 小时运行记录窗口内的请求，完整历史见<Link to="/receipts">回执</Link>。</p>
    </div>
    {requested && !selected && !loading && !error && <p className="notice" role="status">请求已离开近期记录窗口，或当前服务没有此请求。请在回执中查阅历史。</p>}
    {selected && <div className="card" aria-busy={busy}>
      <h2>确认操作：{selected.tool}</h2>
      <p>{platformLabel(selected.platform)} · {actionable ? '等待确认' : selected.status === 'pending' && !error ? '已过期或暂不可处理' : statusText[selected.status]}</p>
      <dl>
        <dt>智能体</dt><dd className="resource-cell">{selected.agent_id || '未提供实例标识'}</dd>
        <dt>会话</dt><dd className="resource-cell">{selected.session_id}</dd>
        <dt>请求时间</dt><dd>{new Date(selected.issued_at).toLocaleString()}</dd>
        <dt>确认截止</dt><dd>{selected.expires_at ? new Date(selected.expires_at).toLocaleString() : '无法核实'}</dd>
        <dt>脱敏参数摘要</dt><dd><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{selected.params_excerpt ?? '未记录参数摘要；无法判断时请选择拒绝。'}</pre></dd>
      </dl>
      <details><summary>查看对应证据</summary><p className="resource-cell">请求回执：{selected.decision_receipt_id}</p><p className="resource-cell">参数指纹：{selected.params_digest}</p></details>
      <p>{selected.grant_id && <Link to={grantLink(selected.grant_id)}>查看长期权限</Link>} · 批准本次请求不会扩大长期权限。</p>
      <p className="notice">{selected.platform === 'hermes'
        ? 'Hermes 当前会阻止等待审批的调用，批准后尚不能自动恢复原调用。重新发起的调用属于新请求，可能需要再次确认。'
        : '批准记录不代表工具已执行。支持恢复的平台仍需在有效期内核对原请求和当前权限。'}</p>
      {actionable && <>
        <div className="field"><label htmlFor="confirmation-actor">确认人</label><input id="confirmation-actor" value={actorId} disabled={busy} onChange={(event) => setActorId(event.target.value)} /></div>
        <label><input type="checkbox" checked={reviewed} disabled={busy} onChange={(event) => setReviewed(event.target.checked)} /> 我已核对本次操作和参数摘要</label>
        <div className="toolbar">
          <button type="button" className="btn btn-danger" disabled={busy || !actorId.trim()} onClick={() => void act(false)}>拒绝本次请求</button>
          <button type="button" className="btn btn-primary" disabled={busy || !reviewed || !actorId.trim()} onClick={() => void act(true)}>批准本次请求</button>
        </div>
      </>}
      {message && <p role="status">{message}</p>}
      <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setParams({})}>关闭详情</button>
    </div>}
    <div className="card">
      <h2>长期权限 · {pendingGrants.length} 项待审阅</h2>
      <p className="page-desc">长期权限需要单独审阅范围和有效期，批准后再完成部署与实例接入。</p>
      {pendingGrants.length ? <ul>{pendingGrants.map((grant) => <li key={grant.grant_id}>
        <Link to={grantLink(grant.grant_id)}>{platformLabel(grant.platform)} · {grant.subject?.id || grant.grant_id} · 审阅权限</Link>
      </li>)}</ul> : <p>{loading ? '正在读取授权…' : error ? '暂时无法读取授权。' : '目前没有待批准的长期权限。'}</p>}
    </div>
  </section>;
}
