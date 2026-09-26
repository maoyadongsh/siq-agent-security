import { useEffect, useReducer, useRef, useState } from 'react';
import { useConsoleContext } from '@/components/ConsoleContext';
import ConfirmDialog from '@/components/ConfirmDialog';
import { ApiError } from '@/api/client';
import { listDiscoverySchedules, revokeDiscoverySchedule } from '@/api/discoveryScheduleManagement';
import { canOfferRevoke, dsmReducer, initialDsmState, remainingBudget, revokeFailureMessage, statusLabel,
  windowLabel, windowState } from './dsmState';
import './discovery-schedule-management.css';

function Manager({ environmentId }: { environmentId: string }) {
  const [open, setOpen] = useState(false);
  const [state, dispatch] = useReducer(dsmReducer, undefined, initialDsmState);
  const pending = useRef(false);
  const generation = useRef(0);
  const load = (cursor: string | null, more: boolean) => {
    if (pending.current) return;
    const ticket = ++generation.current;
    dispatch(more ? { type: 'loadMoreStart', ticket } : { type: 'loadStart', ticket });
    void listDiscoverySchedules(environmentId, cursor).then(page => {
      if (ticket === generation.current) dispatch(more ? { type: 'loadMoreSuccess', ticket, page } : { type: 'loadSuccess', ticket, page });
    }, () => {
      if (ticket === generation.current) dispatch(more ? { type: 'loadMoreFailure', ticket } : { type: 'loadFailure', ticket });
    });
  };
  useEffect(() => {
    if (!open) return;
    load(null, false);
    return () => { generation.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, environmentId]);
  const revoke = async () => {
    const target = state.revokeTarget;
    if (!target || pending.current || state.revokeBusy || state.phase !== 'ready' || state.morePhase !== 'idle'
      || !canOfferRevoke(target, state.canRevoke)) return;
    pending.current = true;
    dispatch({ type: 'revokeStart' });
    const ticket = generation.current;
    try {
      await revokeDiscoverySchedule(environmentId, target.schedule_id, target.revision);
      if (ticket === generation.current) {
        dispatch({ type: 'revokeSuccess' });
        pending.current = false;
        load(null, false);
      }
    } catch (error) {
      if (ticket === generation.current) {
        dispatch({ type: 'revokeFailure', text: revokeFailureMessage(error instanceof ApiError ? error.status : 0) });
      }
    } finally {
      pending.current = false;
    }
  };
  const target = state.revokeTarget;
  return <section className="card dsm-panel" aria-label="周期发现计划">
    <h2>周期发现计划</h2>
    <p>查看本环境已保存的周期发现计划并按需撤销。这里的计划状态不代表设备在线、采集成功或防护生效。</p>
    {open ? null : <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen(true)}>查看周期发现计划</button>}
    {open && state.phase === 'loading' ? <p role="status">正在读取周期发现计划…</p> : null}
    {open && state.phase === 'error' ? <p role="alert">
      <button type="button" className="btn" onClick={() => load(null, false)}>重试读取周期发现计划</button>
    </p> : null}
    {open && state.phase === 'ready' && state.evaluatedAt ? <>
      <p>服务端评估时间：{state.evaluatedAt}。仅显示已加载记录{state.nextCursor !== null ? '，不代表全部计划' : ''}。</p>
      {state.items.length === 0 ? <p>本环境暂无周期发现计划记录。</p> : <ul className="dsm-list">
        {state.items.map(item => <li key={item.schedule_id} className="dsm-item">
          <div className="dsm-row"><span className="dsm-label">计划 ID</span><span>{item.schedule_id}</span></div>
          <div className="dsm-row"><span className="dsm-label">设备</span><span>{item.edge_agent_id}</span></div>
          <div className="dsm-row"><span className="dsm-label">状态</span><span>{statusLabel(item.status)}{item.status === 'active' ? '（已确认的计划不代表设备在线、采集成功或防护生效）' : ''}</span></div>
          <div className="dsm-row"><span className="dsm-label">版本</span><span>revision {item.revision}</span></div>
          <div className="dsm-row"><span className="dsm-label">窗口</span><span>{item.starts_at} 至 {item.expires_at}（{state.evaluatedAt ? windowLabel(windowState(item, state.evaluatedAt)) : ''}，仅为窗口事实，不推算下次必定扫描时间）</span></div>
          <div className="dsm-row"><span className="dsm-label">间隔</span><span>{item.interval_seconds} 秒</span></div>
          <div className="dsm-row"><span className="dsm-label">预算</span><span>已预约 {item.reserved_runs} / {item.max_runs} 轮（已预约轮次不是成功扫描次数）；未预约预算 {remainingBudget(item)} 轮，实际调度还受期限与其他门禁约束</span></div>
          <div className="dsm-row"><span className="dsm-label">最后预约槽</span><span>{item.last_reserved_slot ?? '无'}</span></div>
          <div className="dsm-row"><span className="dsm-label">创建时间</span><span>{item.created_at}</span></div>
          {canOfferRevoke(item, state.canRevoke) ? <div className="dsm-actions">
            <button type="button" className="btn btn-danger" disabled={state.revokeBusy}
              onClick={() => dispatch({ type: 'revokeOpen', item })}>撤销该计划</button>
          </div> : null}
        </li>)}
      </ul>}
      <div className="dsm-actions">
        <button type="button" className="btn" disabled={state.revokeBusy || state.morePhase === 'loading'}
          onClick={() => load(null, false)}>只读刷新（从第一页替换）</button>
        {state.nextCursor !== null ? <button type="button" className="btn" disabled={state.morePhase !== 'idle' || state.revokeBusy}
          onClick={() => load(state.nextCursor, true)}>{state.morePhase === 'loading' ? '正在加载更多…' : '加载更多'}</button> : null}
      </div>
      {state.morePhase === 'error' ? <p role="alert">
        <button type="button" className="btn" disabled={state.revokeBusy}
          onClick={() => { if (state.nextCursor) load(state.nextCursor, true); }}>用同一游标重试加载更多</button>
      </p> : null}
    </> : null}
    {state.message ? <p role={state.message.kind}>{state.message.text}</p> : null}
    <ConfirmDialog open={target !== null} title="撤销周期发现计划" danger busy={state.revokeBusy} confirmLabel="确认撤销"
      description={target ? `计划 ${target.schedule_id}（设备 ${target.edge_agent_id}，当前 revision ${target.revision}）。确认后停止该计划后续调度，不保证已派发任务被取消，不撤销智能体业务权限。` : undefined}
      onConfirm={() => void revoke()}
      onClose={() => { if (!state.revokeBusy) dispatch({ type: 'revokeCancel' }); }} />
  </section>;
}

export default function DiscoverySchedulePanel({ environmentId }: { environmentId: string }) {
  const { data, status } = useConsoleContext();
  if (!environmentId || status !== 'ready' || !data?.access.environments) return null;
  return <Manager key={JSON.stringify([data.tenant.id, data.actor.type, data.actor.id, environmentId])} environmentId={environmentId} />;
}
