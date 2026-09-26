import { useEffect, useRef, useState } from 'react';
import Modal from '@/components/Modal';
import { ApiError } from '@/api/client';
import { confirmCandidateBatch, dismissCandidateBatch, readCandidateBatch, validBulkSelection, type BulkAction, type DismissReason } from '@/api/bulkCandidate';
import { assetStatusLabel, inventoryStamp } from '@/api/inventoryReview';
import type { AgentAsset } from '@/api/types';

export default function BulkCandidateReview({ assets, action, onClose, onResolved }: {
  assets: AgentAsset[]; action: BulkAction; onClose: () => void; onResolved: (count: number, reconciled: boolean) => void;
}) {
  const [snapshot, setSnapshot] = useState(assets);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState('');
  const [ack, setAck] = useState(false);
  const [reason, setReason] = useState<DismissReason | ''>('');
  const label = action === 'confirm' ? '确认' : '驳回';
  const pending = useRef(false);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const execute = async (reconcile: boolean) => {
    if (pending.current || (!reconcile && (!ack || uncertain || (action === 'dismiss' && !reason)))) return;
    pending.current = true; setBusy(true); setError('');
    try {
      if (reconcile) {
        const current = await readCandidateBatch(snapshot);
        if (!live.current) return;
        if (current.every(row => row.status === (action === 'confirm' ? 'confirmed' : 'dismissed'))) { onResolved(current.length, true); return; }
        setSnapshot(current); setAck(false);
        if (validBulkSelection(current)) {
          setUncertain(false); setError('已读回：全部仍待确认。请重新核对当前清单及版本后提交。');
        } else setError('已读回：候选状态不一致。请关闭并刷新列表，重新选择；不会自动重试或处理剩余项。');
      } else {
        if (action === 'confirm') await confirmCandidateBatch(snapshot);
        else if (reason) await dismissCandidateBatch(snapshot, reason);
        else return;
        if (live.current) onResolved(snapshot.length, false);
      }
    } catch (reason) {
      if (!live.current) return;
      setUncertain(true); setAck(false);
      setError(reason instanceof ApiError && reason.status === 403 ? `当前账号无权批量${label}。请核对结果或关闭。`
        : reason instanceof ApiError && reason.status === 409 ? '候选版本或状态发生变化。请先核对当前结果，不会自动重试。'
          : '未能确认批量处理结果。请先读取当前状态，不能假定已全部成功或全部回滚。');
    } finally { pending.current = false; if (live.current) setBusy(false); }
  };
  const close = () => { if (!pending.current) onClose(); };
  return <Modal open title={`批量${label} ${snapshot.length} 个候选`} onClose={close}
    description={action === 'confirm' ? '确认资产不批准工具权限、不启用拦截、不证明运行时已绑定。任一版本冲突或审计失败时整批回滚。'
      : '仅移出待处理候选，不删除配置、不卸载技能、不停止智能体或改变权限。任一版本冲突或审计失败时整批回滚。'}>
    <div className="modal-body">
      <ul>{snapshot.map(row => <li key={row.id} style={{ overflowWrap: 'anywhere' }}>
        {row.name} · {row.framework} · {assetStatusLabel(row.status)} · {inventoryStamp(row.updated_at)}
        <div className="mono">{row.id}</div>
      </li>)}</ul>
      {action === 'dismiss' ? <label className="login-field">批量驳回原因<select value={reason} disabled={busy || uncertain}
        onChange={event => { setReason(event.target.value as DismissReason | ''); setAck(false); }}>
        <option value="">请选择原因</option><option value="duplicate">重复配置</option>
        <option value="out_of_scope">不属于本次管理范围</option><option value="not_agent">不是智能体配置</option>
      </select></label> : null}
      <label><input type="checkbox" checked={ack} disabled={busy || uncertain} onChange={event => setAck(event.target.checked)} />{action === 'confirm'
        ? '我已核对以上明确选中的候选；保持现有用途与负责人，不授予业务权限。'
        : '我已核对以上候选及驳回原因；仅移出待处理清单，不改变实际运行或权限。'}</label>
      {error ? <p role="alert">{error}</p> : null}
    </div>
    <div className="modal-actions">
      <button className="btn" disabled={busy} onClick={close}>关闭并刷新列表</button>
      {uncertain ? <button className="btn btn-primary" disabled={busy} onClick={() => void execute(true)}>{busy ? '正在核对…' : '核对批量处理结果'}</button>
        : <button className={`btn ${action === 'dismiss' ? 'btn-danger' : 'btn-primary'}`} disabled={busy || !ack || !validBulkSelection(snapshot) || (action === 'dismiss' && !reason)} onClick={() => void execute(false)}>{busy ? '正在提交…' : action === 'confirm' ? '确认所选候选' : '驳回所选候选'}</button>}
    </div>
  </Modal>;
}
