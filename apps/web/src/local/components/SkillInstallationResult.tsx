import InstalledSkillProtection from './InstalledSkillProtection';
import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { localApi, LocalApiError } from '../api';
import { useLocalSession } from '../session';
import { skillInstallErrorText } from '../skillInstall';
import type { SkillInstallView } from '../types';

export default function SkillInstallationResult({ epoch, submissionMessage, processing }: { epoch: number; submissionMessage?: string; processing: boolean }) {
  const [params, setParams] = useSearchParams();
  const id = params.get('install_id') ?? '';
  const { actorId } = useLocalSession();
  const [view, setView] = useState<SkillInstallView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const active = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    if (!id) return;
    if (processing) { setView(null); setBusy(false); setError(null); return; }
    const controller = new AbortController();
    setBusy(true); setView(null); setError(null); setMissing(false); setConfirmed(false);
    localApi.skillInstallation(id, controller.signal).then((value) => {
      if (!controller.signal.aborted) setView(value);
    }).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      setMissing(err instanceof LocalApiError && err.status === 404);
      setError(skillInstallErrorText(err));
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [id, epoch, refresh, processing]);
  const [protectionBusy, setProtectionBusy] = useState(false);
  const working = busy || processing || protectionBusy;
  const recover = async () => {
    if (submitting.current || working || !confirmed || !actorId.trim() || view?.status !== 'recovery_required') return;
    submitting.current = true; setBusy(true); setView(null); setError(null); setConfirmed(false);
    const controller = new AbortController(); active.current = controller;
    try { const result = await localApi.recoverSkillInstallation(id, actorId.trim(), controller.signal); if (!controller.signal.aborted) setView(result); }
    catch (err) { if (!controller.signal.aborted) setError(skillInstallErrorText(err)); }
    finally { submitting.current = false; if (!controller.signal.aborted) setBusy(false); }
  };
  if (!id) return null;
  const status = view?.status;
  return <section className="card skill-install-preview" aria-labelledby="installation-result-heading">
    <h2 id="installation-result-heading">Skill 安装结果</h2>

    {working ? <p role="status">正在查询或处理安装操作…</p> : null}
    {!working && error ? <p className="action-error" role="alert">{error} 当前无法确认安装状态。</p> : null}
    {!working && !view && submissionMessage ? <p role="alert">{submissionMessage}</p> : null}
    {view ? <>
      <p role="status">{status === 'installed_unverified' ? 'Skill 文件已安装并完成内容核验，尚未验证运行保护。' : status === 'rolled_back' ? '安装未完成，已记录回滚完成。' : '安装未完成，需要恢复。'}</p>
      <dl><dt>目标位置</dt><dd>{view.plan.target_display}</dd>
        <dt>记录时间</dt><dd>{view.operation ? new Date(view.operation.recorded_at).toLocaleString() : '尚无最终结果记录'}</dd>
      </dl>
      <details><summary>查看来源与授权记录</summary>
      <dl><dt>操作编号</dt><dd><code>{id}</code></dd><dt>绑定授权</dt><dd><code>{view.plan.grant_id}</code></dd>
        <dt>副本摘要</dt><dd><code>{view.plan.source.artifact_digest}</code></dd>
      </dl></details>
      <p className="page-desc">安装和恢复不会启用运行权限。回滚结果是历史记录；平台识别与保护验证仍待完成。</p>
      {status === 'installed_unverified' ? <InstalledSkillProtection view={view} onBusy={setProtectionBusy} /> : null}
      {status === 'recovery_required' ? <div className="field">
        <p>恢复仅清理本次安装创建、内容未改变且归属可证的对象。新增、修改或归属不明的内容会保留。</p>
        <label className="install-confirmation"><input type="checkbox" checked={confirmed} disabled={working} onChange={(event) => setConfirmed(event.target.checked)} /> 确认恢复此次失败安装</label>
        <button type="button" className="btn" disabled={working || !confirmed || !actorId.trim()} onClick={() => void recover()}>恢复失败安装</button>
      </div> : null}
    </> : null}
    <div className="import-actions">
      {!working ? <Link className="btn" to={`/installed-skills?install_id=${encodeURIComponent(id)}`}>查看内容变化</Link> : null}
      <button type="button" className="btn" disabled={working} onClick={() => setRefresh((value) => value + 1)}>重新查询安装结果</button>
      {!working && missing && /^sin-[a-f0-9]{64}$/.test(id) ? <button type="button" className="btn" onClick={() => setParams((previous) => {
        const next = new URLSearchParams(previous); next.delete('install_id'); next.set('install_plan', id.replace(/^sin-/, 'sip-')); return next;
      })}>重新核验原预览</button> : null}
    </div>
    {!working && missing ? <p className="page-desc">尚未读到操作记录。若刚提交，请先重新查询；原请求不会自动重发。</p> : null}
  </section>;
}
