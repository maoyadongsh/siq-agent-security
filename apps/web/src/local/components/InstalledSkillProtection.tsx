import { useCallback, useEffect, useRef, useState } from 'react';
import { localApi } from '../api';
import { skillInstallErrorText } from '../skillInstall';
import { matchesInstalledReadiness } from '../skillRuntime';
import { useLocalSession } from '../session';
import type { SkillInstallView, SkillRuntimeReadiness } from '../types';
import AdapterChangeDialog from './AdapterChangeDialog';
import RuntimeCheckDialog from './RuntimeCheckDialog';
import GrantScopeSummary from './GrantScopeSummary';

export default function InstalledSkillProtection({ view, onBusy }: { view: SkillInstallView; onBusy: (busy: boolean) => void }) {
  const { actorId } = useLocalSession();
  const [readiness, setReadiness] = useState<SkillRuntimeReadiness | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [dialog, setDialog] = useState<'adapter' | 'check' | null>(null);
  const submitting = useRef(false);
  const active = useRef<AbortController | null>(null);
  const closeDialog = useCallback(() => { setDialog(null); setRefresh((n) => n + 1); }, []);
  useEffect(() => { onBusy(busy || dialog !== null); return () => onBusy(false); }, [busy, dialog, onBusy]);
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setReadiness(null); setError(''); setConfirmed(false);
    localApi.skillRuntimeReadiness(view.install_id, controller.signal).then((r) => {
      if (controller.signal.aborted) return;
      if (!matchesInstalledReadiness(r, view)) throw new Error('skill_install_incompatible_response');
      setReadiness(r);
    }).catch((err: unknown) => { if (!controller.signal.aborted) setError(skillInstallErrorText(err)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [view, refresh]);
  const prepare = async () => {
    if (submitting.current || busy || !confirmed || !readiness || !view.operation || !['not_prepared', 'incomplete'].includes(readiness.status)) return;
    const actor = readiness.binding?.actor_id ?? actorId.trim();
    if (!actor) return;
    submitting.current = true; setBusy(true); setError(''); setReadiness(null); setConfirmed(false);
    const controller = new AbortController(); active.current = controller;
    try {
      await localApi.activateSkillInstallation(view.install_id, { schema_version: 'local-skill-install-activate/v1', operation_signature: view.operation.signature, expected_revision: view.plan.grant_revision, actor_id: actor, confirm_instance_scope: true }, controller.signal);
      if (!controller.signal.aborted) setMessage('实例权限准备请求已完成，请以最新查询结果为准。');
    } catch (err) { if (!controller.signal.aborted) setMessage(`${skillInstallErrorText(err)} 已重新查询原操作，未自动重发。`); }
    finally { submitting.current = false; if (!controller.signal.aborted) { setBusy(false); setRefresh((n) => n + 1); } }
  };
  return <section className="instance-permission-panel" aria-label="安装后的实例权限" aria-busy={busy}>
    <h3>下一步：准备实例权限</h3>
    <p>先确认权限，再接入原平台并运行自检。这些权限约束整个实例会话，实际 Skill 调用归属仍待验证。</p>
    {busy ? <p role="status">正在核验安装内容与权限…</p> : null}
    {message ? <p role="status">{message}</p> : null}
    {error ? <p role="alert" className="action-error">{error} 当前无法确认权限准备状态。</p> : null}
    {readiness ? <>
      <GrantScopeSummary grant={readiness.grant} label="此次安装对应的实例权限" />
      {readiness.status === 'no_tools' ? <p role="alert">此授权没有可运行的工具，无法准备接入。请重新起草并确认所需权限；系统不会自动增加工具权限。</p> : readiness.status === 'prepared' ? <>
        <p role="status">实例权限已准备。接入配置和运行保护仍需分别验证。</p>
        <div className="import-actions"><button type="button" className="btn btn-primary" disabled={busy} onClick={() => setDialog('adapter')}>管理此实例接入</button>
          <button type="button" className="btn" disabled={busy} onClick={() => setDialog('check')}>运行此实例自检</button></div>
      </> : <div className="field">
        {readiness.status === 'incomplete' ? <p>上次权限准备中断，尚未启用。确认后以原操作者 {readiness.binding?.actor_id} 重试原操作。</p> : null}
        <label className="install-confirmation"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(e) => setConfirmed(e.target.checked)} />确认以上权限用于此 Hermes 实例的会话</label>
        <button type="button" className="btn btn-primary" disabled={busy || !confirmed || !(readiness.binding?.actor_id || actorId.trim())} onClick={() => void prepare()}>{readiness.status === 'incomplete' ? '重试原权限准备' : '确认并准备实例权限'}</button>
      </div>}
    </> : null}
    <button type="button" className="btn" disabled={busy} onClick={() => setRefresh((n) => n + 1)}>重新查询权限准备状态</button>
    {dialog === 'adapter' ? <AdapterChangeDialog request={{ platform: 'hermes', action: 'install', instanceId: view.plan.instance_id, grantId: view.plan.grant_id }} onClose={closeDialog} onApplied={(m) => { setMessage(m); closeDialog(); }} /> : null}
    {dialog === 'check' ? <RuntimeCheckDialog instanceId={view.plan.instance_id} onClose={closeDialog} /> : null}
  </section>;
}
