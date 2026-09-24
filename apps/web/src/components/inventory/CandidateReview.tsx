import { useEffect, useRef, useState, type FormEvent } from 'react';
import Modal from '@/components/Modal';
import { api, ApiError } from '@/api/client';
import { assertReviewReadback, assetStatusLabel, pendingCandidate } from '@/api/inventoryReview';
import type { AgentAsset } from '@/api/types';

export default function CandidateReview({ asset, action, onClose, onResolved }: {
  asset: AgentAsset; action: 'confirm' | 'dismiss'; onClose: () => void;
  onResolved: (asset: AgentAsset, reconciled: boolean) => void;
}) {
  const [role, setRole] = useState(asset.role ?? '');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [snapshot, setSnapshot] = useState(asset);
  const pending = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const execute = async (reconcile: boolean) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try {
      const current = await api.getAgent(asset.id);
      if (!alive.current) return;
      if (!current || current.id !== asset.id) throw new Error('identity mismatch');
      if (reconcile) {
        setSnapshot(current);
        if (pendingCandidate(current)) {
          setUncertain(false);
          setError('已核对：仍待处理。输入已保留，可确认后重新提交。');
        } else onResolved(current, true);
        return;
      }
      if (!pendingCandidate(current) || current.updated_at !== snapshot.updated_at) {
        setUncertain(true); setError(`资产信息已变化，当前为“${assetStatusLabel(current.status)}”。请先核对处理结果。`); return;
      }
      if (action === 'confirm') await api.confirmCandidate(asset.id, { role: role.trim() || undefined });
      else await api.dismissCandidate(asset.id, { reason: reason.trim() });
      const result = assertReviewReadback(await api.getAgent(asset.id), asset.id, action, role.trim());
      if (alive.current) onResolved(result, false);
    } catch (e) {
      if (!alive.current) return;
      setUncertain(true);
      setError(e instanceof ApiError && e.status === 403 ? '当前账号无权处理此候选，请联系组织管理员。可核对当前结果或关闭。'
        : e instanceof ApiError && e.status === 409 ? '对象已被处理或状态变化，请先核对当前结果。'
          : '未能确认处理结果。输入已保留，请先核对当前状态，避免重复提交。');
    } finally { pending.current = false; if (alive.current) setBusy(false); }
  };
  const submit = (event: FormEvent) => { event.preventDefault(); if (!uncertain) void execute(false); };
  const close = () => { if (!pending.current) onClose(); };
  return <Modal open onClose={close} title={`${action === 'confirm' ? '确认资产' : '驳回候选'} · ${asset.name}`}
    description={action === 'confirm' ? '确认此配置属于需要管理的智能体。确认不会批准工具权限或启用拦截。' : '仅从待处理候选中移出；不会卸载框架、删除配置或停止智能体。'}>
    <form onSubmit={submit}>
      <div className="modal-body">
        <p>框架：{asset.framework}；当前用途：{asset.role || '尚未填写'}。</p>
        {action === 'confirm' ? <label className="login-field">业务用途（可选）<input value={role} maxLength={128} disabled={busy} placeholder="例如：研究分析、合同审查" onChange={e => setRole(e.target.value)} /><span>用于说明智能体角色，不是组织权限角色；已有负责人保持不变。</span></label>
          : <label className="login-field">驳回原因<input value={reason} maxLength={512} required disabled={busy} placeholder="例如：重复配置，不属于本次管理范围" onChange={e => setReason(e.target.value)} /></label>}
        {error ? <p role="alert" className="action-error">{error}</p> : null}
      </div>
      <div className="modal-actions">
        <button type="button" className="btn" disabled={busy} onClick={close}>取消</button>
        {uncertain ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void execute(true)}>{busy ? '正在核对…' : '核对处理结果'}</button>
          : <button type="submit" className={`btn ${action === 'dismiss' ? 'btn-danger' : 'btn-primary'}`} disabled={busy || action === 'dismiss' && !reason.trim()}>{busy ? '正在提交并核对…' : action === 'confirm' ? '确认资产' : '确认驳回'}</button>}
      </div>
    </form>
  </Modal>;
}
