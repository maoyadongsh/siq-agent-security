import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import { isCurrentSkillUpdateRequest, planSkillUpdateSourceToggle, updateCheckErrorText, type SkillUpdateCheckResult, type SkillUpdateScheduleView } from '../skillUpdateCheck';
import type { SkillImportSourceKind } from '../types';

type SourceProbe = { state: 'loading' | 'unknown' | 'ready'; kind: SkillImportSourceKind | null; git?: { url: string; commit_sha: string } | null };
type ScheduleState = { state: 'loading' | 'unavailable' } | { state: 'ready'; view: SkillUpdateScheduleView };

const sourceUnavailable = (kind: SkillImportSourceKind) => kind === 'local_dir' || kind === 'local_zip';

const scheduleStatusText: Record<SkillUpdateScheduleView['status'], string> = {
  not_checked: '尚未检查', checking: '检查中', up_to_date: '上游内容一致', new_version: '发现新版',
  source_unavailable: '上游暂不可用', unsupported: '来源不支持自动检查',
};

export default function SkillUpdateCheckPanel({ installId, importId = '', disabled = false }: { installId: string; importId?: string; disabled?: boolean }) {
  const { actorId, status } = useLocalSession();
  const signer = status?.signing_public_key;
  const connected = status !== null;
  const [url, setUrl] = useState('');
  const [probe, setProbe] = useState<SourceProbe>({ state: 'unknown', kind: null });
  const [schedule, setSchedule] = useState<ScheduleState>({ state: 'loading' });
  const [result, setResult] = useState<SkillUpdateCheckResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  const requestIdentity = [installId, importId, actorId, signer ?? '', connected ? 'connected' : 'disconnected'].join('\u0000');
  const currentIdentity = useRef(requestIdentity);
  // Render updates this synchronously, before effect cleanup can abort an old
  // request. A response owned by the previous object therefore cannot write
  // into the newly rendered installation, even in that narrow transition.
  currentIdentity.current = requestIdentity;
  useEffect(() => {
    setUrl('');
    return () => { active.current?.abort(); active.current = null; };
  }, [installId, importId, actorId, signer, connected]);
  useEffect(() => {
    active.current?.abort(); active.current = null; setBusy(false); setResult(null); setError('');
    setProbe(importId ? { state: 'loading', kind: null } : { state: 'unknown', kind: null });
    if (!importId) return;
    const controller = new AbortController();
    const owner = requestIdentity;
    void (async () => {
      try {
        const detail = await localApi.skillImport(importId, controller.signal);
        if (!isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) return;
        setProbe(detail.import.source_kind === 'git'
          ? { state: 'ready', kind: 'git', git: { url: detail.import.git.url, commit_sha: detail.import.git.commit_sha } }
          : { state: 'ready', kind: detail.import.source_kind });
      } catch {
        if (isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) setProbe({ state: 'unknown', kind: null });
      }
    })();
    return () => controller.abort();
  }, [installId, importId, disabled, actorId, signer, connected]);
  useEffect(() => {
    setSchedule({ state: 'loading' });
    if (!/^sin-[a-f0-9]{64}$/.test(installId)) { setSchedule({ state: 'unavailable' }); return; }
    const controller = new AbortController();
    const owner = requestIdentity;
    void (async () => {
      try {
        const view = await localApi.readSkillUpdateSource(installId, controller.signal);
        if (isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) setSchedule({ state: 'ready', view });
      } catch {
        if (isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) setSchedule({ state: 'unavailable' });
      }
    })();
    return () => controller.abort();
  }, [installId, actorId, signer, connected]);
  const gitMode = probe.state === 'ready' && probe.kind === 'git';
  const blockedSource = probe.state === 'ready' && probe.kind !== null && sourceUnavailable(probe.kind);
  const scheduleReady = schedule.state === 'ready';
  const savedView = scheduleReady && schedule.view.source_state === 'saved' ? schedule.view : null;
  const cancel = () => { active.current?.abort(); active.current = null; setBusy(false); setError('检查已取消。'); };
  const run = async (action: (controller: AbortController, owner: string) => Promise<void>) => {
    if (active.current || disabled || !actorId.trim()) return;
    const controller = new AbortController(); active.current = controller;
    const owner = requestIdentity;
    setBusy(true); setError('');
    try {
      await action(controller, owner);
    } catch (err) {
      if (active.current === controller && isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) setError(updateCheckErrorText(err));
    } finally {
      if (active.current === controller) {
        active.current = null;
        if (isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) setBusy(false);
      }
    }
  };
  const check = () => {
    if (blockedSource || probe.state === 'loading') return;
    if (!gitMode && !url.trim()) return;
    setResult(null);
    void run(async (controller, owner) => {
      const data = await localApi.checkSkillUpdate(installId, { schema_version: 'local-skill-update-check/v1', remote_url: gitMode ? '' : url.trim(), actor_id: actorId.trim() }, controller.signal);
      if (active.current === controller && isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) setResult(data);
    });
  };
  // The caller-provided URL lives in React state only: it is sent once with the
  // save request and dropped afterwards; the panel then shows the redacted
  // display form returned by the service. It is never written to Web Storage.
  const saveSource = (remoteURL: string, enable: boolean) => {
    setResult(null);
    void run(async (controller, owner) => {
      const view = await localApi.saveSkillUpdateSource(installId, { schema_version: 'local-skill-update-source-save/v1', remote_url: remoteURL, enable, actor_id: actorId.trim() }, controller.signal);
      if (active.current === controller && isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) {
        setSchedule({ state: 'ready', view });
        if (!gitMode) setUrl('');
      }
    });
  };
  const disableSource = () => {
    setResult(null);
    void run(async (controller, owner) => {
      const view = await localApi.disableSkillUpdateSource(installId, { schema_version: 'local-skill-update-source-disable/v1', actor_id: actorId.trim() }, controller.signal);
      if (active.current === controller && isCurrentSkillUpdateRequest(owner, currentIdentity.current, controller.signal.aborted)) setSchedule({ state: 'ready', view });
    });
  };
  const toggleSchedule = () => {
    if (!scheduleReady) return;
    const plan = planSkillUpdateSourceToggle(schedule.view, url);
    if (plan.kind === 'disable') { disableSource(); return; }
    if (plan.kind === 'save') { saveSource(plan.remoteURL, true); return; }
    setError(plan.message);
  };
  const description = gitMode
    ? '检查 Git 仓库上游是否有内容变化，不会自动更新文件或权限。检查固定在导入时的仓库地址与提交。'
    : blockedSource ? '此安装来自本机目录或 ZIP，没有可检查的上游。如需新版，请重新导入新的候选。'
      : '检查原 HTTPS ZIP 来源是否有内容变化，不会自动更新文件或权限。';
  const offerSave = scheduleReady && !gitMode && !blockedSource && ['needs_source', 'stale'].includes(schedule.view.source_state);
  const versionLinks = <div className="import-actions"><Link className="btn" to="/skill-imports">重新导入候选</Link><Link className="btn" to={`/skill-updates?install_id=${encodeURIComponent(installId)}`}>审阅候选并更新</Link></div>;
  return <section className="panel import-panel" aria-label="检查 Skill 新版">
    <h3>检查新版</h3>
    <p className="page-desc">{description}</p>
    {probe.state === 'loading' ? <p role="status" className="page-desc">正在读取来源类型…</p> : null}
    {gitMode && probe.git ? <p className="page-desc">已固定来源 <code>{probe.git.url}</code> · 提交 <code>{probe.git.commit_sha}</code></p> : null}
    {schedule.state === 'loading' ? <p role="status" className="page-desc">正在读取自动检查状态…</p> : null}
    {scheduleReady && schedule.view.source_state === 'unsupported' ? <p className="page-desc">此安装来自本机目录或 ZIP，不支持自动检查新版。</p> : null}
    {scheduleReady && schedule.view.source_state === 'stale' ? <p className="page-desc">已保存的来源与当前安装记录不一致（安装可能被重装或替换）。请重新填写并保存原下载链接。</p> : null}
    {scheduleReady && schedule.view.source_state === 'needs_source' ? <p className="page-desc">{gitMode ? '此 Git 安装尚未启用自动检查，可立即开启。' : '尚未保存自动检查来源。可在下方填写原下载链接并保存。'}</p> : null}
    {savedView ? <p className="page-desc">自动检查已{savedView.enabled ? '启用' : '停用'}：来源 <code>{savedView.display}</code> · 上次结果：{scheduleStatusText[savedView.status]}
      {savedView.next_check_at ? ` · 下次检查：${new Date(savedView.next_check_at).toLocaleString()}` : ''}
      {savedView.last_success_at ? ` · 上次成功：${new Date(savedView.last_success_at).toLocaleString()}` : ''}
    </p> : null}
    {savedView && savedView.status === 'new_version' ? versionLinks : null}
    {savedView && !gitMode ? <p className="page-desc">停止自动检查无需重新输入链接；重新启用或更换来源时需要再次提供原下载链接。</p> : null}
    {scheduleReady && (gitMode || !blockedSource) ? <div className="import-actions">
      {scheduleReady && schedule.view.source_state !== 'unsupported'
        ? <button className="btn" type="button" disabled={disabled || busy || !actorId.trim()} onClick={toggleSchedule}>{savedView?.enabled ? '停止自动检查' : '启用自动检查'}</button>
        : null}
    </div> : null}
    {probe.state !== 'loading' && !blockedSource ? <form onSubmit={(event) => { event.preventDefault(); check(); }}>
      {gitMode ? null : <div className="field">
        <label htmlFor="skill-update-source-url">原 HTTPS ZIP 下载链接</label>
        <input id="skill-update-source-url" type="url" required maxLength={4096} value={url} autoComplete="off" spellCheck={false}
          disabled={disabled || busy} placeholder="https://…/skill.zip" onChange={(event) => { setUrl(event.target.value); setResult(null); setError(''); }} />
        <p className="page-desc">使用首次导入时的链接。链接仅发送给本机服务，不会写入浏览器存储。</p>
      </div>}
      <div className="import-actions"><button className="btn" type="submit" disabled={disabled || busy || (!gitMode && !url.trim()) || !actorId.trim()}>检查新版</button>
        {offerSave ? <button className="btn" type="button" disabled={disabled || busy || !url.trim() || !actorId.trim()} onClick={() => saveSource(url.trim(), true)}>保存来源并启用自动检查</button> : null}
        {busy ? <button className="btn" type="button" onClick={cancel}>取消检查</button> : null}</div>
    </form> : null}
    {busy ? <p role="status">正在获取上游并比较内容…</p> : null}
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    {result ? <div>
      <p role="status">{result.status === 'up_to_date' ? '上游内容与安装记录一致。' : `发现 ${result.content_changes_total} 项内容变化，需要你确认后更新。`}</p>
      <p className="page-desc">检查时间：{new Date(result.checked_at).toLocaleString()}。权限差异将在导入候选后审阅。</p>
      {result.content_changes_truncated ? <p>仅显示前 200 项变化。</p> : null}
      <ul>{result.content_changes.map((change) => <li key={change.path_digest}>{change.before === null ? '新增' : change.after === null ? '删除' : '修改'}：{change.path_display}</li>)}</ul>
      {result.requires_confirmation ? versionLinks : null}
    </div> : null}
  </section>;
}
