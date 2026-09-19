import { useCallback, useEffect, useRef, useState } from 'react';
import { localApi } from '../api';
import type { SkillContextManagement, SkillSessionContext } from '../skillContextManagement';
import type { SkillInstallView, SkillRuntimeReadiness } from '../types';

export default function SkillSessionBinding({ view, readiness, actor, onBusy }: {
  view: SkillInstallView; readiness: SkillRuntimeReadiness; actor: string; onBusy: (busy: boolean) => void;
}) {
  const [data, setData] = useState<SkillContextManagement | null>(null);
  const [session, setSession] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [revokeId, setRevokeId] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const active = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  useEffect(() => { onBusy(busy); return () => onBusy(false); }, [busy, onBusy]);
  const read = useCallback(async (signal: AbortSignal) => {
    const current = await localApi.skillContextManagement(view, readiness, signal);
    if (!signal.aborted) setData(current);
  }, [view, readiness]);
  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const controller = new AbortController(); active.current = controller;
    setBusy(true); setData(null); setConfirmed(false); setRevokeId(''); setSession(''); setMessage('');
    try { await read(controller.signal); }
    catch { if (!controller.signal.aborted) setMessage('无法读取会话绑定。请确认实例已接入，稍后重新查询。'); }
    finally { if (active.current === controller) { inFlight.current = false; if (!controller.signal.aborted) setBusy(false); } }
  }, [read]);
  useEffect(() => { void refresh(); return () => { active.current?.abort(); active.current = null; inFlight.current = false; }; }, [refresh]);
  const change = async (context?: SkillSessionContext) => {
    if (inFlight.current || !data || !actor.trim()) return;
    if (context ? revokeId !== context.context_id : !confirmed || !data.sessions.some(s => s.session_id === session && Date.parse(s.expires_at) > Date.now())) return;
    inFlight.current = true;
    const controller = new AbortController(); active.current = controller;
    setBusy(true); setConfirmed(false); setRevokeId(''); setData(null); setMessage('');
    try {
      if (context) await localApi.revokeSkillSession(context, actor.trim(), controller.signal);
      else await localApi.issueSkillSession(view, readiness, session, actor.trim(), controller.signal);
      if (!controller.signal.aborted) setMessage(context ? '撤销请求已完成，请核对下方读回记录。' : '绑定请求已完成，请核对下方读回记录。实际调用仍逐次检查权限。');
    } catch {
      if (!controller.signal.aborted) setMessage('请求未能确认完成，已查询记录；不会自动重发。若仍无法确认，请先重新查询。');
    } finally {
      if (!controller.signal.aborted) {
        try { await read(controller.signal); }
        catch { if (!controller.signal.aborted) setMessage('暂时无法确认操作结果。请重新查询，勿重复提交。'); }
        if (!controller.signal.aborted) setBusy(false);
      }
      if (active.current === controller) inFlight.current = false;
    }
  };
  return <section aria-label="Skill 会话绑定" aria-busy={busy}>
    <h4>绑定 Skill 会话</h4>
    <p>将此实例的一个已登记会话归并到当前 Skill，最长一小时且不超过会话有效期。会话全部调用归并到该 Skill，不含逐调用因果；这不证明宿主已加载 Skill，也不扩大权限。</p>
    {message ? <p role="status">{message}</p> : null}
    {busy ? <p role="status">正在查询或提交会话绑定…</p> : null}
    {data ? <>
      {data.sessions.length === 0 ? <p>没有可绑定会话。请先接入此实例，并在宿主发起一次工具调用以登记会话，再重新查询；尚未绑定时 Skill 调用可能被拒绝。</p> : <>
        <label>已登记会话 <select value={session} disabled={busy} onChange={e => { setSession(e.target.value); setConfirmed(false); }}>
          <option value="">请选择会话</option>
          {data.sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.session_id} · 到期 {new Date(s.expires_at).toLocaleString()}</option>)}
        </select></label>
        <label><input type="checkbox" checked={confirmed} disabled={busy || !session} onChange={e => setConfirmed(e.target.checked)} />确认将所选会话的全部调用归并到当前 Skill</label>
        <button type="button" className="btn" disabled={busy || !session || !confirmed || !actor.trim()} onClick={() => void change()}>确认绑定会话</button>
      </>}
      {data.contexts.map(({ context, revoked }) => <div key={context.context_id}>
        <p>{context.subject.session_id} · {context.evidence_level === 'controlled_session' ? '会话级绑定' : '任务级绑定'} · {revoked ? '已撤销' : Date.parse(context.expires_at) <= Date.now() ? '已到期' : '已记录；实际有效性以调用时复验为准'} · 到期 {new Date(context.expires_at).toLocaleString()}</p>
        {!revoked ? <><label><input type="checkbox" checked={revokeId === context.context_id} disabled={busy} onChange={e => setRevokeId(e.target.checked ? context.context_id : '')} />确认撤销此绑定</label>
          <button type="button" className="btn" disabled={busy || revokeId !== context.context_id || !actor.trim()} onClick={() => void change(context)}>撤销绑定</button></> : null}
      </div>)}
    </> : null}
    <button type="button" className="btn" disabled={busy} onClick={() => void refresh()}>重新查询会话与绑定</button>
  </section>;
}
