import { useCallback, useEffect, useRef, useState } from 'react';
import Modal from '@/components/Modal';
import { localApi } from '../api';
import { skillInstallErrorText } from '../skillInstall';
import { skillRemoveRequest } from '../skillRemoval';
import { useLocalSession } from '../session';
import type { SkillRemovalView } from '../types';
import GrantScopeSummary from './GrantScopeSummary';

export default function SkillRemovalDialog({ current, disabled, onOpen, onRefresh }: {
  current: SkillRemovalView | null; disabled: boolean; onOpen: (open: boolean) => void; onRefresh: () => void;
}) {
  const { actorId } = useLocalSession();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<SkillRemovalView | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const snapshot = useRef<SkillRemovalView | null>(null);
  const active = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  useEffect(() => () => { active.current?.abort(); onOpen(false); }, [onOpen]);
  const close = useCallback(() => {
    if (submitting.current) return;
    active.current?.abort(); setOpen(false); onOpen(false); onRefresh();
  }, [onOpen, onRefresh]);
  const show = () => {
    if (!current || disabled) return;
    snapshot.current = current; setView(current); setConfirmed(false); setMessage(''); setBusy(false);
    setOpen(true); onOpen(true);
  };
  const read = async (controller: AbortController) => {
    const original = snapshot.current;
    if (!original) throw new Error('skill_install_incompatible_response');
    const result = await localApi.skillRemoval(original.record.install_id, controller.signal);
    if (result.record.claim_signature !== original.record.claim_signature || result.record.plan.signature !== original.record.plan.signature) throw new Error('skill_install_incompatible_response');
    if (!controller.signal.aborted) setView(result);
  };
  const refresh = async () => {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setView(null); setConfirmed(false); setMessage('');
    const controller = new AbortController(); active.current = controller;
    try { await read(controller); }
    catch (err) { if (!controller.signal.aborted) setMessage(skillInstallErrorText(err) + ' 当前状态无法确认，请重新查询。'); }
    finally { submitting.current = false; if (!controller.signal.aborted) setBusy(false); }
  };
  const submit = async () => {
    if (submitting.current || !confirmed || !view || view.status === 'removed' || (!view.claim && !actorId.trim())) return;
    const request = skillRemoveRequest(view, actorId);
    const id = view.record.install_id;
    submitting.current = true; setBusy(true); setView(null); setConfirmed(false); setMessage('');
    const controller = new AbortController(); active.current = controller;
    try {
      const result = await localApi.removeSkill(id, request, controller.signal);
      if (!controller.signal.aborted) setView(result);
    } catch (err) {
      if (controller.signal.aborted) return;
      setMessage(skillInstallErrorText(err) + ' 正在只读查询原移除操作，未自动重发。');
      try { await read(controller); }
      catch (readError) { if (!controller.signal.aborted) { setView(null); setMessage(skillInstallErrorText(readError) + ' 当前无法确认移除状态，请重新查询原操作。'); } }
    } finally { submitting.current = false; if (!controller.signal.aborted) setBusy(false); }
  };
  const record = snapshot.current?.record;
  return <>
    <button type="button" className="btn" disabled={disabled || !current} onClick={show}>
      {current?.status === 'removed' ? '查看移除记录' : current?.claim ? '继续移除与恢复' : '移除此 Skill'}
    </button>
    <Modal open={open} onClose={close} title="移除 Skill" description="核对目标副本和权限范围后，再确认操作。" className="skill-removal-dialog">
      {record ? <><h3>{record.plan.directory_name}</h3><p>{record.plan.target_display}</p></> : null}
      {busy ? <p role="status">正在处理或查询移除操作…</p> : null}
      {message ? <p role="alert" className="action-error">{message}</p> : null}
      {view ? <>
        {view.status === 'removed' ? <>
          <p role="status"><strong>已记录移除完成</strong></p>
          <p>完成时间：{new Date(view.result!.recorded_at).toLocaleString()}</p>
          <p>{view.result!.grant_revoked ? '对应授权已撤销。' : '保留了其他安装使用的授权。'} 这是原操作的历史结果；同路径后来出现的文件不会再次清理。</p>
        </> : <>
          {view.status === 'revocation_pending' ? <p role="alert">移除已开始，授权撤销尚未完成。运行接入已拒绝使用此安装，文件尚待清理。</p> : null}
          {view.status === 'cleanup_pending' ? <p role="alert">{view.will_revoke_grant ? '对应授权已撤销，' : '其他安装的授权保留，'}文件清理尚未完成。请核对目标中的新增、修改或归属不明内容，保留需要的文件后再重试。若仅剩无归属标记的空目录，请确认其用途后自行处理。</p> : null}
          <p><strong>{view.will_revoke_grant ? (view.grant?.status === 'revoked' ? '此安装对应的授权已撤销，相关实例凭据和会话不能再使用该授权。' : '本次会撤销此安装对应的授权，相关实例凭据和会话将无法继续使用该授权。') : '此授权正在关联另一份安装，本次保留该授权，仅清理当前副本。'}</strong></p>
          {view.retained_install_id ? <p>保留的安装：<code>{view.retained_install_id}</code></p> : null}
          <GrantScopeSummary grant={view.grant ?? undefined} label="本次关联的权限范围" />
          <p>只清理本次安装创建、内容未变且归属可证的文件。用户新增或修改的内容会保留；导入来源与审计记录保留。撤销不会在重试时恢复。</p>
          {view.claim ? <p>继续原操作，记录操作者：<strong>{view.claim.actor_id}</strong>。重试使用原确认范围。</p> : <p>记录操作者：{actorId.trim() || '请先在管理会话中设置操作者'}</p>}
          <label className="install-confirmation"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} />我已核对目标和权限范围，确认移除</label>
          <div className="import-actions"><button type="button" className="btn" disabled={busy || !confirmed || (!view.claim && !actorId.trim())} onClick={() => void submit()}>{view.claim ? '按原确认继续移除' : '确认移除 Skill'}</button></div>
        </>}
      </> : null}
      <div className="import-actions"><button type="button" className="btn" disabled={busy} onClick={() => void refresh()}>重新查询移除状态</button><button type="button" className="btn" disabled={busy} onClick={close}>关闭</button></div>
    </Modal>
  </>;
}
