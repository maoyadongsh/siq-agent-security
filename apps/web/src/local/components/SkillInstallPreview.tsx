import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import { newImportId } from '../skillImports';
import { installDirectoryValid, matchesInstallAuthority, skillInstallErrorText } from '../skillInstall';
import type { Grant, ImportPermissionSource, SkillInstallPlan, SkillInstallRequest } from '../types';

export default function SkillInstallPreview({ grant, source, skillName, onOperation }: { grant: Grant; source: ImportPermissionSource; skillName: string; onOperation: (message?: string, pending?: boolean) => void }) {
  const [params, setParams] = useSearchParams();
  const installId = params.get('install_id') ?? '';
  const [confirmed, setConfirmed] = useState(false);
  const planId = params.get('install_plan') ?? '';
  const { actorId } = useLocalSession();
  const [directory, setDirectory] = useState(() => installDirectoryValid(skillName) ? skillName : '');
  const [pending, setPending] = useState<SkillInstallRequest | null>(null);
  const [plan, setPlan] = useState<SkillInstallPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [now, setNow] = useState(Date.now);
  const active = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  useEffect(() => () => {
    active.current?.abort();
    if (submitting.current) onOperation('提交已中断，请重新查询原操作结果。');
  }, [onOperation]);
  useEffect(() => {
    if (!planId || installId) return;
    const controller = new AbortController();
    setRestoring(true); setConfirmed(false); setPlan(null); setError(null);
    localApi.installPlan(planId, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      if (!matchesInstallAuthority(value, grant, source)) throw new Error('skill_install_incompatible_response');
      setPlan(value); setDirectory(value.directory_name); setNow(Date.now());
    }).catch((err: unknown) => { if (!controller.signal.aborted) setError(skillInstallErrorText(err)); })
      .finally(() => { if (!controller.signal.aborted) setRestoring(false); });
    return () => controller.abort();
  }, [planId, installId, epoch, grant, source]);
  useEffect(() => {
    if (!plan) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [plan]);
  const working = busy || restoring;
  const expired = !!plan && now >= Date.parse(plan.expires_at);
  const prepare = async (original?: SkillInstallRequest) => {
    if (submitting.current || working || grant.state_revision === undefined) return;
    const body: SkillInstallRequest = original ?? {
      schema_version: 'local-skill-install-stage-create/v1', request_id: newImportId().replace(/^si-/, 'is-'),
      grant_id: grant.grant_id, expected_revision: grant.state_revision,
      instance_id: grant.subject.id.replace(/^hri-/, 'hi-'), directory_name: directory, actor_id: actorId.trim(),
    };
    if (!installDirectoryValid(body.directory_name) || !body.actor_id) return;
    submitting.current = true; setBusy(true); setError(null); setPlan(null); setPending(body);
    const controller = new AbortController(); active.current = controller;
    try {
      const result = await localApi.createInstallPlan(body, controller.signal);
      if (controller.signal.aborted) return;
      if (!matchesInstallAuthority(result.plan, grant, source)) throw new Error('skill_install_incompatible_response');
      setParams((previous) => {
        const next = new URLSearchParams(previous); next.set('grant', grant.grant_id); next.set('install_plan', result.plan.plan_id); return next;
      });
    } catch (err) { if (!controller.signal.aborted) setError(skillInstallErrorText(err)); }
    finally { submitting.current = false; if (!controller.signal.aborted) setBusy(false); }
  };
  const install = async () => {
    if (submitting.current || working || !plan || expired || !confirmed || actorId.trim() !== plan.actor_id) return;
    submitting.current = true; setBusy(true); setError(null);
    const controller = new AbortController(); active.current = controller;
    onOperation(undefined, true);
    setParams((previous) => { const next = new URLSearchParams(previous); next.delete('install_plan'); next.set('install_id', plan.plan_id.replace(/^sip-/, 'sin-')); return next; });
    try {
      await localApi.applySkillInstall({ schema_version: 'local-skill-install-apply/v1', plan_id: plan.plan_id,
        plan_signature: plan.signature, actor_id: plan.actor_id, confirm_install: true }, controller.signal);
      if (!controller.signal.aborted) onOperation();
    } catch (err) { if (!controller.signal.aborted) onOperation(skillInstallErrorText(err)); }
    finally { submitting.current = false; if (!controller.signal.aborted) { setBusy(false); setRestoring(false); } }
  };
  const reset = () => {
    if (working) return;
    setPending(null); setPlan(null); setError(null);
    setParams((previous) => { const next = new URLSearchParams(previous); next.delete('install_plan'); next.set('grant', grant.grant_id); return next; });
  };
  if (installId) return busy ? <p role="status">正在提交安装，请稍候。结果可按原操作编号重新查询。</p> : null;
  return <section className="skill-install-preview" aria-labelledby="install-preview-heading">
    <h3 id="install-preview-heading">安装预览</h3>
    <p className="page-desc">权限已批准。先核对安装位置与内容；生成预览会准备本机暂存副本，尚未安装到 Hermes。</p>
    <p className="page-desc">目标为此授权绑定的 Hermes 实例；操作者沿用上方填写的批准人。</p>
    <div className="field"><label htmlFor="install-directory">Skill 安装目录名</label>
      <input id="install-directory" value={directory} onChange={(event) => setDirectory(event.target.value)} maxLength={64}
        disabled={working || !!pending || !!planId} aria-describedby="install-directory-help" />
      <p id="install-directory-help" className="page-desc">1–64 个小写字母、数字或连字符，首尾为字母或数字；不能覆盖已有目录。</p>
    </div>
    {error ? <p className="action-error" role="alert">{error}</p> : null}
    {working ? <p role="status">正在核对权限、内容与目标目录…</p> : null}
    {plan ? <div className="install-plan-result">
      <p role="status">{expired ? '预览已到期，请重新准备。' : '预览已核验，尚未安装。'}</p>
      <dl>
        <dt>目标位置</dt><dd>{plan.target_display}</dd>
        <dt>待安装文件</dt><dd>{plan.file_count} 个 · {plan.total_bytes.toLocaleString()} 字节</dd>
        <dt>预览到期时间</dt><dd><time dateTime={plan.expires_at}>{new Date(plan.expires_at).toLocaleString()}</time></dd>
        <dt>副本摘要</dt><dd><code>{plan.source.artifact_digest}</code></dd>
        <dt>权限摘要</dt><dd><code>{plan.grant_permission_digest}</code></dd>
      </dl>
      <p className="page-desc">安装会写入上方新目录。完成后仍需平台识别与保护验证，当前不会启用此 Skill 的运行权限。</p>
    </div> : null}
    {plan && !expired ? <div className="field">
      <label className="install-confirmation"><input type="checkbox" checked={confirmed} disabled={working} onChange={(event) => setConfirmed(event.target.checked)} /> 我已核对安装位置、内容和权限，确认安装</label>
      {actorId.trim() !== plan.actor_id ? <p role="alert">操作者已变化，请恢复为 {plan.actor_id} 或重新准备预览。</p> : null}
    </div> : null}
    <div className="import-actions">
      {plan ? <button type="button" className="btn btn-primary" disabled={working || expired || !confirmed || actorId.trim() !== plan.actor_id} onClick={() => void install()}>确认安装 Skill</button> : null}
      {!pending && !planId ? <button type="button" className="btn btn-primary" disabled={working || !installDirectoryValid(directory) || !actorId.trim() || grant.state_revision === undefined} onClick={() => void prepare()}>生成安装预览</button> : null}
      {pending && error && !planId ? <button type="button" className="btn" disabled={working} onClick={() => void prepare(pending)}>重试原预览请求</button> : null}
      {planId ? <button type="button" className="btn" disabled={working || expired} onClick={() => setEpoch((value) => value + 1)}>重新核验预览</button> : null}
      {pending || planId ? <button type="button" className="btn" disabled={working} onClick={reset}>重新准备预览</button> : null}
    </div>
  </section>;
}
